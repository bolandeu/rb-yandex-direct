from __future__ import annotations

import asyncio
import os
import tomllib
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar

import tomli_w
from packaging.version import Version

from ..providers.direct import DirectClient
from ..providers.reports import ReportsClient
from .auth import resolve_token
from .errors import CliTooOld, DirectAPIError, InvalidArguments, ProjectNotInitialized
from .models import DirectConfig, ProjectConfig
from .version import cli_name, installed_version

# Папка проекта — по имени команды (`.yd/`), как у ym/ywm: её видит пользователь.
PROJECT_DIR_NAME = f".{cli_name()}"
CONFIG_FILE_NAME = "config.toml"


def find_project_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / PROJECT_DIR_NAME).is_dir():
            return candidate
    return None


def require_project_root(start: Path) -> Path:
    root = find_project_root(start)
    if root is None:
        raise ProjectNotInitialized(str(start))
    return root


def config_path(project_root: Path) -> Path:
    return project_root / PROJECT_DIR_NAME / CONFIG_FILE_NAME


def check_cli_compat(config: ProjectConfig) -> None:
    """Raise CliTooOld if this installed CLI is older than the project's `cli.min_version`.

    A project outlives any single CLI release; this is how it refuses to be
    driven by a CLI that predates a config field or command it relies on.
    Skipped for an uninstalled (bare source) run, which has no version, and
    for a build without a `v*` tag in reach (uv-dynamic-versioning's
    `0.0.0` fallback) — a dev checkout, not a release older than anything.
    """
    installed = installed_version()
    if installed is None or Version(installed).release == (0, 0, 0):
        return
    if Version(installed) < Version(config.cli.min_version):
        raise CliTooOld(installed, config.cli.min_version)


def load_config(project_root: Path, *, check_compat: bool = True) -> ProjectConfig:
    """Load and validate the project config, enforcing `cli.min_version` by default.

    Only `doctor` passes `check_compat=False` — it reports the mismatch as
    one of its checks instead of failing on it.
    """
    data = tomllib.loads(config_path(project_root).read_text())
    config = ProjectConfig.model_validate(data)
    if check_compat:
        check_cli_compat(config)
    return config


def save_config(project_root: Path, config: ProjectConfig) -> None:
    path = config_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(config.model_dump(exclude_none=True)))  # TOML не хранит None


def init_project(project_root: Path, name: str, *, login: str | None = None, sandbox: bool = False) -> ProjectConfig:
    config = ProjectConfig(name=name, direct=DirectConfig(login=login, sandbox=sandbox))
    save_config(project_root, config)
    return config


# --- Директ: кабинет, клиент API, запуск -------------------------------------------------------

MANAGED_LOGINS_ENV = "YANDEX_DIRECT_MANAGED_LOGINS"
LOGIN_ENV = "YANDEX_DIRECT_LOGIN"
SANDBOX_ENV = "YANDEX_DIRECT_SANDBOX"
OPERATOR_UNITS_ENV = "YANDEX_DIRECT_USE_OPERATOR_UNITS"

T = TypeVar("T")


def managed_logins() -> list[str]:
    """Кабинеты, где владелец токена — представитель: API этот список не отдаёт, он в env."""
    raw = os.getenv(MANAGED_LOGINS_ENV, "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def resolve_login(login: str | None) -> str | None:
    """Неполное имя → полный логин из YANDEX_DIRECT_MANAGED_LOGINS (единственное совпадение подстроки).

    Логин с `@` и любой логин при пустом списке передаются как есть.
    """
    if not login:
        return None
    managed = managed_logins()
    if "@" in login or not managed:
        return login
    matches = [m for m in managed if login.lower() in m.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise InvalidArguments(f"Логин по подстроке {login!r} не найден среди {MANAGED_LOGINS_ENV}: {managed}.")
    raise InvalidArguments(f"Неоднозначный логин {login!r}, совпали: {matches}. Укажите полностью.")


def _project_direct(ctx_obj: dict) -> DirectConfig | None:
    start = Path(ctx_obj.get("project") or Path.cwd())
    root = find_project_root(start)
    return load_config(root).direct if root else None


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").lower() in ("1", "true", "yes")


def connection(ctx_obj: dict) -> dict:
    """Параметры подключения: `--login` → конфиг проекта → YANDEX_DIRECT_LOGIN; так же sandbox."""
    project = _project_direct(ctx_obj)
    login = resolve_login(ctx_obj.get("login")) or (project.login if project else None) or os.getenv(LOGIN_ENV)
    sandbox = ctx_obj.get("sandbox")
    if sandbox is None:
        sandbox = _env_flag(SANDBOX_ENV) or bool(project and project.sandbox)
    return {"client_login": login, "sandbox": bool(sandbox), "use_operator_units": _env_flag(OPERATOR_UNITS_ENV)}


def direct(ctx_obj: dict, *, login: str | None = None) -> DirectClient:
    """DirectClient для команды; `login` — явный Client-Login поверх `connection()`."""
    params = connection(ctx_obj)
    if login is not None:
        params["client_login"] = login
    return DirectClient(token=resolve_token(), **params)


def reports(ctx_obj: dict) -> ReportsClient:
    return ReportsClient(token=resolve_token(), **connection(ctx_obj))


def run(coro: Coroutine[Any, Any, T]) -> T:
    """Выполнить корутину клиента из синхронной команды."""
    return asyncio.run(coro)


def micros(rubles: float | None) -> int | None:
    """Рубли → микроединицы валюты API (×1 000 000); None остаётся None."""
    return None if rubles is None else round(rubles * 1_000_000)


def rubles(value: int | None) -> float | None:
    """Микроединицы валюты API → рубли."""
    return None if value is None else value / 1_000_000


async def gather_accounts(ctx_obj: dict, *, managed_only: bool) -> list[dict]:
    """Кабинеты, доступные токену: клиенты агентства (agencyclients.get) + YANDEX_DIRECT_MANAGED_LOGINS.

    Для каждого managed-логина — clients.get под его Client-Login: валюта, баллы или ошибка доступа
    в поле `_error` (кабинет без доступа — не сбой всей команды).
    """
    seen: dict[str, dict] = {}
    if not managed_only:
        try:
            for c in await direct(ctx_obj, login="").list_clients():
                seen[c.get("Login", "")] = c
        except DirectAPIError as exc:
            if exc.is_auth_error:
                raise
            # Не агентство — список клиентов недоступен; это нормально для представителя.
    for login in managed_logins():
        if login in seen:
            continue
        try:
            items = await direct(ctx_obj, login=login).list_clients()
            seen[login] = items[0] if items else {"Login": login, "_error": "empty"}
        except DirectAPIError as exc:
            seen[login] = {"Login": login, "_error": f"[{exc.error_code}] {exc.error_string}"}
    return list(seen.values())
