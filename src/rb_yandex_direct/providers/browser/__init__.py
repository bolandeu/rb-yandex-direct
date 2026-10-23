"""Веб-интерфейс Директа через браузер — то, чего нет в API: Мастер кампаний и история изменений.

Тонкая обёртка над браузерным слоем пакета direct-cli (MIT, https://github.com/axisrow/direct-cli,
`direct_cli.browser`): Playwright + куки Яндекса из Chrome. Этот слой — тысячи строк
DOM-скрейпинга, выверенного на живом кабинете; своя копия устаревала бы при каждой смене
разметки Яндекса, поэтому берём готовое (optional extra `browser`) и здесь только:

- выбираем сессию: свой профиль Chromium (`yd browser login`) → сохранённые куки
  (`yd browser login --from-chrome`) → свежая расшифровка кук Chrome; устаревшая сохранённая
  сессия один раз пересобирается из Chrome;
- держим состояние в `platformdirs.user_data_dir("yd")/browser`, а не в `~/.direct-cli`;
- переводим ошибки библиотеки в CliError (AUTH_REQUIRED / PROVIDER_ERROR / INVALID_ARGUMENTS);
- уводим её печать в stderr: stdout остаётся чистым для `--json`.

Библиотека импортируется лениво (`lib()`): без extra остальной CLI работает, а браузерные
команды отвечают DEPENDENCY_TOO_OLD с командой установки. `lib()` — точка подмены в тестах.
"""

from __future__ import annotations

import contextlib
import importlib
import shutil
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypeVar

from platformdirs import user_data_dir

from ...core.errors import CliError, InvalidArguments, ProviderError
from ...core.version import cli_name
from ..base import Health, Provider

T = TypeVar("T")

INSTALL_ACTION = (
    'uv tool install --reinstall "rb-yandex-direct[browser] @ '
    'git+https://github.com/bolandeu/yandex-direct.git@vX.Y.Z" && playwright install chromium'
)
_MODULES = ("session", "masters", "change_history", "store", "diagnostics")
# Имя файла-метки, которым библиотека помечает созданный ею профиль (без неё logout не удалит папку).
PROFILE_MARKER = ".direct-cli-profile"

_lib: SimpleNamespace | None = None


class BrowserUnavailable(CliError):
    """Нет extra `browser` (direct-cli + playwright) — команды веб-интерфейса недоступны."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            "DEPENDENCY_TOO_OLD",
            f"Команды веб-интерфейса Директа требуют extra `browser` (direct-cli, playwright): {reason}.",
            action=f"Установите: {INSTALL_ACTION}",
            exit_code=1,
        )


def lib() -> SimpleNamespace:
    """Модули `direct_cli.browser.*`: session, masters, change_history, store, diagnostics."""
    global _lib
    if _lib is None:
        try:
            _lib = SimpleNamespace(**{name: importlib.import_module(f"direct_cli.browser.{name}") for name in _MODULES})
        except ImportError as exc:
            raise BrowserUnavailable(str(exc)) from exc
    return _lib


@dataclass(frozen=True)
class Paths:
    """Где лежит браузерное состояние yd (не в репозитории и не в ~/.direct-cli)."""

    root: Path

    @property
    def profile(self) -> Path:
        return self.root / "profile"

    @property
    def session(self) -> Path:
        return self.root / "session.json"

    @property
    def pointer(self) -> Path:
        return self.root / "profile-path"


def paths() -> Paths:
    return Paths(Path(user_data_dir(cli_name())) / "browser")


def _pin_library_paths(library: SimpleNamespace) -> None:
    """Библиотека по умолчанию пишет в ~/.direct-cli — направляем её в папку yd."""
    p = paths()
    library.session.PROFILE_POINTER_PATH = p.pointer
    library.session.DEFAULT_PERSISTENT_PROFILE_DIR = p.profile


def _cli_error(exc: BaseException) -> CliError:
    """Ошибка браузерного слоя → CliError с понятным следующим шагом."""
    session = lib().session
    login = f"{cli_name()} browser login"
    message = str(exc)
    if isinstance(exc, session.BrowserCaptchaError):
        return ProviderError(
            "direct-web", message, action="Откройте direct.yandex.ru в Chrome, решите капчу и повторите."
        )
    if isinstance(exc, session.BrowserNetworkError):
        return ProviderError("direct-web", message, action="Проверьте сеть/VPN и повторите.")
    if isinstance(exc, session.BrowserAuthError | session.BrowserSessionMissingError | session.ChromeCookieError):
        return CliError(
            "AUTH_REQUIRED",
            f"Нет рабочей сессии Яндекса в браузере: {message}",
            action=f"Выполните '{login}' (или войдите в direct.yandex.ru в Chrome и повторите).",
            exit_code=3,
        )
    if isinstance(exc, ValueError):
        return InvalidArguments(message)
    return ProviderError("direct-web", message, action=f"Повторите с --headful, чтобы увидеть страницу; '{login}'.")


def _library_errors() -> tuple[type[BaseException], ...]:
    session = lib().session
    return (session.BrowserSessionError, session.PlaywrightError, ValueError)


def session_source() -> str:
    """Какую сессию возьмёт следующая команда: profile | saved | chrome (без сети и браузера)."""
    library = lib()
    p = paths()
    if library.session.persistent_profile_is_usable(p.profile):
        return "profile"
    status = library.store.session_status(p.session)
    if status["exists"] and not status["error"] and status["expired"] is not True:
        return "saved"
    return "chrome"


@contextlib.contextmanager
def _page(source: str, *, headful: bool, chrome_dir: Path | None, chrome_profile: str) -> Iterator[Any]:
    session = lib().session
    if source == "profile":
        with session.open_persistent_session(profile_dir=paths().profile, headless=not headful) as page:
            yield page
    elif source == "saved":
        with session.open_saved_session(headless=not headful, session_path=paths().session) as page:
            yield page
    else:
        with session.open_chrome_session(
            profile_dir=chrome_dir, chrome_profile=chrome_profile, headless=not headful
        ) as page:
            yield page


def run[T](
    operation: Callable[[Any], T],
    *,
    headful: bool = False,
    chrome_dir: Path | None = None,
    chrome_profile: str = "Default",
) -> T:
    """Выполнить `operation(page)` в браузерной сессии и вернуть результат.

    Явный `chrome_dir` — всегда свежие куки из этого профиля Chrome. Иначе — `session_source()`;
    если сохранённая сессия или свой профиль оказались просрочены, операция один раз
    повторяется на свежих куках Chrome (до любого изменения: вход проверяется при переходе).
    """
    library = lib()
    _pin_library_paths(library)
    source = "chrome" if chrome_dir else session_source()
    errors = _library_errors()
    attempts = [source] if source == "chrome" else [source, "chrome"]
    with contextlib.redirect_stdout(sys.stderr):  # библиотека печатает предупреждения в stdout
        for index, current in enumerate(attempts):
            try:
                with _page(current, headful=headful, chrome_dir=chrome_dir, chrome_profile=chrome_profile) as page:
                    return operation(page)
            except errors as exc:
                retry = index + 1 < len(attempts) and isinstance(exc, library.session.BrowserAuthError)
                if not retry:
                    raise _cli_error(exc) from exc
    raise AssertionError("unreachable")  # pragma: no cover


def login(*, from_chrome: bool, timeout_s: int, chrome_dir: Path | None, chrome_profile: str, verify: bool) -> dict:
    """Сохранить сессию: свой профиль Chromium (ручной вход) или снимок кук из Chrome."""
    library = lib()
    _pin_library_paths(library)
    p = paths()
    p.root.mkdir(parents=True, exist_ok=True)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            if from_chrome:
                state, source = library.session.capture_storage_state(
                    profile_dir=chrome_dir, chrome_profile=chrome_profile, verify=verify
                )
                library.store.save_session(state, source=source, path=p.session)
                return {"source": "saved", "path": str(p.session), "verified": verify}
            library.session.login_persistent_session(profile_dir=p.profile, timeout_ms=timeout_s * 1000)
            return {"source": "profile", "path": str(p.profile), "verified": True}
    except _library_errors() as exc:
        raise _cli_error(exc) from exc


def status() -> dict:
    """Состояние сессий без сети: что есть на диске и что возьмёт следующая команда."""
    library = lib()
    p = paths()
    saved = library.store.session_status(p.session)
    return {
        "active": session_source(),
        "profile": {"path": str(p.profile), "usable": library.session.persistent_profile_is_usable(p.profile)},
        "saved": {"path": str(p.session), **saved},
    }


def diagnostics(*, chrome_dir: Path | None, chrome_profile: str) -> list[dict]:
    """Проверки окружения библиотеки (playwright, cryptography, Chrome, сохранённая сессия)."""
    checks = lib().diagnostics.run_diagnostics(
        profile_dir=chrome_dir, chrome_profile=chrome_profile, session_path=paths().session
    )
    return [{"name": c.name, "ok": c.ok, "detail": _ours(c.detail), "hint": _ours(c.hint)} for c in checks]


def _ours(text: str | None) -> str | None:
    """Подсказки библиотеки называют её команды — переводим на команды yd."""
    if text is None:
        return None
    login = f"{cli_name()} browser login"
    return text.replace("direct playwright login", login).replace("direct masters login", login)


def logout() -> dict:
    """Удалить свой профиль Chromium и сохранённые куки (Chrome пользователя не трогается)."""
    p = paths()
    removed: list[str] = []
    if (p.profile / PROFILE_MARKER).is_file():
        shutil.rmtree(p.profile)
        removed.append(str(p.profile))
    for file in (p.session, p.pointer):
        if file.exists():
            file.unlink()
            removed.append(str(file))
    return {"removed": removed}


class DirectWebProvider(Provider):
    """Веб-интерфейс Директа (браузер): для `auth status`/`doctor` — есть ли сессия, без сети.

    Необязательный: CLI работает без него, это только Мастер кампаний и история изменений.
    """

    abstract = False
    name = "direct-web"
    credential_fields = ()
    required = False

    def health_check(self) -> Health:
        try:
            source = session_source()
        except BrowserUnavailable as exc:
            return Health("unreachable", message=exc.message)
        if source == "chrome":
            raise CliError(
                "AUTH_REQUIRED",
                "Сохранённой браузерной сессии нет — каждая команда будет расшифровывать куки Chrome.",
                action=f"Выполните '{cli_name()} browser login'.",
                exit_code=3,
            )
        return Health(message=f"сессия: {source}")
