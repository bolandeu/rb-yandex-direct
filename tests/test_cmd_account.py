"""`yd accounts`, `yd clients update`, `yd agency`: тела запросов и выбор кабинета."""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response
from typer.testing import CliRunner

from rb_yandex_direct.cli import app
from rb_yandex_direct.providers.direct import PROD_BASE


@pytest.fixture(autouse=True)
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")


def _run(*args: str):
    return CliRunner().invoke(app, list(args), prog_name="yd")


def _route(service: str, result: dict):
    return respx.post(f"{PROD_BASE}/{service}").mock(return_value=Response(200, json={"result": result}))


def _body(route) -> dict:
    return json.loads(route.calls.last.request.content)


@respx.mock
def test_accounts_merges_api_and_managed_logins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_MANAGED_LOGINS", "friend@yandex.ru,nope@yandex.ru")
    respx.post(f"{PROD_BASE}/agencyclients").mock(
        return_value=Response(200, json={"error": {"error_code": 8100, "error_string": "Not agency"}})
    )

    def clients(request) -> Response:
        login = request.headers.get("client-login", "")
        if login == "nope@yandex.ru":
            return Response(200, json={"error": {"error_code": 8800, "error_string": "Нет доступа"}})
        return Response(200, json={"result": {"Clients": [{"Login": login or "me", "Currency": "RUB"}]}})

    respx.post(f"{PROD_BASE}/clients").mock(side_effect=clients)
    result = _run("accounts", "--json")
    assert result.exit_code == 0, result.output
    accounts = {a["Login"]: a for a in json.loads(result.output)["accounts"]}
    assert set(accounts) == {"me", "friend@yandex.ru", "nope@yandex.ru"}
    assert "8800" in accounts["nope@yandex.ru"]["_error"]


@respx.mock
def test_clients_update_typed_body() -> None:
    route = _route("clients", {"UpdateResults": [{"ClientId": 1}]})
    result = _run(
        "clients", "update", "--email", "a@b.ru", "--lang", "en", "--subscription", "TRACK_POSITION_CHANGES=NO",
        "--setting", "DISPLAY_STORE_RATING=YES", "--tin-type", "legal", "--tin", "7700000000", "--confirm",
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    item = _body(route)["params"]["Clients"][0]
    assert item["Notification"] == {
        "Email": "a@b.ru",
        "Lang": "EN",
        "EmailSubscriptions": [{"Option": "TRACK_POSITION_CHANGES", "Value": "NO"}],
    }
    assert item["Settings"] == [{"Option": "DISPLAY_STORE_RATING", "Value": "YES"}]
    assert item["TinInfo"] == {"TinType": "LEGAL", "Tin": "7700000000"}


def test_clients_update_rejects_empty_and_unknown_setting() -> None:
    assert _run("clients", "update", "--dry-run").exit_code == 2
    assert _run("clients", "update", "--setting", "SHARED_ACCOUNT_ENABLED=YES", "--dry-run").exit_code == 2


@respx.mock
def test_clients_update_json_wraps_item(tmp_path) -> None:
    route = _route("clients", {"UpdateResults": [{}]})
    path = tmp_path / "client.json"
    path.write_text(json.dumps({"ClientInfo": "Ромашка"}), encoding="utf-8")
    assert _run("clients", "update-json", "--from-json", str(path), "--confirm").exit_code == 0
    assert _body(route)["params"] == {"Clients": [{"ClientInfo": "Ромашка"}]}


@respx.mock
def test_agency_list_goes_without_client_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_LOGIN", "client@yandex.ru")
    route = _route("agencyclients", {"Clients": [{"ClientId": 1, "Login": "c1"}]})
    result = _run("agency", "list", "--active", "--client-login", "c1", "--json")
    assert result.exit_code == 0, result.output
    assert "client-login" not in route.calls.last.request.headers
    params = _body(route)["params"]
    assert params["SelectionCriteria"] == {"Logins": ["c1"], "Archived": "NO"}
    assert "Grants" in params["FieldNames"]


@respx.mock
def test_agency_add_organization_member_and_update() -> None:
    route = _route("agencyclients", {"Login": "romashka", "ClientId": 5})
    result = _run(
        "agency", "add-organization", "--name", "Ромашка", "--email", "a@b.ru", "--grant", "IMPORT_XLS=YES",
        "--setting", "SHARED_ACCOUNT_ENABLED=YES", "--confirm", "--json",
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    body = _body(route)
    assert body["method"] == "addPassportOrganization"
    assert body["params"]["Notification"]["EmailSubscriptions"][0] == {
        "Option": "RECEIVE_RECOMMENDATIONS",
        "Value": "NO",
    }
    assert body["params"]["Grants"] == [{"Privilege": "IMPORT_XLS", "Value": "YES"}]
    assert json.loads(result.output)["result"] == {"Login": "romashka", "ClientId": 5}

    assert _run("agency", "add-member", "romashka").exit_code == 2  # нет адреса приглашения
    assert _run("agency", "add-member", "romashka", "--invite-phone", "+7900", "--confirm").exit_code == 0
    assert _body(route)["params"] == {
        "PassportOrganizationLogin": "romashka",
        "Role": "USER",
        "SendInviteTo": {"Phone": "+7900"},
    }

    assert _run("agency", "update", "5").exit_code == 2
    assert _run("agency", "update", "5", "--grant", "EDIT_CAMPAIGNS=NO", "--phone", "1", "--confirm").exit_code == 0
    assert _body(route)["params"]["Clients"] == [
        {"ClientId": 5, "Phone": "1", "Grants": [{"Privilege": "EDIT_CAMPAIGNS", "Value": "NO"}]}
    ]
