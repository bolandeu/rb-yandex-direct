"""Общие фикстуры: изолируют тесты от настоящего keychain и переменных окружения."""

from __future__ import annotations

import os

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
