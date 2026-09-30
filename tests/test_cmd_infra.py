"""`yd dict`, `yd changes`, `yd report`, `yd feeds`: тела запросов и разбор ответов."""

from __future__ import annotations

import base64
import json

import pytest
import respx
from httpx import Response
from typer.testing import CliRunner

from rb_yandex_direct.cli import app
from rb_yandex_direct.core.errors import InvalidArguments
from rb_yandex_direct.core.report_payloads import ReportSpec, report_params
from rb_yandex_direct.providers.direct import PROD_BASE
from rb_yandex_direct.providers.reports import Report, report_name


@pytest.fixture(autouse=True)
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")


def _run(*args: str):
    return CliRunner().invoke(app, list(args), prog_name="yd")


def _route(service: str, result: dict):
    return respx.post(f"{PROD_BASE}/{service}").mock(return_value=Response(200, json={"result": result}))


def _body(route) -> dict:
    return json.loads(route.calls.last.request.content)


# --- dict ---------------------------------------------------------------------------------


@respx.mock
def test_dict_get_and_geo_regions() -> None:
    route = _route("dictionaries", {"Currencies": [{"Currency": "RUB"}]})
    result = _run("dict", "get", "Currencies", "--json")
    assert result.exit_code == 0, result.output
    assert _body(route)["params"] == {"DictionaryNames": ["Currencies"]}
    assert json.loads(result.output)["dictionaries"]["Currencies"][0]["Currency"] == "RUB"

    route = _route(
        "dictionaries",
        {"GeoRegions": [{"GeoRegionId": 43, "GeoRegionName": "Казань", "ParentGeoRegionNames": {"Items": ["Россия"]}}]},
    )
    result = _run("dict", "geo-regions", "--name", "Каз")
    assert result.exit_code == 0, result.output
    body = _body(route)
    assert (body["method"], body["params"]["SelectionCriteria"]) == ("getGeoRegions", {"Name": "Каз"})
    assert "Россия" in result.output


def test_dict_rejects_unknown_name_and_empty_geo_query() -> None:
    assert _run("dict", "get", "ProductivityIndicators").exit_code == 2
    assert _run("dict", "geo-regions").exit_code == 2


# --- changes ------------------------------------------------------------------------------


@respx.mock
def test_changes_campaigns_check_dictionaries() -> None:
    route = _route("changes", {"Campaigns": [{"CampaignId": 1, "ChangesIn": ["SELF", "STAT"]}], "Timestamp": "T2"})
    result = _run("changes", "campaigns", "2026-09-01T00:00:00Z", "--json")
    assert result.exit_code == 0, result.output
    assert _body(route)["params"] == {"Timestamp": "2026-09-01T00:00:00Z"}
    payload = json.loads(result.output)
    assert (payload["count"], payload["timestamp"]) == (1, "T2")

    assert _run("changes", "check", "2026-09-01T00:00:00Z").exit_code == 2
    assert _run("changes", "check", "T", "--campaign", "1", "--ad", "2").exit_code == 2
    assert _run("changes", "check", "T", "--adgroup", "7").exit_code == 0
    assert _body(route)["params"] == {
        "Timestamp": "T",
        "FieldNames": ["CampaignIds", "AdGroupIds", "AdIds", "CampaignsStat"],
        "AdGroupIds": [7],
    }

    assert _run("changes", "dictionaries").exit_code == 0
    assert _body(route) == {"method": "checkDictionaries", "params": {}}


# --- report ---------------------------------------------------------------------------------


def test_report_params_validation() -> None:
    params = report_params(
        ReportSpec(report_type="custom_report", fields=["Date"], goals=[1], attribution_models=["lc"])
    )
    assert params["DateRangeType"] == "LAST_30_DAYS"
    assert params["Goals"] == ["1"]
    assert params["AttributionModels"] == ["LC"]
    for bad in (
        ReportSpec(report_type="NOPE", fields=["Date"]),
        ReportSpec(report_type="CUSTOM_REPORT", fields=[]),
        ReportSpec(report_type="CUSTOM_REPORT", fields=["Date"], date_from="2026-09-01"),
        ReportSpec(report_type="CUSTOM_REPORT", fields=["Date"], date_range="LAST_7_DAYS", date_to="2026-09-01"),
        ReportSpec(report_type="CUSTOM_REPORT", fields=["Date"], filters=["Clicks:BIGGER:1"]),
        ReportSpec(report_type="CUSTOM_REPORT", fields=["Date"], order_by=["Cost:UP"]),
        ReportSpec(report_type="CUSTOM_REPORT", fields=["Date"], goals=list(range(11))),
        ReportSpec(report_type="CUSTOM_REPORT", fields=["Date"], attribution_models=["XX"]),
    ):
        with pytest.raises(InvalidArguments):
            report_params(bad)


def test_report_parse_types_and_name_is_stable() -> None:
    tsv = "Date\tCampaignId\tQuery\tCost\tConversions\n2026-09-01\t5\t2024\t12.5\t--\nTotal rows: 1\n"
    assert Report(tsv, None, None).parse() == [
        {"Date": "2026-09-01", "CampaignId": 5, "Query": "2024", "Cost": 12.5, "Conversions": None}
    ]
    assert report_name({"a": 1}) == report_name({"a": 1}) != report_name({"a": 2})


@respx.mock
def test_report_custom_request_and_rows() -> None:
    tsv = "Date\tClicks\tCost\n2026-09-01\t10\t100.5\n"
    route = respx.post(f"{PROD_BASE}/reports").mock(return_value=Response(200, text=tsv, headers={"RequestId": "r9"}))
    result = _run(
        "report", "custom", "--type", "CUSTOM_REPORT", "--field", "Date", "--field", "Clicks", "--field", "Cost",
        "--date-from", "2026-09-01", "--date-to", "2026-09-02", "--campaign", "5", "--order-by", "Cost:DESC",
        "--mode", "offline", "--no-vat", "--json",
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    request = route.calls.last.request
    assert request.headers["processingMode"] == "offline"
    assert request.headers["skipReportHeader"] == "true"
    params = json.loads(request.content)["params"]
    assert params["SelectionCriteria"]["Filter"] == [{"Field": "CampaignId", "Operator": "IN", "Values": ["5"]}]
    assert params["IncludeVAT"] == "NO"
    assert params["ReportName"].startswith("yd-")
    payload = json.loads(result.output)
    assert payload["rows"] == [{"Date": "2026-09-01", "Clicks": 10, "Cost": 100.5}]
    assert payload["request_id"] == "r9"


@respx.mock
def test_report_waits_for_queue_and_maps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rb_yandex_direct.providers.reports.asyncio.sleep", _no_sleep)
    respx.post(f"{PROD_BASE}/reports").mock(
        side_effect=[
            Response(201, headers={"retryIn": "1"}),
            Response(200, text="Date\tClicks\n2026-09-01\t1\n"),
        ]
    )
    result = _run("report", "account", "--range", "YESTERDAY", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["count"] == 1

    respx.post(f"{PROD_BASE}/reports").mock(
        return_value=Response(400, json={"error": {"error_code": 4000, "error_string": "Неверные поля"}})
    )
    result = _run("report", "campaigns", "--json")
    assert result.exit_code == 5
    assert json.loads(result.output)["error"]["api_code"] == 4000


async def _no_sleep(_: float) -> None:
    return None


def test_report_dry_run_needs_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YANDEX_DIRECT_TOKEN")
    result = _run("report", "queries", "--range", "LAST_7_DAYS", "--campaign", "1", "--dry-run", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["params"]["ReportType"] == "SEARCH_QUERY_PERFORMANCE_REPORT"


def test_report_types() -> None:
    payload = json.loads(_run("report", "types", "--json").output)
    assert "CUSTOM_REPORT" in payload["report_types"]


# --- feeds --------------------------------------------------------------------------------


@respx.mock
def test_feeds_list_uses_valid_field_names() -> None:
    route = _route("feeds", {"Feeds": [{"Id": 1, "Name": "F", "UrlFeed": {"Url": "https://x"}}]})
    result = _run("feeds", "list")
    assert result.exit_code == 0, result.output
    params = _body(route)["params"]
    assert "FilterQuantity" not in params["FieldNames"]
    assert params["UrlFeedFieldNames"] == ["Url", "Login", "RemoveUtmTags"]
    assert "https://x" in result.output


@respx.mock
def test_feeds_add_file_and_password_are_masked_in_output(tmp_path) -> None:
    route = _route("feeds", {"AddResults": [{"Id": 3}]})
    feed = tmp_path / "feed.xml"
    feed.write_bytes(b"<yml/>")
    result = _run("feeds", "add", "--name", "F", "--file", str(feed), "--confirm", "--json")
    assert result.exit_code == 0, result.output
    sent = _body(route)["params"]["Feeds"][0]
    assert sent["SourceType"] == "FILE"
    assert base64.b64decode(sent["FileFeed"]["Data"]) == b"<yml/>"
    assert sent["FileFeed"]["Data"] not in result.output

    result = _run(
        "feeds", "add", "--name", "U", "--url", "https://x/f.xml", "--feed-login", "u", "--feed-password", "s3cr3t",
        "--remove-utm", "--confirm", "--json",
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert _body(route)["params"]["Feeds"][0]["UrlFeed"] == {
        "Url": "https://x/f.xml",
        "Login": "u",
        "Password": "s3cr3t",
        "RemoveUtmTags": "YES",
    }
    assert "s3cr3t" not in result.output


def test_feeds_add_and_update_validation(tmp_path) -> None:
    assert _run("feeds", "add", "--name", "F", "--dry-run").exit_code == 2
    assert _run("feeds", "add", "--name", "F", "--url", "u", "--file", "f", "--dry-run").exit_code == 2
    assert _run("feeds", "update", "1", "--dry-run").exit_code == 2
    assert _run("feeds", "add", "--name", "F", "--file", str(tmp_path / "none.xml"), "--dry-run").exit_code == 2


@respx.mock
def test_feeds_update_delete_and_json(tmp_path) -> None:
    route = _route("feeds", {"UpdateResults": [{"Id": 1}]})
    assert _run("feeds", "update", "1", "--name", "N", "--keep-utm", "--confirm").exit_code == 0
    assert _body(route)["params"]["Feeds"] == [{"Id": 1, "UrlFeed": {"RemoveUtmTags": "NO"}, "Name": "N"}]
    assert _run("feeds", "delete", "1", "2", "--confirm").exit_code == 0
    assert _body(route)["params"] == {"SelectionCriteria": {"Ids": [1, 2]}}
    path = tmp_path / "feeds.json"
    path.write_text(json.dumps({"Feeds": [{"Id": 1, "Name": "X"}]}), encoding="utf-8")
    assert _run("feeds", "update-json", "--from-json", str(path), "--confirm").exit_code == 0
    assert _body(route)["params"] == {"Feeds": [{"Id": 1, "Name": "X"}]}
    path.write_text("[]", encoding="utf-8")
    assert _run("feeds", "add-json", "--from-json", str(path), "--dry-run").exit_code == 2
