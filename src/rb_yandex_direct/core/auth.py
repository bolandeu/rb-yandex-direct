"""Токен Директа — общая библиотека rb-yandex-oauth (keychain ОС + переменные окружения).

У Директа свой слот, а не общий `yandex-oauth:yandex` инструментов ym/ywm: API Директа
принимает токен только от приложения с подтверждённой заявкой на доступ (иначе код 58) и
правами `direct:api passport:business`. Вход в Директ поэтому не перезаписывает общий токен.

- keychain: `yandex-oauth:direct`;
- env: `YANDEX_OAUTH_DIRECT_<FIELD>` (TOKEN, REFRESH_TOKEN, CLIENT_ID, CLIENT_SECRET, EXPIRES_AT);
  задан `YANDEX_OAUTH_DIRECT_REFRESH_TOKEN` — keychain не читается, токен обновляется в памяти;
- `YANDEX_DIRECT_TOKEN` — готовый access-токен без автообновления (разовые запуски, тесты).

`.env`-файлы не читаются. Client-Login (`--login`, `YANDEX_DIRECT_LOGIN`) — не секрет и не часть токена.
"""

from __future__ import annotations

import asyncio
import os
from importlib import metadata

from yandex_oauth import CredentialStore, Profile, TokenStore, status
from yandex_oauth.errors import AuthRequired, CliError, CredentialsUnhealthy

from rb_yandex_direct.core.client import DirectClient
from rb_yandex_direct.core.errors import DirectAPIError

DIST_NAME = "rb-yandex-direct"
CLI_NAME = "yd"

PROFILE = Profile(
    cli_name=CLI_NAME,
    token_env="YANDEX_DIRECT_TOKEN",  # noqa: S106 — имя переменной, не секрет
    scopes="direct:api passport:business",
    service="Яндекс.Директ",
    provider="direct",
)
credentials = CredentialStore(PROFILE)
store = TokenStore(PROFILE, credentials)

# Прежние имена переменных OAuth-приложения Директа (до перехода на rb-yandex-oauth).
LEGACY_CLIENT_ID_ENV = "YANDEX_DIRECT_CLIENT_ID"
LEGACY_CLIENT_SECRET_ENV = "YANDEX_DIRECT_CLIENT_SECRET"  # noqa: S105 — имя переменной, не секрет

# Ошибки API, означающие «токен/приложение/аккаунт не годятся», а не сбой сервиса:
# 53 — ошибка авторизации, 54 — нет прав, 58 — заявка на доступ не подтверждена,
# 513 — логин не подключён к Директу, 1002 — токен недействителен.
CREDENTIAL_ERROR_CODES = frozenset({53, 54, 58, 513, 1002})


def version() -> str:
    try:
        return metadata.version(DIST_NAME)
    except metadata.PackageNotFoundError:
        return "0.0.0"


def app_credentials(client_id: str | None = None, client_secret: str | None = None) -> tuple[str | None, str | None]:
    """OAuth-приложение Директа: аргумент → YANDEX_OAUTH_DIRECT_CLIENT_* → YANDEX_DIRECT_CLIENT_* → keychain."""
    stored = store.stored()
    cid = client_id or os.getenv(store.env_var("client_id")) or os.getenv(LEGACY_CLIENT_ID_ENV)
    secret = client_secret or os.getenv(store.env_var("client_secret")) or os.getenv(LEGACY_CLIENT_SECRET_ENV)
    return cid or stored.get("client_id"), secret or stored.get("client_secret")


def resolve_token() -> str:
    """Действующий access-токен (обновляется сам по refresh_token); нет токена — AuthRequired."""
    token, _refreshable = store.resolve()
    if not token:
        raise AuthRequired(PROFILE)
    return token


def as_cli_error(exc: DirectAPIError) -> CliError:
    """Ошибка API → CliError: учётные данные (exit 3, `invalid` в auth status) или сбой сервиса (exit 5)."""
    if exc.error_code in CREDENTIAL_ERROR_CODES:
        return CliError(
            "AUTH_INVALID",
            f"Директ не принял учётные данные: [{exc.error_code}] {exc.error_string}. {exc.error_detail}".strip(),
            action=f"Проверьте заявку на доступ к API и выполните '{PROFILE.login_cmd}'.",
            exit_code=3,
        )
    return CliError("PROVIDER_ERROR", str(exc), exit_code=5)


def _units_quota(units: str | None) -> dict | None:
    """Заголовок `Units: израсходовано/остаток/суточный лимит` → quota отчёта §8."""
    parts = (units or "").split("/")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return {"remaining": int(parts[1]), "limit": int(parts[2]), "unit": "points"}


def status_report(*, check: bool, sandbox: bool = False) -> tuple[dict, CredentialsUnhealthy | None]:
    """Отчёт `auth status` по §8 стандарта tools; вторым — ошибка, если код выхода должен быть 3.

    Проверка (`check`) — один `clients.get` без Client-Login: дешёвый read-only запрос.
    """
    client: list[DirectClient] = []

    def probe() -> None:
        c = DirectClient(token=resolve_token(), sandbox=sandbox)
        client.append(c)
        try:
            asyncio.run(c.call("clients", "get", {"FieldNames": ["Login"]}))
        except DirectAPIError as exc:
            raise as_cli_error(exc) from exc

    entry = status.credential_status(store, live=check, check=probe)
    if entry["status"] == "ok" and client:
        entry["quota"] = _units_quota(client[0].last_units)
    report = status.status_report(CLI_NAME, version(), [entry])
    problems = status.status_problems(report)
    return report, (CredentialsUnhealthy(PROFILE, problems) if problems else None)
