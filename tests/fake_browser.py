"""Подмена браузерного слоя direct-cli для тестов: без Playwright, Chrome и сети.

`FakeBrowser()` повторяет форму `providers.browser.lib()` — модули session, masters,
change_history, store, diagnostics — и записывает вызовы в `calls`.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any


class BrowserSessionError(RuntimeError):
    pass


class BrowserAuthError(BrowserSessionError):
    pass


class BrowserCaptchaError(BrowserSessionError):
    pass


class BrowserNetworkError(BrowserSessionError):
    pass


class BrowserSessionMissingError(BrowserSessionError):
    pass


class ChromeCookieError(BrowserSessionError):
    pass


class PlaywrightError(Exception):
    pass


@dataclass
class Check:
    name: str
    ok: bool | None
    detail: str
    hint: str | None = None


PAGE = object()
MASTER = {"CampaignId": 72349978, "Name": "Мастер", "Status": "ACTIVE", "Type": "TEXT", "StartDate": "2026-09-01"}


class FakeBrowser(SimpleNamespace):
    def __init__(self) -> None:
        calls: list[tuple[str, tuple, dict]] = []
        # Сколько раз подряд открытие сессии заканчивается BrowserAuthError (для самовосстановления).
        state: dict[str, Any] = {"auth_failures": 0, "profile_usable": False, "saved": False, "opened": []}

        def record(name: str, result: Any) -> Any:
            def call(*args: Any, **kwargs: Any) -> Any:
                calls.append((name, args[1:] if args and args[0] is PAGE else args, kwargs))
                return result(*args, **kwargs) if callable(result) else result

            return call

        @contextlib.contextmanager
        def opener(kind: str, **kwargs: Any):
            state["opened"].append(kind)
            if state["auth_failures"]:
                state["auth_failures"] -= 1
                raise BrowserAuthError("login page")
            yield PAGE

        session = SimpleNamespace(
            BrowserSessionError=BrowserSessionError,
            BrowserAuthError=BrowserAuthError,
            BrowserCaptchaError=BrowserCaptchaError,
            BrowserNetworkError=BrowserNetworkError,
            BrowserSessionMissingError=BrowserSessionMissingError,
            ChromeCookieError=ChromeCookieError,
            PlaywrightError=PlaywrightError,
            PROFILE_POINTER_PATH=None,
            DEFAULT_PERSISTENT_PROFILE_DIR=None,
            persistent_profile_is_usable=lambda profile_dir=None: state["profile_usable"],
            open_persistent_session=lambda **kw: opener("profile", **kw),
            open_saved_session=lambda **kw: opener("saved", **kw),
            open_chrome_session=lambda **kw: opener("chrome", **kw),
            capture_storage_state=record("capture_storage_state", ({"cookies": []}, {"profile_dir": "x"})),
            login_persistent_session=record("login_persistent_session", self._make_profile),
        )
        store = SimpleNamespace(
            session_status=lambda path=None: {
                "exists": state["saved"],
                "error": None,
                "expired": False if state["saved"] else None,
                "path": str(path),
            },
            save_session=record("save_session", lambda state_, *, source=None, path=None: Path(path)),
        )
        masters = SimpleNamespace(
            fetch_masters_list=record("fetch_masters_list", [MASTER]),
            fetch_master=record("fetch_master", dict(MASTER)),
            fetch_master_moderation_statuses=record("fetch_master_moderation_statuses", {"Moderation": []}),
            fetch_master_tracking_params=record("fetch_master_tracking_params", {"TrackingParams": "utm=1"}),
            fetch_master_audience=record("fetch_master_audience", {"Gender": "any", "AudienceTags": []}),
            fetch_master_metrika_counters=record("fetch_master_metrika_counters", {"MetrikaCounters": []}),
            fetch_master_target_actions=record("fetch_master_target_actions", {"TargetActions": []}),
            fetch_master_images=record("fetch_master_images", {"Images": []}),
            create_master=record("create_master", {"CampaignId": 1}),
            update_master=record("update_master", {"CampaignId": 72349978, "Saved": True}),
        )
        for name in (
            "suspend_master",
            "resume_master",
            "archive_master",
            "delete_master",
            "launch_master",
            "copy_master",
            "add_master_images",
            "delete_master_images",
            "set_master_images",
        ):
            setattr(masters, name, record(name, {"CampaignId": 72349978}))
        change_history = SimpleNamespace(
            fetch_change_history=record("fetch_change_history", [{"Datetime": "2026-09-01T10:00:00", "Login": "me"}])
        )
        diagnostics = SimpleNamespace(
            run_diagnostics=lambda **kw: [
                Check("playwright_installed", True, "ok"),
                Check("saved_session", False, "none", "Run: direct playwright login"),
            ]
        )
        super().__init__(
            session=session,
            store=store,
            masters=masters,
            change_history=change_history,
            diagnostics=diagnostics,
            calls=calls,
            state=state,
        )

    def _make_profile(self, *, profile_dir: Path, timeout_ms: int) -> None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / ".direct-cli-profile").touch()
        self.state["profile_usable"] = True

    def last(self, name: str) -> tuple[tuple, dict]:
        for call_name, args, kwargs in reversed(self.calls):
            if call_name == name:
                return args, kwargs
        raise AssertionError(f"{name} не вызывался; были: {[c[0] for c in self.calls]}")
