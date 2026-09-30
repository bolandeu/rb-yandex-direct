"""`auth login|refresh|logout|status` on rb-yandex-oauth: keychain slot, §8 report, error mapping."""

from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request

import httpx
import pytest
import respx
from click.testing import CliRunner

from rb_yandex_direct.cli import cli
from rb_yandex_direct.core import auth as direct_auth
from rb_yandex_direct.core.client import PROD_BASE
from rb_yandex_direct.core.errors import DirectAPIError
from rb_yandex_direct.core.oauth import DEVICE_CODE_URL, TOKEN_URL

SLOT = ("yandex-oauth:direct", "direct")
REPORT_KEYS = {"ok", "tool", "version", "checked_at", "credentials"}
ENTRY_KEYS = {"provider", "required", "fields", "source", "source_ref", "status", "expires_at", "quota", "message"}
TOKENS = {"access_token": "acc", "refresh_token": "ref", "expires_in": 31_536_000}


def _run(*args: str, input: str | None = None):
    return CliRunner().invoke(cli, list(args), obj={}, prog_name="yd", input=input)


def _store(fake_keyring: dict, **fields: str) -> None:
    fake_keyring[SLOT] = json.dumps({"token": "acc", **fields})


def _stored(fake_keyring: dict) -> dict:
    return json.loads(fake_keyring[SLOT])


def _clients_get(status: int = 200, body: dict | None = None):
    return respx.post(url__startswith=PROD_BASE).mock(
        return_value=httpx.Response(
            status, json=body or {"result": {"Clients": []}}, headers={"Units": "10/20000/64000"}
        )
    )


# --- status (§8) ------------------------------------------------------------------


def test_status_missing_is_exit_3_with_full_report() -> None:
    result = _run("auth", "status", "--json")
    assert result.exit_code == 3
    report = json.loads(result.output)
    assert set(report) == REPORT_KEYS | {"error"}
    assert report["ok"] is False
    assert report["error"]["code"] == "CREDENTIALS_UNHEALTHY"
    assert report["tool"] == "yd"
    (entry,) = report["credentials"]
    assert set(entry) == ENTRY_KEYS
    assert entry["provider"] == "direct"
    assert entry["status"] == "missing"
    assert "yandex-oauth:direct" in entry["source_ref"]


def test_status_keychain_unchecked_without_network(fake_keyring: dict) -> None:
    _store(fake_keyring)
    result = _run("auth", "status", "--json")
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["ok"] is True
    assert report["credentials"][0]["status"] == "unchecked"
    assert report["credentials"][0]["source"] == "keychain"
    assert "acc" not in result.output


@respx.mock
def test_status_check_ok_reports_units_quota(fake_keyring: dict) -> None:
    _store(fake_keyring)
    route = _clients_get()
    result = _run("auth", "status", "--check", "--json")
    assert result.exit_code == 0, result.output
    entry = json.loads(result.output)["credentials"][0]
    assert entry["status"] == "ok"
    assert entry["quota"] == {"remaining": 20000, "limit": 64000, "unit": "points"}
    assert route.calls.last.request.headers["Authorization"] == "Bearer acc"


@respx.mock
def test_status_check_rejected_token_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "bad")
    _clients_get(body={"error": {"error_code": 53, "error_string": "Ошибка авторизации", "error_detail": ""}})
    result = _run("auth", "status", "--check")
    assert result.exit_code == 3
    assert "invalid" in result.output
    assert "CREDENTIALS_UNHEALTHY" not in result.output  # human mode: message, not the code


# --- login / refresh / logout -----------------------------------------------------


def test_login_with_manual_token_stores_it(fake_keyring: dict) -> None:
    result = _run("auth", "login", "--token", "y0_manual")
    assert result.exit_code == 0, result.output
    assert _stored(fake_keyring)["token"] == "y0_manual"
    assert "автообновление: нет" in result.output


def test_login_without_app_credentials_is_usage_error() -> None:
    result = _run("auth", "login")
    assert result.exit_code == 2
    assert "YANDEX_OAUTH_DIRECT_CLIENT_ID" in result.output


@respx.mock
def test_login_oob_reads_legacy_app_env(fake_keyring: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_CLIENT_ID", "cid")
    monkeypatch.setenv("YANDEX_DIRECT_CLIENT_SECRET", "sec")
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKENS))
    result = _run("auth", "login", "--oob", input="12345\n")
    assert result.exit_code == 0, result.output
    assert b"code=12345" in route.calls.last.request.content
    bag = _stored(fake_keyring)
    assert (bag["token"], bag["refresh_token"], bag["client_id"]) == ("acc", "ref", "cid")
    assert "автообновление: да" in result.output


@respx.mock
def test_login_device_flow(fake_keyring: dict) -> None:
    respx.post(DEVICE_CODE_URL).mock(
        return_value=httpx.Response(
            200, json={"device_code": "dc", "user_code": "ABCD", "verification_url": "https://ya.ru/device"}
        )
    )
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKENS))
    result = _run("auth", "login", "--device", "--client-id", "cid", "--client-secret", "sec")
    assert result.exit_code == 0, result.output
    assert "ABCD" in result.output
    assert _stored(fake_keyring)["refresh_token"] == "ref"


def test_login_browser_flow_catches_callback(fake_keyring: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    def browser(url: str) -> None:
        redirect = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["redirect_uri"][0]
        threading.Thread(target=urllib.request.urlopen, args=(f"{redirect}?code=777",), daemon=True).start()

    monkeypatch.setattr("rb_yandex_direct.core.oauth.webbrowser.open", browser)
    with respx.mock(assert_all_called=False) as router:
        router.route(host="localhost").pass_through()
        route = router.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKENS))
        result = _run("auth", "login", "--client-id", "cid", "--client-secret", "sec")
    assert result.exit_code == 0, result.output
    assert b"code=777" in route.calls.last.request.content
    assert _stored(fake_keyring)["token"] == "acc"


@respx.mock
def test_refresh_rewrites_keychain(fake_keyring: dict) -> None:
    _store(fake_keyring, refresh_token="old", client_id="cid", client_secret="sec")
    respx.post("https://oauth.yandex.ru/token").mock(
        return_value=httpx.Response(200, json={**TOKENS, "access_token": "new"})
    )
    result = _run("auth", "refresh")
    assert result.exit_code == 0, result.output
    assert _stored(fake_keyring)["token"] == "new"


def test_refresh_without_refresh_token_is_an_error(fake_keyring: dict) -> None:
    _store(fake_keyring)
    result = _run("auth", "refresh")
    assert result.exit_code == 1
    assert "refresh_token" in result.output


def test_logout_deletes_the_slot(fake_keyring: dict) -> None:
    _store(fake_keyring)
    assert _run("auth", "logout").exit_code == 0
    assert SLOT not in fake_keyring


# --- token for API calls and error mapping --------------------------------------------


def test_api_command_without_token_asks_to_log_in() -> None:
    result = _run("campaigns", "list")
    assert result.exit_code == 3
    assert "yd auth login" in result.output


@respx.mock
@pytest.mark.parametrize(("code", "exit_code"), [(58, 3), (1002, 3), (8000, 5)])
def test_whoami_maps_api_errors(code: int, exit_code: int, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    _clients_get(body={"error": {"error_code": code, "error_string": "e", "error_detail": "d"}})
    assert _run("whoami").exit_code == exit_code


def test_app_credentials_precedence(fake_keyring: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    _store(fake_keyring, client_id="stored", client_secret="stored-sec")
    assert direct_auth.app_credentials() == ("stored", "stored-sec")
    monkeypatch.setenv("YANDEX_DIRECT_CLIENT_ID", "legacy")
    assert direct_auth.app_credentials()[0] == "legacy"
    monkeypatch.setenv("YANDEX_OAUTH_DIRECT_CLIENT_ID", "new")
    assert direct_auth.app_credentials()[0] == "new"
    assert direct_auth.app_credentials("arg")[0] == "arg"


def test_units_quota_ignores_malformed_header() -> None:
    assert direct_auth._units_quota(None) is None
    assert direct_auth._units_quota("1/2") is None


def test_provider_error_is_exit_5() -> None:
    error = direct_auth.as_cli_error(DirectAPIError(8000, "Некорректный запрос"))
    assert (error.code, error.exit_code) == ("PROVIDER_ERROR", 5)
