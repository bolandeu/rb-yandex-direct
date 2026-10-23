"""LiveClient — API Директа v4 Live: то, чего нет в v5 (Wordstat, прогноз бюджета, финансы, общий счёт…).

Протокол (yandex.ru/dev/direct/doc/dg-v4/ru/concepts/JSON): один адрес
`POST https://api.direct.yandex.ru/live/v4/json/` (песочница — api-sandbox.direct.yandex.ru),
тело `{"method", "param", "token", "locale"}`; финансовые методы добавляют в тело
`finance_token` и `operation_num`. Ответ — `{"data": ...}`; ошибка — HTTP 200 и
`{"error_code", "error_str", "error_detail"}` в теле.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ..core.errors import DirectAPIError
from ..core.version import DEV_VERSION, cli_name, installed_version

log = logging.getLogger(__name__)

LIVE_PROD = "https://api.direct.yandex.ru/live/v4/json/"
LIVE_SANDBOX = "https://api-sandbox.direct.yandex.ru/live/v4/json/"

# «Не сейчас», а не «нет»: 52 — аутентификация временно недоступна, 56 — превышен лимит
# запросов, 57 — лимит одновременных запросов метода, 358 — финансовые операции временно
# недоступны. Такие ответы значат, что запрос не выполнен, — повторять безопасно.
RETRY_API_CODES = frozenset({52, 56, 57, 358})
RETRY_HTTP = frozenset({429, 502, 503, 504})
# Учётные данные: 53 — авторизация, 54 — нет прав, 58 — незавершённая регистрация,
# 350 — неверный финансовый токен, 352 — финансовые операции недоступны аккаунту.
LIVE_CREDENTIAL_CODES = frozenset({53, 54, 58, 350, 352})


class LiveAPIError(DirectAPIError):
    """Ошибка v4 Live. Коды учётных данных свои (LIVE_CREDENTIAL_CODES), остальное как у v5."""

    def __init__(self, error_code: int, error_string: str, error_detail: str = "", request_id: str | None = None):
        super().__init__(error_code, error_string, error_detail, request_id)
        if error_code in (350, 352):
            self.action = (
                f"Проверьте мастер-токен и доступ к финансовым операциям в Директе, затем `{cli_name()} finance setup`."
            )
        elif error_code == 351:
            self.action = (
                "Номер финансовой операции не больше предыдущего: сбросьте счётчик в Директе "
                "(Настройки API → Финансовые операции) или повторите — следующий номер будет больше."
            )

    @property
    def is_auth_error(self) -> bool:
        return self.error_code in LIVE_CREDENTIAL_CODES

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["provider"] = "direct-live"
        return payload


@dataclass(frozen=True)
class Finance:
    """Поля финансового метода: верхний уровень тела рядом с `method` и `param`."""

    finance_token: str
    operation_num: int


class LiveClient:
    """Клиент v4 Live.

    Args:
        token: OAuth-токен Директа (тот же, что для v5).
        client_login: логин клиента агентства — заголовок Client-Login.
        sandbox: песочница.
        transport: для тестов (`httpx.MockTransport`); в рабочем коде None.

    Временные сбои (RETRY_API_CODES, HTTP 429/5xx, сеть) повторяются `retries` раз.
    Финансовые вызовы не повторяются при сетевых сбоях и 5xx: неизвестно, прошла ли
    операция, а повтор с тем же operation_num API всё равно отвергнет (код 351).
    """

    retries: int = 2
    backoff: float = 1.0

    def __init__(
        self,
        token: str,
        client_login: str | None = None,
        sandbox: bool = False,
        locale: str = "ru",
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.token = token
        self.client_login = client_login
        self.sandbox = sandbox
        self.url = LIVE_SANDBOX if sandbox else LIVE_PROD
        self.locale = locale
        self.timeout = timeout
        self.transport = transport

    def body(self, method: str, param: Any = None, finance: Finance | None = None) -> dict[str, Any]:
        """Тело запроса без токена — его же показывает --dry-run."""
        body: dict[str, Any] = {"method": method}
        if param is not None:
            body["param"] = param
        if finance is not None:
            body["finance_token"] = finance.finance_token
            body["operation_num"] = finance.operation_num
        body["locale"] = self.locale
        return body

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": f"{cli_name()}/{installed_version() or DEV_VERSION}",
        }
        if self.client_login:
            headers["Client-Login"] = self.client_login
        return headers

    async def call(self, method: str, param: Any = None, *, finance: Finance | None = None) -> Any:
        """Вызвать метод v4 Live; вернуть содержимое `data`."""
        payload = json.dumps({**self.body(method, param, finance), "token": self.token}, ensure_ascii=False)
        attempt = 0
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            while True:
                try:
                    resp = await client.post(self.url, content=payload.encode("utf-8"), headers=self._headers())
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    if finance is None and attempt < self.retries:
                        attempt += 1
                        await asyncio.sleep(self.backoff * 2 ** (attempt - 1))
                        continue
                    raise LiveAPIError(0, "Сеть", f"{type(exc).__name__}: {exc}") from exc
                data = _parse(resp)
                code = _error_code(data)
                retry_http = resp.status_code in RETRY_HTTP and finance is None
                if (code in RETRY_API_CODES or retry_http) and attempt < self.retries:
                    attempt += 1
                    await asyncio.sleep(self.backoff * 2 ** (attempt - 1))
                    continue
                break
        if code:
            raise LiveAPIError(code, str(data.get("error_str", "")), str(data.get("error_detail", "")))
        if resp.status_code >= 400:
            raise LiveAPIError(resp.status_code, f"HTTP {resp.status_code}", resp.text[:500])
        log.debug("v4 %s ok", method)
        return data.get("data")


def _parse(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError as exc:
        if resp.status_code >= 400:
            return {}
        raise LiveAPIError(resp.status_code, "Invalid JSON", str(exc)) from exc
    return data if isinstance(data, dict) else {"data": data}


def _error_code(data: dict[str, Any]) -> int:
    try:
        return int(data.get("error_code") or 0)
    except TypeError, ValueError:
        return 0
