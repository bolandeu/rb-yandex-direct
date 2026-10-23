"""Shared fixtures: isolate the tests from the real keychain and environment, rerun a test file under the CI environment."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable

import pytest

_ENV_PREFIXES = ("YANDEX_OAUTH_", "YANDEX_DIRECT_", "YANDEX_CLIENT_")


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    """In-memory замена keychain ОС + окружение без токенов Яндекса для каждого теста."""
    store: dict[tuple[str, str], str] = {}

    def fake_set_password(service: str, username: str, password: str) -> None:
        store[(service, username)] = password

    def fake_get_password(service: str, username: str) -> str | None:
        return store.get((service, username))

    def fake_delete_password(service: str, username: str) -> None:
        store.pop((service, username), None)

    monkeypatch.setattr("yandex_oauth.credentials.keyring.set_password", fake_set_password)
    monkeypatch.setattr("yandex_oauth.credentials.keyring.get_password", fake_get_password)
    monkeypatch.setattr("yandex_oauth.credentials.keyring.delete_password", fake_delete_password)
    for var in list(os.environ):
        if var.startswith(_ENV_PREFIXES):
            monkeypatch.delenv(var)
    return store


@pytest.fixture(autouse=True)
def fake_browser(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory):
    """Браузерный слой (direct-cli + Playwright) подменён, данные yd — во временной папке.

    Ни один тест не запускает браузер и не читает куки Chrome, даже если extra `browser` установлен.
    """
    from rb_yandex_direct.providers import browser

    from .fake_browser import FakeBrowser

    fake = FakeBrowser()
    root = tmp_path_factory.mktemp("yd-data") / "browser"
    monkeypatch.setattr(browser, "_lib", fake)
    monkeypatch.setattr(browser, "paths", lambda: browser.Paths(root))
    return fake


# Typer reads these once, at import, and then forces terminal output — what a CI runner sets.
CI_ENV = {"GITHUB_ACTIONS": "true", "FORCE_COLOR": "1", "PY_COLORS": "1"}


@pytest.fixture
def same_in_ci(request: pytest.FixtureRequest) -> Callable[[str], None]:
    """Rerun this file's tests matching `-k` under CI_ENV in a fresh interpreter: the only way to set a value read at import."""
    if request.config.getoption("--snapshot-update"):
        pytest.skip("the snapshots are being written; there is nothing to compare yet")

    def run(selection: str) -> None:
        options = ["-k", selection, "-p", "no:cacheprovider", "--no-cov", "-q"]
        command = [sys.executable, "-m", "pytest", str(request.path), *options]
        env = {**os.environ, **CI_ENV}
        result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)  # noqa: S603
        assert result.returncode == 0, result.stdout[-3000:]

    return run
