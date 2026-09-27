"""OAuth 2.0 для Яндекса.

Источники:
- https://yandex.ru/dev/direct/doc/ru/concepts/auth-token (подтверждено WebFetch)
- https://yandex.ru/dev/direct/doc/ru/concepts/register  (scope direct:api, passport:business)
- https://yandex.ru/dev/id/doc/ru/codes/code-url
- https://yandex.ru/dev/id/doc/ru/tokens/device

Три потока:
1. authorization_code + localhost callback — основной для CLI, открывает браузер.
2. OOB — redirect_uri=https://oauth.yandex.ru/verification_code, пользователь копирует код вручную.
3. device flow — для headless окружений (по ssh без браузера).
"""

from __future__ import annotations

import asyncio
import base64
import http.server
import secrets
import socket
import threading
import urllib.parse
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from rb_yandex_direct.core.errors import DirectAuthError

OAUTH_BASE = "https://oauth.yandex.ru"
AUTHORIZE_URL = f"{OAUTH_BASE}/authorize"
TOKEN_URL = f"{OAUTH_BASE}/token"
DEVICE_CODE_URL = f"{OAUTH_BASE}/device/code"
OOB_REDIRECT = f"{OAUTH_BASE}/verification_code"
DIRECT_SCOPES = ("direct:api", "passport:business")


@dataclass
class OAuthToken:
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    token_type: str = "bearer"  # noqa: S105 — тип токена, не секрет
    scope: str = ""

    @classmethod
    def from_response(cls, data: dict) -> OAuthToken:
        expires_at = None
        if "expires_in" in data:
            expires_at = datetime.now(UTC) + timedelta(seconds=int(data["expires_in"]))
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            token_type=data.get("token_type", "bearer"),
            scope=data.get("scope", ""),
        )

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(UTC) >= self.expires_at - timedelta(minutes=5)


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    received_code: str | None = None
    received_error: str | None = None

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]
        type(self).received_code = code
        type(self).received_error = error

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if code:
            body = "<h1>Готово</h1><p>Токен получен, можно закрыть вкладку и вернуться в терминал.</p>"
        else:
            body = f"<h1>Ошибка</h1><p>{error or 'код не получен'}</p>"
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args, **kwargs) -> None:
        pass


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class YandexOAuth:
    """Клиент OAuth 2.0 для Яндекса.

    Args:
        client_id: ID приложения (из https://oauth.yandex.ru/?dialog=create-client-entry)
        client_secret: secret приложения
        scopes: запрашиваемые права. По умолчанию direct:api + passport:business.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        scopes: tuple[str, ...] = DIRECT_SCOPES,
    ) -> None:
        if not client_id or not client_secret:
            raise DirectAuthError("client_id и client_secret обязательны")
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes

    def build_authorize_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": " ".join(self.scopes),
            "force_confirm": "yes",
        }
        return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str | None = None) -> OAuthToken:
        """Обменять authorization code на access+refresh токены."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        if redirect_uri:
            data["redirect_uri"] = redirect_uri
        return await self._token_request(data)

    async def refresh(self, refresh_token: str) -> OAuthToken:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        return await self._token_request(data)

    async def _token_request(self, data: dict[str, str]) -> OAuthToken:
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        headers = {
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(TOKEN_URL, data=data, headers=headers)
        if resp.status_code != 200:
            raise DirectAuthError(f"OAuth ошибка {resp.status_code}: {resp.text}")
        return OAuthToken.from_response(resp.json())

    async def authorize_interactive(
        self,
        port: int | None = None,
        open_browser: bool = True,
        print_url: Callable[[str], None] | None = print,
    ) -> OAuthToken:
        """Локальный callback-поток: открывает браузер, ловит code на 127.0.0.1:<port>."""
        port = port or _free_port()
        redirect_uri = f"http://localhost:{port}/"
        state = secrets.token_urlsafe(16)
        url = self.build_authorize_url(redirect_uri, state)

        _CallbackHandler.received_code = None
        _CallbackHandler.received_error = None
        server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            if print_url:
                print_url(f"Открываю в браузере: {url}")
            if open_browser:
                webbrowser.open(url)
            loop = asyncio.get_event_loop()
            code = await loop.run_in_executor(None, self._wait_for_code, 300)
        finally:
            server.shutdown()
            server.server_close()
        return await self.exchange_code(code, redirect_uri=redirect_uri)

    @staticmethod
    def _wait_for_code(timeout_sec: int) -> str:
        import time

        start = time.time()
        while time.time() - start < timeout_sec:
            if _CallbackHandler.received_error:
                raise DirectAuthError(f"OAuth отказ: {_CallbackHandler.received_error}")
            if _CallbackHandler.received_code:
                return _CallbackHandler.received_code
            time.sleep(0.2)
        raise DirectAuthError("Таймаут ожидания authorization code")

    async def authorize_oob(self, code: str) -> OAuthToken:
        """Out-of-band: пользователь открыл authorize с redirect_uri=OOB_REDIRECT,
        скопировал код со страницы подтверждения и ввёл его вручную."""
        return await self.exchange_code(code, redirect_uri=OOB_REDIRECT)

    def build_oob_url(self) -> str:
        state = secrets.token_urlsafe(8)
        return self.build_authorize_url(OOB_REDIRECT, state)

    # --- Device flow ---
    async def device_code_start(self) -> dict:
        data = {"client_id": self.client_id, "scope": " ".join(self.scopes)}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(DEVICE_CODE_URL, data=data)
        if resp.status_code != 200:
            raise DirectAuthError(f"device_code ошибка {resp.status_code}: {resp.text}")
        return resp.json()

    async def device_code_poll(self, device_code: str, interval: int = 5, timeout: int = 600) -> OAuthToken:
        """Polling /token с grant_type=device_code до получения access_token."""
        data = {
            "grant_type": "device_code",
            "code": device_code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                return await self._token_request(data)
            except DirectAuthError as e:
                if "authorization_pending" in str(e) or "slow_down" in str(e):
                    await asyncio.sleep(interval)
                    continue
                raise
        raise DirectAuthError("Таймаут device flow")
