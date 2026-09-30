"""ДЕНЬГИ: `yd finance` и `yd shared-account` — мастер-токен, финансовый токен, dry-run, частичный отказ."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from rb_yandex_direct.cli import app
from rb_yandex_direct.core import live as core_live
from rb_yandex_direct.providers.live import LIVE_PROD


@pytest.fixture
def state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "finance.json"
    monkeypatch.setattr(core_live, "state_path", lambda: path)
    monkeypatch.setattr(core_live.time, "time", lambda: 0.0)
    return path


@pytest.fixture
def master(monkeypatch: pytest.MonkeyPatch, state: Path) -> None:
    monkeypatch.setenv("YANDEX_OAUTH_DIRECT_FINANCE_MASTER_TOKEN", "m")
    monkeypatch.setenv("YANDEX_OAUTH_DIRECT_FINANCE_LOGIN", "Ag.Rom")


def run(*args: str, input: str | None = None) -> tuple[int, dict]:
    result = CliRunner().invoke(app, [*args, "--json"], prog_name="yd", input=input)
    # CliRunner повторяет введённое в stdout (как эхо терминала) — JSON в последней строке.
    return result.exit_code, json.loads(result.stdout.strip().splitlines()[-1])


def mock(data: object) -> respx.Route:
    return respx.post(LIVE_PROD).mock(return_value=httpx.Response(200, json={"data": data}))


@respx.mock
def test_invoice_sends_finance_token_and_consumes_number(master, state: Path) -> None:
    route = mock("https://balance/invoice")
    code, payload = run("finance", "invoice", "--pay", "12345=5000.5", "--confirm", "--non-interactive")
    assert code == 0, payload
    body = json.loads(route.calls.last.request.content)
    assert body["operation_num"] == 1 == payload["operation_num"]
    assert body["finance_token"] == core_live.finance_token("m", 1, "CreateInvoice", "ag-rom")
    assert body["param"] == {"Payments": [{"CampaignID": 12345, "Sum": 5000.5, "Currency": "RUB"}]}
    assert payload["data"] == "https://balance/invoice"
    assert json.loads(state.read_text())["last_operation_num"] == 1


@respx.mock
def test_dry_run_masks_token_and_keeps_counter(master, state: Path) -> None:
    route = mock(1)
    code, payload = run("finance", "transfer", "--from", "1=100", "--to", "2=60", "--to", "3=40", "--dry-run")
    assert code == 0
    assert payload["body"]["finance_token"] == "***"
    assert payload["body"]["operation_num"] == 1
    assert not route.called
    assert not state.exists()


def test_money_needs_confirm_non_interactive(master) -> None:
    code, payload = run("finance", "pay", "--pay", "1=10", "--method", "Overdraft", "--non-interactive")
    assert code == 2
    assert "--confirm" in payload["error"]["message"]


def test_money_validation(master) -> None:
    assert run("finance", "transfer", "--from", "1=100", "--to", "2=50", "--dry-run")[0] == 2
    assert run("finance", "pay", "--pay", "1=10", "--method", "Bank", "--dry-run")[0] == 2
    assert run("finance", "invoice", "--pay", "1=0.001", "--dry-run")[0] == 2
    assert run("finance", "invoice", "--pay", "abc", "--dry-run")[0] == 2
    assert run("shared-account", "transfer", "--from", "1", "--to", "2", "--amount", "-5", "--dry-run")[0] == 2
    assert run("shared-account", "update", "555", "--dry-run")[0] == 2


@respx.mock
def test_pay_bank_with_contract(master) -> None:
    route = mock(1)
    code, _ = run("finance", "pay", "--pay", "1=10", "--method", "Bank", "--contract", "C-1", "--confirm")
    assert code == 0
    param = json.loads(route.calls.last.request.content)["param"]
    assert (param["PayMethod"], param["ContractID"]) == ("Bank", "C-1")


def test_finance_without_master_token_is_exit_3(state) -> None:
    code, payload = run("finance", "invoice", "--pay", "1=10", "--confirm")
    assert code == 3
    assert "finance setup" in payload["error"]["action"]


@respx.mock
def test_credit_limits_and_units(master) -> None:
    route = mock({"Currency": "RUB", "Limits": []})
    assert run("finance", "credit-limits")[1]["limits"]["Currency"] == "RUB"
    body = json.loads(route.calls.last.request.content)
    assert "param" not in body and body["operation_num"] == 1
    mock([{"Login": "shop", "UnitsRest": 100}])
    _, payload = run("finance", "units", "--client", "shop")
    assert payload["units"][0]["UnitsRest"] == 100
    mock({"Status": "Done"})
    assert run("finance", "check-payment", "X" * 32)[1]["payment"] == {"Status": "Done"}


def test_setup_status_forget(fake_keyring: dict, state) -> None:
    assert run("finance", "status")[1]["configured"] is False
    code, payload = run(
        "finance", "setup", "--finance-login", "agrom", "--master-token-stdin", "--non-interactive", input="mt\n"
    )
    assert code == 0 and payload["login"] == "agrom"
    status = run("finance", "status")[1]
    assert (status["configured"], status["source"], status["login"]) == (True, "keychain", "agrom")
    assert "mt" not in json.dumps(status)
    assert run("finance", "forget")[0] == 0
    assert run("finance", "status")[1]["configured"] is False


def test_setup_interactive_and_errors(fake_keyring: dict, state) -> None:
    code, _ = run("finance", "setup", input="mt\nagrom\n")
    assert code == 0
    assert core_live.finance_credential() == {"master_token": "mt", "login": "agrom"}
    assert run("finance", "setup", "--non-interactive")[0] == 2
    assert run("finance", "setup", "--master-token-stdin", "--non-interactive", input="mt\n")[0] == 2
    assert run("finance", "setup", "--finance-login", "x", "--master-token-stdin", input="\n")[0] == 2


@respx.mock
def test_shared_account_list_and_update(master) -> None:
    route = mock({"Accounts": [{"AccountID": 555, "Amount": 10.5, "AccountDayBudget": {"Amount": 100}}]})
    code, payload = run("shared-account", "list", "--client", "shop", "--account", "555")
    assert payload["accounts"][0]["AccountID"] == 555
    assert json.loads(route.calls.last.request.content)["param"] == {
        "Action": "Get",
        "SelectionCriteria": {"Logins": ["shop"], "AccountIDS": [555]},
    }
    route = mock({"ActionsResult": [{"AccountID": 555}]})
    code, payload = run(
        "shared-account", "update", "555", "--day-budget", "300", "--email", "a@b.ru",
        "--money-warning", "20", "--no-notify-paused", "--confirm",
    )  # fmt: skip
    assert code == 0 and payload["succeeded"] == 1
    body = json.loads(route.calls.last.request.content)
    assert "finance_token" not in body
    assert body["param"]["Accounts"][0] == {
        "AccountID": 555,
        "AccountDayBudget": {"Amount": 300.0, "SpendMode": "Default"},
        "EmailNotification": {"Email": "a@b.ru", "MoneyWarningValue": 20, "PausedByDayBudget": "No"},
    }


@respx.mock
def test_shared_deposit_partial_failure_is_exit_5(master) -> None:
    route = mock(
        {
            "ActionsResult": [
                {"AccountID": 555},
                {"AccountID": 556, "Errors": [{"FaultCode": 245, "FaultString": "Валюта"}]},
            ]
        }
    )
    code, payload = run("shared-account", "deposit", "--pay", "555=100", "--pay", "556=100", "--confirm")
    assert code == 5
    assert (payload["succeeded"], payload["failed"]) == (1, 1)
    assert payload["errors"][0]["FaultCode"] == 245
    body = json.loads(route.calls.last.request.content)
    assert body["param"]["Payments"][0]["Origin"] == "Overdraft"
    assert body["finance_token"] == core_live.finance_token("m", 1, "AccountManagement", "ag-rom", "Deposit")
    human = CliRunner().invoke(
        app, ["shared-account", "deposit", "--pay", "555=100", "--contract", "C", "--confirm"], prog_name="yd"
    )
    assert "Валюта" in human.stdout
    assert json.loads(route.calls.last.request.content)["param"]["Payments"][0]["Contract"] == "C"


@respx.mock
def test_shared_invoice_transfer_enable(master) -> None:
    route = mock({"ActionsResult": [{"URL": "https://x"}]})
    assert run("shared-account", "invoice", "--pay", "555=100", "--confirm")[0] == 0
    body = json.loads(route.calls.last.request.content)
    assert body["finance_token"] == core_live.finance_token("m", 1, "AccountManagement", "ag-rom", "Invoice")
    assert run("shared-account", "transfer", "--from", "1", "--to", "2", "--amount", "10", "--confirm")[0] == 0
    body = json.loads(route.calls.last.request.content)
    assert body["param"]["Transfers"] == [{"FromAccountID": 1, "ToAccountID": 2, "Amount": 10.0, "Currency": "RUB"}]
    assert body["operation_num"] == 2
    mock({"Login": "shop", "AccountID": 9})
    code, payload = run("shared-account", "enable", "shop", "--confirm")
    assert code == 0 and payload["data"]["AccountID"] == 9
