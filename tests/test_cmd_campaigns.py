"""`yd campaigns` и `yd strategies`: тела запросов, стратегии, dry-run/confirm, частичные ошибки."""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response
from typer.testing import CliRunner

from rb_yandex_direct.cli import app
from rb_yandex_direct.core.campaign_payloads import CampaignSpec, campaign_add_item
from rb_yandex_direct.core.errors import InvalidArguments
from rb_yandex_direct.core.strategy import (
    StrategyParams,
    bidding_strategy,
    block_name,
    package_strategy_block,
    priority_goals,
)
from rb_yandex_direct.providers.direct import PROD_BASE


@pytest.fixture(autouse=True)
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")


def _run(*args: str, input: str | None = None):
    return CliRunner().invoke(app, list(args), prog_name="yd", input=input)


def _route(service: str, result: dict):
    return respx.post(f"{PROD_BASE}/{service}").mock(
        return_value=Response(200, json={"result": result}, headers={"RequestId": "r1"})
    )


def _body(route) -> dict:
    return json.loads(route.calls.last.request.content)


# --- стратегии (core) ---------------------------------------------------------------


def test_block_name_is_camel_case() -> None:
    assert block_name("WB_MAXIMUM_CLICKS") == "WbMaximumClicks"
    assert block_name("PAY_FOR_CONVERSION_CRR") == "PayForConversionCrr"


def test_bidding_strategy_routes_params_to_both_auto_sides() -> None:
    params = StrategyParams(average_cpa=800, goal_id=5)
    result = bidding_strategy("UNIFIED_CAMPAIGN", "AVERAGE_CPA", "AVERAGE_CPA", params)
    assert result["Search"]["AverageCpa"] == {"AverageCpa": 800_000_000, "GoalId": 5}
    assert result["Network"]["AverageCpa"] == {"AverageCpa": 800_000_000, "GoalId": 5}


def test_bidding_strategy_rejects_missing_unused_and_unknown() -> None:
    with pytest.raises(InvalidArguments, match="--weekly-budget"):
        bidding_strategy("TEXT_CAMPAIGN", "WB_MAXIMUM_CLICKS", "SERVING_OFF", StrategyParams())
    with pytest.raises(InvalidArguments, match="--crr"):
        bidding_strategy("TEXT_CAMPAIGN", "HIGHEST_POSITION", "SERVING_OFF", StrategyParams(crr=10))
    with pytest.raises(InvalidArguments, match="недоступна"):
        bidding_strategy("TEXT_CAMPAIGN", "AVERAGE_CPI", "SERVING_OFF", StrategyParams())
    with pytest.raises(InvalidArguments, match="add-json"):
        bidding_strategy("TEXT_CAMPAIGN", "AVERAGE_ROI", "SERVING_OFF", StrategyParams())


def test_bidding_strategy_network_default_and_placements() -> None:
    result = bidding_strategy(
        "TEXT_CAMPAIGN",
        "HIGHEST_POSITION",
        "NETWORK_DEFAULT",
        StrategyParams(limit_percent=30),
        placement_types={"ProductGallery": "NO"},
    )
    assert result["Search"] == {"BiddingStrategyType": "HIGHEST_POSITION", "PlacementTypes": {"ProductGallery": "NO"}}
    assert result["Network"] == {"BiddingStrategyType": "NETWORK_DEFAULT", "NetworkDefault": {"LimitPercent": 30}}


def test_bidding_strategy_update_skips_required_and_absent_sides() -> None:
    result = bidding_strategy("TEXT_CAMPAIGN", "WB_MAXIMUM_CLICKS", None, StrategyParams(), update=True)
    assert result == {"Search": {"BiddingStrategyType": "WB_MAXIMUM_CLICKS"}}


def test_package_strategy_block_and_priority_goals() -> None:
    assert package_strategy_block("average_cpc", StrategyParams(average_cpc=12.5)) == {
        "AverageCpc": {"AverageCpc": 12_500_000}
    }
    with pytest.raises(InvalidArguments, match="--goal-id"):
        package_strategy_block("WB_MAXIMUM_CONVERSION_RATE", StrategyParams())
    with pytest.raises(InvalidArguments, match="Тип пакетной"):
        package_strategy_block("HIGHEST_POSITION", StrategyParams())
    assert priority_goals(["7=150", "8"]) == {"Items": [{"GoalId": 7, "Value": 150_000_000}, {"GoalId": 8, "Value": 0}]}
    with pytest.raises(InvalidArguments):
        priority_goals(["x=1"])


def test_campaign_add_item_type_specific_validation() -> None:
    smart = campaign_add_item(
        "SMART_CAMPAIGN",
        CampaignSpec(
            name="S",
            start_date="2026-10-01",
            search_strategy="AVERAGE_CPC_PER_CAMPAIGN",
            network_strategy="NETWORK_DEFAULT",
            strategy=StrategyParams(average_cpc=25),
            counter_ids=[987],
        ),
    )
    assert smart["SmartCampaign"]["CounterId"] == 987
    with pytest.raises(InvalidArguments, match="ровно один счётчик"):
        campaign_add_item(
            "SMART_CAMPAIGN", CampaignSpec(name="S", search_strategy="SERVING_OFF", network_strategy="SERVING_OFF")
        )
    with pytest.raises(InvalidArguments, match="--frequency-cap"):
        campaign_add_item("TEXT_CAMPAIGN", CampaignSpec(name="T", frequency_cap="3/7"))
    with pytest.raises(InvalidArguments, match="--priority-goal"):
        campaign_add_item(
            "TEXT_CAMPAIGN",
            CampaignSpec(name="T", search_strategy="AVERAGE_CPA_MULTIPLE_GOALS", network_strategy="SERVING_OFF"),
        )
    cpm = campaign_add_item(
        "CPM_BANNER_CAMPAIGN",
        CampaignSpec(
            name="C",
            network_strategy="WB_MAXIMUM_IMPRESSIONS",
            strategy=StrategyParams(average_cpm=150, spend_limit=30000),
            frequency_cap="3/7",
            video_target="views",
            settings=["ADD_METRICA_TAG=YES"],
        ),
    )
    block = cpm["CpmBannerCampaign"]
    assert block["FrequencyCap"] == {"Impressions": 3, "PeriodDays": 7}
    assert block["VideoTarget"] == "VIEWS"
    assert block["BiddingStrategy"]["Search"] == {"BiddingStrategyType": "SERVING_OFF"}
    assert block["Settings"] == [{"Option": "ADD_METRICA_TAG", "Value": "YES"}]


# --- campaigns: команды ---------------------------------------------------------------


@respx.mock
def test_add_text_campaign_body() -> None:
    route = _route("campaigns", {"AddResults": [{"Id": 42}]})
    result = _run(
        "campaigns", "add", "text", "--name", "Весна", "--start-date", "2026-10-01",
        "--search-strategy", "WB_MAXIMUM_CLICKS", "--weekly-budget", "10000", "--daily-budget", "500",
        "-w", "бесплатно", "--counter-id", "987", "--setting", "ADD_METRICA_TAG=YES", "--confirm", "--json",
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    item = _body(route)["params"]["Campaigns"][0]
    assert item["Name"] == "Весна"
    assert item["DailyBudget"] == {"Amount": 500_000_000, "Mode": "STANDARD"}
    assert item["NegativeKeywords"] == {"Items": ["бесплатно"]}
    text = item["TextCampaign"]
    assert text["BiddingStrategy"]["Search"]["WbMaximumClicks"] == {"WeeklySpendLimit": 10_000_000_000}
    assert text["CounterIds"] == {"Items": [987]}
    assert json.loads(result.output)["ids"] == [42]


def test_add_invalid_strategy_param_fails_before_request() -> None:
    result = _run("campaigns", "add", "text", "--name", "T", "--crr", "10", "--dry-run", "--json")
    assert result.exit_code == 2
    assert json.loads(result.output)["error"]["code"] == "INVALID_ARGUMENTS"


@respx.mock
def test_set_strategy_detects_campaign_type() -> None:
    route = respx.post(f"{PROD_BASE}/campaigns").mock(
        side_effect=[
            Response(200, json={"result": {"Campaigns": [{"Id": 5, "Type": "UNIFIED_CAMPAIGN"}]}}),
            Response(200, json={"result": {"UpdateResults": [{"Id": 5}]}}),
        ]
    )
    result = _run(
        "campaigns", "set-strategy", "5", "--search-strategy", "AVERAGE_CPA", "--average-cpa", "900",
        "--goal-id", "3", "--confirm",
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    get_body, update_body = (json.loads(c.request.content) for c in route.calls)
    assert get_body["params"]["FieldNames"] == ["Id", "Type"]
    block = update_body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"]
    assert block == {
        "Search": {"BiddingStrategyType": "AVERAGE_CPA", "AverageCpa": {"AverageCpa": 900_000_000, "GoalId": 3}}
    }


@respx.mock
def test_get_requests_all_type_field_names() -> None:
    route = _route("campaigns", {"Campaigns": [{"Id": 1, "TextCampaign": {}}]})
    result = _run("campaigns", "get", "1", "--json")
    assert result.exit_code == 0, result.output
    params = _body(route)["params"]
    assert "NegativeKeywords" in params["FieldNames"]
    assert "BiddingStrategy" in params["TextCampaignFieldNames"]
    assert "CounterId" in params["SmartCampaignFieldNames"]


@respx.mock
def test_get_missing_campaign_is_invalid_arguments() -> None:
    _route("campaigns", {"Campaigns": []})
    assert _run("campaigns", "get", "1").exit_code == 2


@respx.mock
def test_list_filters() -> None:
    route = _route("campaigns", {"Campaigns": [{"Id": 1, "Name": "A", "DailyBudget": {"Amount": 500_000_000}}]})
    result = _run("campaigns", "list", "--state", "ON", "--status", "ACCEPTED", "--payment-status", "ALLOWED")
    assert result.exit_code == 0, result.output
    criteria = _body(route)["params"]["SelectionCriteria"]
    assert criteria == {"States": ["ON"], "Statuses": ["ACCEPTED"], "StatusesPayment": ["ALLOWED"]}
    assert "500" in result.output  # бюджет — в рублях в таблице


@respx.mock
def test_set_budget_and_negative_keywords_bodies() -> None:
    route = _route("campaigns", {"UpdateResults": [{"Id": 42}]})
    assert _run("campaigns", "set-budget", "42", "500", "--confirm").exit_code == 0
    assert _body(route)["params"]["Campaigns"][0]["DailyBudget"]["Amount"] == 500_000_000
    assert _run("campaigns", "set-negative-keywords", "42", "-w", "а", "-w", "б", "--confirm").exit_code == 0
    assert _body(route)["params"]["Campaigns"][0] == {"Id": 42, "NegativeKeywords": {"Items": ["а", "б"]}}


@respx.mock
def test_mutation_needs_confirm_non_interactive_and_declined_prompt() -> None:
    route = _route("campaigns", {"SuspendResults": [{"Id": 1}]})
    result = _run("campaigns", "suspend", "1", "--non-interactive", "--json")
    assert result.exit_code == 2
    assert json.loads(result.output)["error"]["code"] == "INVALID_ARGUMENTS"
    result = _run("campaigns", "suspend", "1", input="n\n")
    assert result.exit_code == 1
    assert route.call_count == 0


@respx.mock
def test_partial_failure_is_exit_5_with_full_report() -> None:
    _route(
        "campaigns",
        {"SuspendResults": [{"Id": 1}, {"Errors": [{"Code": 8800, "Message": "Объект не найден", "Details": ""}]}]},
    )
    result = _run("campaigns", "suspend", "1", "2", "--confirm", "--json")
    assert result.exit_code == 5
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert (payload["succeeded"], payload["failed"]) == (1, 1)
    assert payload["errors"][0]["Code"] == 8800


# --- strategies ---------------------------------------------------------------------------


@respx.mock
def test_strategies_list_sends_all_block_field_names() -> None:
    route = _route("strategies", {"Strategies": [{"Id": 1, "Name": "S", "Type": "AVERAGE_CPC"}]})
    result = _run("strategies", "list", "--archived", "--type", "AVERAGE_CPC", "--json")
    assert result.exit_code == 0, result.output
    params = _body(route)["params"]
    assert params["SelectionCriteria"] == {"Types": ["AVERAGE_CPC"], "IsArchived": "YES"}
    assert "GoalId" in params["StrategyAverageCpaFieldNames"]
    assert json.loads(result.output)["count"] == 1


@respx.mock
def test_strategies_add_update_archive_bodies() -> None:
    route = _route("strategies", {"AddResults": [{"Id": 9}]})
    result = _run(
        "strategies", "add", "--name", "Конверсии", "--type", "AVERAGE_CPA", "--average-cpa", "700", "--goal-id", "5",
        "--counter-id", "987", "--priority-goal", "5=1000", "--attribution-model", "lsc", "--confirm",
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    item = _body(route)["params"]["Strategies"][0]
    assert item["AverageCpa"] == {"AverageCpa": 700_000_000, "GoalId": 5}
    assert item["CounterIds"] == {"Items": [987]}
    assert item["PriorityGoals"] == {"Items": [{"GoalId": 5, "Value": 1_000_000_000}]}
    assert item["AttributionModel"] == "LSC"

    assert _run("strategies", "update", "9", "--weekly-budget", "1").exit_code == 2  # без --type
    assert _run("strategies", "update", "9", "--name", "X", "--confirm").exit_code == 0
    assert _body(route)["params"]["Strategies"] == [{"Id": 9, "Name": "X"}]

    assert _run("strategies", "archive", "9", "--confirm").exit_code == 0
    body = _body(route)
    assert (body["method"], body["params"]) == ("archive", {"SelectionCriteria": {"Ids": [9]}})
