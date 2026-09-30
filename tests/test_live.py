"""API v4 Live: клиент (тело, ошибки, ретраи) и финансовый доступ (токен, номер операции)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from rb_yandex_direct.core import live as core_live
from rb_yandex_direct.core.errors import CliError
from rb_yandex_direct.providers.live import LIVE_PROD, LIVE_SANDBOX, Finance, LiveAPIError, LiveClient


def _client(handler, **kwargs) -> LiveClient:
    client = LiveClient(token="tok", transport=httpx.MockTransport(handler), **kwargs)
    client.backoff = 0
    return client


@pytest.mark.asyncio
async def test_call_sends_body_and_returns_data() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [1, 2]})

    client = _client(handler, client_login="shop")
    assert await client.call("GetStatGoals", {"CampaignIDS": [1]}) == [1, 2]
    body = json.loads(seen[0].content)
    assert body == {"method": "GetStatGoals", "param": {"CampaignIDS": [1]}, "locale": "ru", "token": "tok"}
    assert str(seen[0].url) == LIVE_PROD
    assert seen[0].headers["Client-Login"] == "shop"


def test_sandbox_url_and_finance_fields() -> None:
    client = LiveClient(token="t", sandbox=True)
    assert client.url == LIVE_SANDBOX
    body = client.body("CreateInvoice", {"Payments": []}, Finance("ft", 7))
    assert (body["finance_token"], body["operation_num"]) == ("ft", 7)
    assert "token" not in body  # тело для --dry-run без токена


@pytest.mark.asyncio
async def test_error_in_body_maps_codes() -> None:
    def rejected(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error_code": 53, "error_str": "Ошибка авторизации", "error_detail": ""})

    with pytest.raises(LiveAPIError) as auth:
        await _client(rejected).call("PingAPI")
    assert (auth.value.code, auth.value.exit_code) == ("AUTH_REQUIRED", 3)
    assert auth.value.to_dict()["provider"] == "direct-live"

    def bad(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error_code": 71, "error_str": "Неверный параметр", "error_detail": "x"})

    with pytest.raises(LiveAPIError) as other:
        await _client(bad).call("CheckPayment", {})
    assert (other.value.code, other.value.exit_code, other.value.error_code) == ("PROVIDER_ERROR", 5, 71)


@pytest.mark.asyncio
async def test_finance_error_actions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        code = 350 if json.loads(request.content)["method"] == "A" else 351
        return httpx.Response(200, json={"error_code": code, "error_str": "e"})

    with pytest.raises(LiveAPIError) as token:
        await _client(handler).call("A")
    assert token.value.exit_code == 3
    assert "finance setup" in (token.value.action or "")
    with pytest.raises(LiveAPIError) as num:
        await _client(handler).call("B")
    assert num.value.exit_code == 5
    assert "счётчик" in (num.value.action or "")


@pytest.mark.asyncio
async def test_retries_temporary_errors_but_not_finance_network() -> None:
    calls = {"n": 0}

    def flaky(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"error_code": 56, "error_str": "limit"})
        return httpx.Response(200, json={"data": 1})

    assert await _client(flaky).call("PingAPI") == 1
    assert calls["n"] == 2

    def down(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("boom")

    calls["n"] = 0
    with pytest.raises(LiveAPIError):
        await _client(down).call("CreateInvoice", {}, finance=Finance("ft", 1))
    assert calls["n"] == 1  # финансовый вызов при сбое сети не повторяется
    calls["n"] = 0
    with pytest.raises(LiveAPIError):
        await _client(down).call("PingAPI")
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_http_error_and_bad_json() -> None:
    with pytest.raises(LiveAPIError) as http:
        await _client(lambda _: httpx.Response(400, text="nope")).call("PingAPI")
    assert http.value.error_code == 400
    with pytest.raises(LiveAPIError) as bad:
        await _client(lambda _: httpx.Response(200, text="<html>")).call("PingAPI")
    assert bad.value.error_string == "Invalid JSON"
    assert await _client(lambda _: httpx.Response(200, json=[1])).call("PingAPI") == [1]


def test_finance_token_matches_docs_formula() -> None:
    expected = hashlib.sha256(b"AEgchkX2M3FBL8lU119CreateInvoiceagrom").hexdigest()
    assert core_live.finance_token("AEgchkX2M3FBL8lU", 119, "CreateInvoice", "agrom") == expected
    # Логин нормализуется: строчные, точки → дефисы; операция AccountManagement — перед логином.
    expected_am = hashlib.sha256(b"m5AccountManagementDepositag-rom").hexdigest()
    assert core_live.finance_token("m", 5, "AccountManagement", " Ag.Rom ", "Deposit") == expected_am
    with pytest.raises(CliError):
        core_live.normalize_login("  ")


def test_operation_num_grows_and_persists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_live, "state_path", lambda: tmp_path / "d" / "finance.json")
    monkeypatch.setattr(core_live.time, "time", lambda: 1.0)  # «часы» отстали: растёт от прошлого номера
    assert core_live.last_operation_num() == 0
    assert core_live.next_operation_num() == 1000
    core_live.commit_operation_num(5000)
    assert core_live.next_operation_num() == 5001
    monkeypatch.setenv("YANDEX_OAUTH_DIRECT_FINANCE_MASTER_TOKEN", "m")
    monkeypatch.setenv("YANDEX_OAUTH_DIRECT_FINANCE_LOGIN", "agrom")
    fin = core_live.finance("CreateInvoice")
    assert fin.operation_num == 5001
    assert core_live.last_operation_num() == 5001  # номер записан до запроса
    assert fin.finance_token == core_live.finance_token("m", 5001, "CreateInvoice", "agrom")


def test_finance_without_master_token_is_auth_error() -> None:
    with pytest.raises(core_live.FinanceNotConfigured) as exc:
        core_live.finance_credential()
    assert exc.value.exit_code == 3
    assert "YANDEX_OAUTH_DIRECT_FINANCE_MASTER_TOKEN" in (exc.value.action or "")


def test_broken_state_file_counts_as_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "finance.json"
    path.write_text("{oops", encoding="utf-8")
    monkeypatch.setattr(core_live, "state_path", lambda: path)
    assert core_live.last_operation_num() == 0


def test_store_and_delete_finance_credential(fake_keyring: dict) -> None:
    core_live.store_finance_credential(" m ", "agrom")
    assert core_live.finance_credential() == {"master_token": "m", "login": "agrom"}
    assert ("yandex-oauth:direct_finance", "direct_finance") in fake_keyring
    core_live.delete_finance_credential()
    assert not fake_keyring
