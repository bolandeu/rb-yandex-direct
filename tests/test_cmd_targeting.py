"""Команды таргетинга и ставок: тело запроса к API, рубли → микро, проверки аргументов, dry-run."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from rb_yandex_direct.cli import app
from rb_yandex_direct.providers.direct import PROD_BASE

WRITE = ["--confirm", "--non-interactive", "--json"]


@pytest.fixture(autouse=True)
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")


def run(*args: str):
    return CliRunner().invoke(app, list(args), prog_name="yd")


def route(service: str, result: dict | None = None) -> respx.Route:
    return respx.post(f"{PROD_BASE}/{service}").mock(
        return_value=httpx.Response(200, json={"result": result or {}}, headers={"RequestId": "r1"})
    )


def body(r: respx.Route) -> dict:
    return json.loads(r.calls.last.request.content)


# --- keywords ------------------------------------------------------------------------------------


@respx.mock
def test_keywords_add_converts_bids_and_autotargeting() -> None:
    r = route("keywords", {"AddResults": [{"Id": 1}, {"Id": 2}]})
    result = run(
        "keywords", "add", "диван", "--autotargeting-phrase", "--adgroup", "555", "--search-bid", "12.5",
        "--network-bid", "3", "--priority", "HIGH", "--autotargeting", "exact=yes", "--autotargeting",
        "WithCompetitorsBrand=NO", *WRITE,
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    common = {"AdGroupId": 555, "Bid": 12_500_000, "ContextBid": 3_000_000, "StrategyPriority": "HIGH"}
    assert body(r)["params"]["Keywords"] == [
        {**common, "Keyword": "диван"},
        {
            **common,
            "Keyword": "---autotargeting",
            "AutotargetingSettings": {"Categories": {"Exact": "YES"}, "BrandOptions": {"WithCompetitorsBrand": "NO"}},
        },
    ]
    assert json.loads(result.output)["ids"] == [1, 2]


def test_keywords_add_rejects_bad_autotargeting() -> None:
    result = run("keywords", "add", "x", "--adgroup", "1", "--autotargeting", "Bogus=YES", *WRITE)
    assert result.exit_code == 2
    assert json.loads(result.output)["error"]["code"] == "INVALID_ARGUMENTS"


@respx.mock
def test_keywords_list_filters() -> None:
    r = route("keywords", {"Keywords": [{"Id": 1, "Keyword": "диван", "Bid": 5_000_000}]})
    result = run("keywords", "list", "--campaign", "7", "--state", "ON", "--serving-status", "ELIGIBLE", "--json")
    assert result.exit_code == 0, result.output
    criteria = body(r)["params"]["SelectionCriteria"]
    assert criteria == {"CampaignIds": [7], "States": ["ON"], "ServingStatuses": ["ELIGIBLE"]}
    assert json.loads(result.output)["keywords"][0]["Keyword"] == "диван"


def test_keywords_list_requires_filter() -> None:
    assert run("keywords", "list", "--json").exit_code == 2


@respx.mock
def test_keywords_update_has_no_priority() -> None:
    r = route("keywords", {"UpdateResults": [{"Id": 9}]})
    result = run("keywords", "update", "9", "--keyword", "угловой диван", "--user-param1", "a", *WRITE)
    assert result.exit_code == 0, result.output
    assert body(r)["params"]["Keywords"] == [{"Id": 9, "Keyword": "угловой диван", "UserParam1": "a"}]


@respx.mock
def test_keywords_dedup_uses_adgroup_keywords() -> None:
    r = respx.post(f"{PROD_BASE}/keywords").mock(
        return_value=httpx.Response(200, json={"result": {"Keywords": [{"Id": 5, "Keyword": "диван"}]}})
    )
    research = route("keywordsresearch", {"Delete": {"Ids": [5]}})
    result = run("keywords", "dedup", "диван купить", "--adgroup", "555", "--operation", "MERGE_DUPLICATES", "--json")
    assert result.exit_code == 0, result.output
    assert body(r)["params"]["SelectionCriteria"] == {"AdGroupIds": [555]}
    assert body(research)["params"] == {
        "Keywords": [{"Keyword": "диван купить"}, {"Id": 5, "Keyword": "диван"}],
        "Operation": ["MERGE_DUPLICATES"],
    }
    assert json.loads(result.output)["result"]["Delete"]["Ids"] == [5]


@respx.mock
def test_keywords_check_volume() -> None:
    r = route("keywordsresearch", {"HasSearchVolumeResults": [{"Keyword": "диван", "AllDevices": "YES"}]})
    result = run("keywords", "check-volume", "диван", "--region", "213", "--json")
    assert result.exit_code == 0, result.output
    assert body(r)["params"]["SelectionCriteria"] == {"Keywords": ["диван"], "RegionIds": [213]}


def test_keywords_suspend_needs_confirm_non_interactive() -> None:
    result = run("keywords", "suspend", "1", "--non-interactive", "--json")
    assert result.exit_code == 2
    assert "--confirm" in json.loads(result.output)["error"]["message"]


# --- bids ----------------------------------------------------------------------------------------


@respx.mock
def test_bids_set_converts_rubles_to_micros() -> None:
    r = route("keywordbids", {"SetResults": [{"KeywordId": 5}]})
    result = run("bids", "set", "--keyword", "5", "--search-bid", "30", "--priority", "LOW", *WRITE)
    assert result.exit_code == 0, result.output
    assert body(r)["params"]["KeywordBids"] == [{"KeywordId": 5, "SearchBid": 30_000_000, "StrategyPriority": "LOW"}]


def test_bids_set_requires_one_scope() -> None:
    assert run("bids", "set", "--keyword", "1", "--adgroup", "2", "--search-bid", "1", *WRITE).exit_code == 2
    assert run("bids", "set", "--search-bid", "1", *WRITE).exit_code == 2


@respx.mock
def test_bids_set_auto_bidding_rule() -> None:
    r = route("keywordbids", {"SetAutoResults": [{"CampaignId": 7}]})
    result = run(
        "bids", "set-auto", "--campaign", "7", "--target-traffic-volume", "75", "--increase-percent", "10",
        "--bid-ceiling", "40", *WRITE,
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert body(r)["params"]["KeywordBids"] == [
        {
            "CampaignId": 7,
            "BiddingRule": {
                "SearchByTrafficVolume": {"TargetTrafficVolume": 75, "IncreasePercent": 10, "BidCeiling": 40_000_000}
            },
        }
    ]


def test_bids_set_auto_needs_exactly_one_rule() -> None:
    assert run("bids", "set-auto", "--keyword", "1", *WRITE).exit_code == 2


@respx.mock
def test_bids_list_sends_sub_field_names() -> None:
    r = route("keywordbids", {"KeywordBids": [{"KeywordId": 1, "Search": {"Bid": 2_000_000}}]})
    result = run("bids", "list", "--adgroup", "3", "--json")
    assert result.exit_code == 0, result.output
    params = body(r)["params"]
    assert "Search" not in params["FieldNames"]
    assert params["SearchFieldNames"] == ["Bid", "AutotargetingSearchBidIsAuto", "AuctionBids"]
    assert params["NetworkFieldNames"] == ["Bid", "Coverage"]


@respx.mock
def test_bids_classic_set_auto() -> None:
    r = route("bids", {"SetAutoResults": [{"KeywordId": 1}]})
    result = run(
        "bids-classic", "set-auto", "--keyword", "1", "--scope", "SEARCH", "--position", "P12", "--max-bid", "30",
        "--calculate-by", "VALUE", *WRITE,
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert body(r)["params"]["Bids"] == [
        {"KeywordId": 1, "Scope": ["SEARCH"], "MaxBid": 30_000_000, "Position": "P12", "CalculateBy": "VALUE"}
    ]


@respx.mock
def test_bids_classic_list() -> None:
    r = route("bids", {"Bids": [{"KeywordId": 1, "Bid": 1_000_000}]})
    result = run("bids-classic", "list", "--campaign", "7", "--json")
    assert result.exit_code == 0, result.output
    assert body(r)["params"]["SelectionCriteria"] == {"CampaignIds": [7]}
    assert json.loads(result.output)["count"] == 1


# --- modifiers -----------------------------------------------------------------------------------


@respx.mock
def test_modifiers_add_regional_is_array() -> None:
    r = route("bidmodifiers", {"AddResults": [{"Ids": [11]}]})
    result = run(
        "modifiers", "add", "--campaign", "7", "--type", "REGIONAL", "--region", "213", "--value", "150", *WRITE
    )
    assert result.exit_code == 0, result.output
    assert body(r)["params"]["BidModifiers"] == [
        {"CampaignId": 7, "RegionalAdjustments": [{"BidModifier": 150, "RegionId": 213}]}
    ]


@respx.mock
def test_modifiers_add_mobile_with_os() -> None:
    r = route("bidmodifiers", {"AddResults": [{"Ids": [12]}]})
    result = run("modifiers", "add", "--adgroup", "5", "--type", "MOBILE", "--os", "IOS", "--value", "80", *WRITE)
    assert result.exit_code == 0, result.output
    assert body(r)["params"]["BidModifiers"] == [
        {"AdGroupId": 5, "MobileAdjustment": {"BidModifier": 80, "OperatingSystemType": "IOS"}}
    ]


@pytest.mark.parametrize(
    "extra",
    [
        ["--type", "DEMOGRAPHICS"],
        ["--type", "REGIONAL"],
        ["--type", "RETARGETING"],
        ["--type", "SERP_LAYOUT"],
        ["--type", "INCOME_GRADE"],
    ],
)
def test_modifiers_add_requires_type_condition(extra: list[str]) -> None:
    assert run("modifiers", "add", "--campaign", "1", "--value", "100", *extra, *WRITE).exit_code == 2


@respx.mock
def test_modifiers_add_demographics_serp_income() -> None:
    r = route("bidmodifiers", {"AddResults": [{"Ids": [1]}]})
    run("modifiers", "add", "--campaign", "1", "--type", "DEMOGRAPHICS", "--gender", "GENDER_MALE", "--age",
        "AGE_25_34", "--value", "120", *WRITE)  # fmt: skip
    assert body(r)["params"]["BidModifiers"][0]["DemographicsAdjustments"] == [
        {"BidModifier": 120, "Gender": "GENDER_MALE", "Age": "AGE_25_34"}
    ]
    run(
        "modifiers",
        "add",
        "--campaign",
        "1",
        "--type",
        "SERP_LAYOUT",
        "--serp-layout",
        "ALONE",
        "--value",
        "90",
        *WRITE,
    )
    assert body(r)["params"]["BidModifiers"][0]["SerpLayoutAdjustments"] == [{"BidModifier": 90, "SerpLayout": "ALONE"}]
    run("modifiers", "add", "--campaign", "1", "--type", "INCOME_GRADE", "--grade", "HIGH", "--value", "110", *WRITE)
    assert body(r)["params"]["BidModifiers"][0]["IncomeGradeAdjustments"] == [{"BidModifier": 110, "Grade": "HIGH"}]
    run("modifiers", "add", "--campaign", "1", "--type", "RETARGETING", "--retargeting", "4", "--value", "130", *WRITE)
    assert body(r)["params"]["BidModifiers"][0]["RetargetingAdjustments"] == [
        {"BidModifier": 130, "RetargetingConditionId": 4}
    ]


@respx.mock
def test_modifiers_set_many_ids() -> None:
    r = route("bidmodifiers", {"SetResults": [{"Id": 1}, {"Id": 2}]})
    assert run("modifiers", "set", "1", "2", "--value", "90", *WRITE).exit_code == 0
    assert body(r)["params"]["BidModifiers"] == [{"Id": 1, "BidModifier": 90}, {"Id": 2, "BidModifier": 90}]


@respx.mock
def test_modifiers_list_values_column() -> None:
    route(
        "bidmodifiers",
        {"BidModifiers": [{"Id": 1, "Type": "MOBILE_ADJUSTMENT", "MobileAdjustment": {"BidModifier": 50}}]},
    )
    result = run("modifiers", "list", "--campaign", "1")
    assert result.exit_code == 0, result.output
    assert "50" in result.output


# --- minus-sets, retargeting, audiences ------------------------------------------------------------


@respx.mock
def test_minus_sets_update_plain_array(tmp_path) -> None:
    (tmp_path / "m.txt").write_text("бесплатно\n# комментарий\nскачать\n", encoding="utf-8")
    r = route("negativekeywordsharedsets", {"UpdateResults": [{"Id": 6}]})
    result = run("minus-sets", "update", "6", "--from-file", str(tmp_path / "m.txt"), *WRITE)
    assert result.exit_code == 0, result.output
    assert body(r)["params"]["NegativeKeywordSharedSets"] == [{"Id": 6, "NegativeKeywords": ["бесплатно", "скачать"]}]


@respx.mock
def test_minus_sets_add() -> None:
    r = route("negativekeywordsharedsets", {"AddResults": [{"Id": 6}]})
    assert run("minus-sets", "add", "--name", "Общие", "-w", "даром", *WRITE).exit_code == 0
    assert body(r)["params"]["NegativeKeywordSharedSets"] == [{"Name": "Общие", "NegativeKeywords": ["даром"]}]


@respx.mock
def test_retargeting_add_rule() -> None:
    r = route("retargetinglists", {"AddResults": [{"Id": 4}]})
    result = run("retargeting", "add", "--name", "Корзина", "--goal", "1", "--goal", "2", "--days", "14",
                 "--operator", "ALL", *WRITE)  # fmt: skip
    assert result.exit_code == 0, result.output
    assert body(r)["params"]["RetargetingLists"] == [
        {
            "Name": "Корзина",
            "Type": "RETARGETING",
            "Rules": [
                {
                    "Operator": "ALL",
                    "Arguments": [
                        {"ExternalId": 1, "MembershipLifeSpan": 14},
                        {"ExternalId": 2, "MembershipLifeSpan": 14},
                    ],
                }
            ],
        }
    ]


@respx.mock
def test_retargeting_update_replaces_rules() -> None:
    r = route("retargetinglists", {"UpdateResults": [{"Id": 4}]})
    assert run("retargeting", "update", "4", "--goal", "9", *WRITE).exit_code == 0
    assert body(r)["params"]["RetargetingLists"][0]["Rules"][0]["Arguments"] == [
        {"ExternalId": 9, "MembershipLifeSpan": 30}
    ]


def test_retargeting_update_needs_changes() -> None:
    assert run("retargeting", "update", "4", *WRITE).exit_code == 2


@respx.mock
def test_audiences_add_and_set_bids() -> None:
    r = route("audiencetargets", {"AddResults": [{"Id": 5}]})
    assert run("audiences", "add", "--adgroup", "1", "--retargeting", "4", "--context-bid", "7", *WRITE).exit_code == 0
    assert body(r)["params"]["AudienceTargets"] == [{"AdGroupId": 1, "RetargetingListId": 4, "ContextBid": 7_000_000}]
    assert run("audiences", "set-bids", "--adgroup", "1", "--priority", "HIGH", *WRITE).exit_code == 0
    assert body(r)["params"]["Bids"] == [{"AdGroupId": 1, "StrategyPriority": "HIGH"}]


def test_audiences_add_requires_exactly_one_target() -> None:
    assert run("audiences", "add", "--adgroup", "1", *WRITE).exit_code == 2
    assert run("audiences", "add", "--adgroup", "1", "--retargeting", "1", "--interest", "2", *WRITE).exit_code == 2


# --- dynamic / feed / smart targets ----------------------------------------------------------------


@respx.mock
def test_dynamic_targets_add_conditions() -> None:
    r = route("dynamictextadtargets", {"AddResults": [{"Id": 8}]})
    result = run("dynamic-targets", "add", "--adgroup", "5", "--name", "Каталог", "--condition",
                 "URL:contains_any:/catalog/|/shop/", "--bid", "10", *WRITE)  # fmt: skip
    assert result.exit_code == 0, result.output
    assert body(r)["params"]["Webpages"] == [
        {
            "AdGroupId": 5,
            "Name": "Каталог",
            "Conditions": [{"Operand": "URL", "Operator": "CONTAINS_ANY", "Arguments": ["/catalog/", "/shop/"]}],
            "Bid": 10_000_000,
        }
    ]


@pytest.mark.parametrize("spec", ["URL:CONTAINS_ANY", "URL::x", "URL:CONTAINS_ANY:|"])
def test_bad_condition_is_invalid_arguments(spec: str) -> None:
    assert run("dynamic-targets", "add", "--adgroup", "5", "--name", "x", "--condition", spec, *WRITE).exit_code == 2


@respx.mock
def test_feed_targets_add_and_list() -> None:
    r = route("dynamicfeedadtargets", {"AddResults": [{"Id": 81}]})
    result = run("dynamic-feed-targets", "add", "--adgroup", "5", "--name", "Диваны", "--condition",
                 "categoryId:EQUALS_ANY:12", "--available-items-only", "YES", *WRITE)  # fmt: skip
    assert result.exit_code == 0, result.output
    assert body(r)["params"]["DynamicFeedAdTargets"] == [
        {
            "AdGroupId": 5,
            "Name": "Диваны",
            "Conditions": {"Items": [{"Operand": "categoryId", "Operator": "EQUALS_ANY", "Arguments": ["12"]}]},
            "AvailableItemsOnly": "YES",
        }
    ]
    route("dynamicfeedadtargets", {"DynamicFeedAdTargets": [{"Id": 81, "Conditions": {"Items": []}}]})
    listed = run("dynamic-feed-targets", "list", "--adgroup", "5", "--json")
    assert json.loads(listed.output)["targets"][0]["Id"] == 81


@respx.mock
def test_smart_targets_add_update_set_bids() -> None:
    r = route("smartadtargets", {"AddResults": [{"Id": 9}]})
    assert run("smart-targets", "add", "--adgroup", "5", "--name", "Все", "--average-cpc", "15", *WRITE).exit_code == 0
    assert body(r)["params"]["SmartAdTargets"] == [
        {"AdGroupId": 5, "Name": "Все", "AverageCpc": 15_000_000, "Audience": "ALL_SEGMENTS"}
    ]
    assert run("smart-targets", "update", "9", "--average-cpa", "300", *WRITE).exit_code == 0
    assert body(r)["params"]["SmartAdTargets"] == [{"Id": 9, "AverageCpa": 300_000_000}]
    assert run("smart-targets", "set-bids", "--campaign", "7", "--priority", "LOW", *WRITE).exit_code == 0
    assert body(r)["params"]["Bids"] == [{"CampaignId": 7, "StrategyPriority": "LOW"}]


@respx.mock
def test_smart_targets_list_uses_smart_ad_targets_key() -> None:
    r = route("smartadtargets", {"SmartAdTargets": [{"Id": 9, "Name": "Все"}]})
    result = run("smart-targets", "list", "--campaign", "7", "--json")
    assert result.exit_code == 0, result.output
    assert "AverageCpc" in body(r)["params"]["FieldNames"]
    assert json.loads(result.output)["count"] == 1


def test_targets_list_requires_filter() -> None:
    for group in ("dynamic-targets", "dynamic-feed-targets", "smart-targets"):
        assert run(group, "list", "--json").exit_code == 2


def test_dry_run_sends_nothing() -> None:
    with respx.mock(assert_all_called=False) as router:
        r = router.post(url__startswith=PROD_BASE)
        result = run("smart-targets", "delete", "9", "--dry-run", "--json")
    assert result.exit_code == 0
    assert not r.called
    assert json.loads(result.output)["params"] == {"SelectionCriteria": {"Ids": [9]}}
