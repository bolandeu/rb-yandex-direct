"""Тесты P0-write методов."""

import json

import pytest
import respx
from click.testing import CliRunner
from httpx import Response

from rb_yandex_direct.cli import cli
from rb_yandex_direct.core.client import PROD_BASE, DirectClient


def _route(service: str, payload: dict):
    return respx.post(f"{PROD_BASE}/{service}").mock(
        return_value=Response(200, json={"result": payload}, headers={"RequestId": "r1"})
    )


@pytest.mark.asyncio
@respx.mock
async def test_suspend_campaigns_body() -> None:
    route = _route("campaigns", {"SuspendResults": [{"Id": 1}, {"Id": 2}]})
    c = DirectClient(token="t")
    result = await c.suspend_campaigns([1, 2])
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "suspend"
    assert body["params"]["SelectionCriteria"]["Ids"] == [1, 2]
    assert len(result["SuspendResults"]) == 2


@pytest.mark.asyncio
@respx.mock
async def test_resume_and_archive_campaigns() -> None:
    _route("campaigns", {"ResumeResults": [{"Id": 1}]})
    c = DirectClient(token="t")
    result = await c.resume_campaigns([1])
    assert "ResumeResults" in result


@pytest.mark.asyncio
@respx.mock
async def test_keywords_suspend_resume_delete() -> None:
    for method_key in ("SuspendResults", "ResumeResults", "DeleteResults"):
        _route("keywords", {method_key: [{"Id": 1}]})
    c = DirectClient(token="t")
    for coro in (c.suspend_keywords([1]), c.resume_keywords([1]), c.delete_keywords([1])):
        result = await coro
        assert any(k.endswith("Results") for k in result)


@pytest.mark.asyncio
@respx.mock
async def test_set_keyword_bids_body() -> None:
    route = _route("keywordbids", {"SetResults": [{"KeywordId": 1}]})
    c = DirectClient(token="t")
    await c.set_keyword_bids([{"KeywordId": 1, "SearchBid": 30_000_000}])
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "set"
    assert body["params"]["KeywordBids"][0]["SearchBid"] == 30_000_000


@pytest.mark.asyncio
@respx.mock
async def test_moderate_ads_body() -> None:
    route = _route("ads", {"ModerateResults": [{"Id": 100}]})
    c = DirectClient(token="t")
    await c.moderate_ads([100, 200])
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "moderate"
    assert body["params"]["SelectionCriteria"]["Ids"] == [100, 200]


@pytest.mark.asyncio
@respx.mock
async def test_update_negative_set_requires_at_least_one_field() -> None:
    c = DirectClient(token="t")
    with pytest.raises(ValueError):
        await c.update_negative_keyword_shared_set(set_id=1)


@pytest.mark.asyncio
@respx.mock
async def test_update_negative_set_body() -> None:
    route = _route("negativekeywordsharedsets", {"UpdateResults": [{"Id": 1}]})
    c = DirectClient(token="t")
    await c.update_negative_keyword_shared_set(set_id=1, negative_keywords=["стоп", "минус"])
    body = json.loads(route.calls.last.request.content)
    set_obj = body["params"]["NegativeKeywordSharedSets"][0]
    assert set_obj["Id"] == 1
    assert set_obj["NegativeKeywords"]["Items"] == ["стоп", "минус"]


# --- CLI: проверка, что -y пропускает промпт ---


@respx.mock
def test_cli_suspend_without_yes_aborts(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    runner = CliRunner()
    # Ответим "n" на подтверждение — должен быть Abort без HTTP-вызова
    result = runner.invoke(cli, ["campaigns", "suspend", "1", "2"], input="n\n")
    assert result.exit_code != 0
    assert respx.calls.call_count == 0


@respx.mock
def test_cli_suspend_with_yes(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    _route("campaigns", {"SuspendResults": [{"Id": 1}, {"Id": 2}]})
    runner = CliRunner()
    result = runner.invoke(cli, ["campaigns", "suspend", "1", "2", "-y"])
    assert result.exit_code == 0, result.output
    assert respx.calls.call_count == 1


@respx.mock
def test_cli_bids_set_converts_rubles_to_micros(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("keywordbids", {"SetResults": [{"KeywordId": 5}]})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["bids", "set", "--keyword", "5", "--search-bid", "30", "-y"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["KeywordBids"][0]["SearchBid"] == 30_000_000


# --- Sprint 5A: keywords.add / keywords.update / campaigns.update / bidmodifiers ---


@pytest.mark.asyncio
@respx.mock
async def test_add_keywords_body() -> None:
    route = _route("keywords", {"AddResults": [{"Id": 111}]})
    c = DirectClient(token="t")
    await c.add_keywords(
        [
            {"AdGroupId": 5, "Keyword": "купить пылесос", "Bid": 30_000_000},
        ]
    )
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "add"
    assert body["params"]["Keywords"][0]["AdGroupId"] == 5
    assert body["params"]["Keywords"][0]["Bid"] == 30_000_000


@pytest.mark.asyncio
async def test_add_keywords_rejects_empty() -> None:
    c = DirectClient(token="t")
    with pytest.raises(ValueError):
        await c.add_keywords([])


@pytest.mark.asyncio
async def test_add_keywords_rejects_over_1000() -> None:
    c = DirectClient(token="t")
    with pytest.raises(ValueError):
        await c.add_keywords([{"AdGroupId": 1, "Keyword": "x"}] * 1001)


@pytest.mark.asyncio
@respx.mock
async def test_update_keywords_body() -> None:
    route = _route("keywords", {"UpdateResults": [{"Id": 1}]})
    c = DirectClient(token="t")
    await c.update_keywords([{"Id": 1, "StrategyPriority": "HIGH"}])
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "update"
    assert body["params"]["Keywords"][0]["StrategyPriority"] == "HIGH"


@pytest.mark.asyncio
@respx.mock
async def test_update_campaigns_body() -> None:
    route = _route("campaigns", {"UpdateResults": [{"Id": 77}]})
    c = DirectClient(token="t")
    await c.update_campaigns([{"Id": 77, "Name": "новое имя"}])
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "update"
    assert body["params"]["Campaigns"][0]["Name"] == "новое имя"


@pytest.mark.asyncio
@respx.mock
async def test_set_campaign_daily_budget_converts_rubles() -> None:
    route = _route("campaigns", {"UpdateResults": [{"Id": 77}]})
    c = DirectClient(token="t")
    await c.set_campaign_daily_budget(77, 500.0, mode="DISTRIBUTED")
    body = json.loads(route.calls.last.request.content)
    campaign = body["params"]["Campaigns"][0]
    assert campaign["Id"] == 77
    assert campaign["DailyBudget"] == {"Amount": 500_000_000, "Mode": "DISTRIBUTED"}


@pytest.mark.asyncio
@respx.mock
async def test_add_bid_modifiers_body() -> None:
    route = _route("bidmodifiers", {"AddResults": [{"Id": 999}]})
    c = DirectClient(token="t")
    await c.add_bid_modifiers(
        [
            {
                "CampaignId": 1,
                "MobileAdjustment": {"BidModifier": 80},
            }
        ]
    )
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "add"
    assert body["params"]["BidModifiers"][0]["MobileAdjustment"]["BidModifier"] == 80


@pytest.mark.asyncio
@respx.mock
async def test_toggle_bid_modifiers_body() -> None:
    route = _route("bidmodifiers", {"ToggleResults": [{"CampaignId": 1}]})
    c = DirectClient(token="t")
    await c.toggle_bid_modifiers(
        [
            {"CampaignId": 1, "Type": "DEMOGRAPHICS_ADJUSTMENT", "Enabled": "NO"},
        ]
    )
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "toggle"
    item = body["params"]["BidModifierToggleItems"][0]
    assert item["Type"] == "DEMOGRAPHICS_ADJUSTMENT"
    assert item["Enabled"] == "NO"


@pytest.mark.asyncio
@respx.mock
async def test_set_and_delete_bid_modifiers() -> None:
    route_set = _route("bidmodifiers", {"SetResults": [{"Id": 1}]})
    c = DirectClient(token="t")
    await c.set_bid_modifiers([{"Id": 1, "BidModifier": 200}])
    body = json.loads(route_set.calls.last.request.content)
    assert body["method"] == "set"
    assert body["params"]["BidModifiers"][0]["BidModifier"] == 200

    route_del = _route("bidmodifiers", {"DeleteResults": [{"Id": 1}]})
    await c.delete_bid_modifiers([1, 2])
    body = json.loads(route_del.calls.last.request.content)
    assert body["method"] == "delete"
    assert body["params"]["SelectionCriteria"]["Ids"] == [1, 2]


# --- CLI ---


@respx.mock
def test_cli_keywords_add_converts_bid(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("keywords", {"AddResults": [{"Id": 1}]})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["keywords", "add", "--adgroup", "5", "--search-bid", "30", "купить", "пылесос", "-y"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    kws = body["params"]["Keywords"]
    assert len(kws) == 2
    assert kws[0]["AdGroupId"] == 5
    assert kws[0]["Bid"] == 30_000_000
    assert {k["Keyword"] for k in kws} == {"купить", "пылесос"}


@respx.mock
def test_cli_campaigns_set_budget(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("campaigns", {"UpdateResults": [{"Id": 42}]})
    runner = CliRunner()
    result = runner.invoke(cli, ["campaigns", "set-budget", "42", "500", "-y"])
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["Campaigns"][0]["DailyBudget"]["Amount"] == 500_000_000


@respx.mock
def test_cli_modifiers_add_regional(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("bidmodifiers", {"AddResults": [{"Id": 1}]})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["modifiers", "add", "--campaign", "10", "--type", "REGIONAL", "--region", "213", "--value", "150", "-y"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    mod = body["params"]["BidModifiers"][0]
    assert mod["CampaignId"] == 10
    assert mod["RegionalAdjustment"] == {"BidModifier": 150, "RegionId": 213}


@respx.mock
def test_cli_modifiers_toggle(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("bidmodifiers", {"ToggleResults": [{"CampaignId": 10}]})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["modifiers", "toggle", "--campaign", "10", "--type", "DEMOGRAPHICS_ADJUSTMENT", "--enabled", "NO", "-y"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["BidModifierToggleItems"][0]["Enabled"] == "NO"


# --- Sprint 5C: retargetinglists + audiencetargets CRUD ---


@pytest.mark.asyncio
@respx.mock
async def test_add_retargeting_lists_body() -> None:
    route = _route("retargetinglists", {"AddResults": [{"Id": 999}]})
    c = DirectClient(token="t")
    await c.add_retargeting_lists(
        [
            {
                "Name": "Корзина без покупки",
                "Type": "RETARGETING",
                "Rules": [
                    {
                        "Operator": "ALL",
                        "Arguments": [{"ExternalId": 12345, "MembershipLifeSpan": 30}],
                    }
                ],
            }
        ]
    )
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "add"
    rl = body["params"]["RetargetingLists"][0]
    assert rl["Name"] == "Корзина без покупки"
    assert rl["Rules"][0]["Operator"] == "ALL"
    assert rl["Rules"][0]["Arguments"][0]["ExternalId"] == 12345


@pytest.mark.asyncio
async def test_add_retargeting_lists_rejects_empty() -> None:
    c = DirectClient(token="t")
    with pytest.raises(ValueError):
        await c.add_retargeting_lists([])


@pytest.mark.asyncio
@respx.mock
async def test_update_and_delete_retargeting_lists() -> None:
    route_upd = _route("retargetinglists", {"UpdateResults": [{"Id": 1}]})
    c = DirectClient(token="t")
    await c.update_retargeting_lists([{"Id": 1, "Name": "новое имя"}])
    body = json.loads(route_upd.calls.last.request.content)
    assert body["method"] == "update"
    assert body["params"]["RetargetingLists"][0]["Name"] == "новое имя"

    route_del = _route("retargetinglists", {"DeleteResults": [{"Id": 1}]})
    await c.delete_retargeting_lists([1, 2])
    body = json.loads(route_del.calls.last.request.content)
    assert body["method"] == "delete"
    assert body["params"]["SelectionCriteria"]["Ids"] == [1, 2]


@pytest.mark.asyncio
@respx.mock
async def test_add_audience_targets_body() -> None:
    route = _route("audiencetargets", {"AddResults": [{"Id": 555}]})
    c = DirectClient(token="t")
    await c.add_audience_targets(
        [
            {
                "AdGroupId": 10,
                "RetargetingListId": 20,
                "ContextBid": 50_000_000,
                "StrategyPriority": "HIGH",
            }
        ]
    )
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "add"
    at = body["params"]["AudienceTargets"][0]
    assert at["RetargetingListId"] == 20
    assert at["ContextBid"] == 50_000_000


@pytest.mark.asyncio
@respx.mock
async def test_audience_targets_suspend_resume_delete() -> None:
    for key in ("SuspendResults", "ResumeResults", "DeleteResults"):
        _route("audiencetargets", {key: [{"Id": 1}]})
    c = DirectClient(token="t")
    for coro in (
        c.suspend_audience_targets([1]),
        c.resume_audience_targets([1]),
        c.delete_audience_targets([1]),
    ):
        result = await coro
        assert any(k.endswith("Results") for k in result)


# --- CLI ---


@respx.mock
def test_cli_retargeting_add(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("retargetinglists", {"AddResults": [{"Id": 99}]})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "retargeting",
            "add",
            "--name",
            "Корзина",
            "--goal",
            "111",
            "--goal",
            "222",
            "--days",
            "14",
            "--operator",
            "ANY",
            "-y",
        ],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    rl = body["params"]["RetargetingLists"][0]
    assert rl["Name"] == "Корзина"
    assert rl["Rules"][0]["Operator"] == "ANY"
    ext_ids = {a["ExternalId"] for a in rl["Rules"][0]["Arguments"]}
    assert ext_ids == {111, 222}
    assert all(a["MembershipLifeSpan"] == 14 for a in rl["Rules"][0]["Arguments"])


@respx.mock
def test_cli_audiences_add(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("audiencetargets", {"AddResults": [{"Id": 1}]})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["audiences", "add", "--adgroup", "10", "--retargeting", "99", "--context-bid", "50", "-y"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    at = body["params"]["AudienceTargets"][0]
    assert at["AdGroupId"] == 10
    assert at["RetargetingListId"] == 99
    assert at["ContextBid"] == 50_000_000


def test_cli_audiences_add_requires_exactly_one_target(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    runner = CliRunner()
    # ни --retargeting, ни --interest — ошибка
    result = runner.invoke(cli, ["audiences", "add", "--adgroup", "10", "-y"])
    assert result.exit_code != 0
    # оба сразу — тоже ошибка
    result = runner.invoke(
        cli,
        ["audiences", "add", "--adgroup", "10", "--retargeting", "1", "--interest", "2", "-y"],
    )
    assert result.exit_code != 0


# --- P2: dictionaries, sitelinks, vcards, adextensions, adimages, creatives, turbopages ---


@pytest.mark.asyncio
@respx.mock
async def test_add_negative_keyword_shared_sets_body() -> None:
    route = _route("negativekeywordsharedsets", {"AddResults": [{"Id": 1}]})
    c = DirectClient(token="t")
    await c.add_negative_keyword_shared_sets(
        [
            {"Name": "Общие минусы", "NegativeKeywords": ["стоп", "минус"]},
        ]
    )
    body = json.loads(route.calls.last.request.content)
    # add принимает плоский массив строк, не {Items: [...]}
    assert body["params"]["NegativeKeywordSharedSets"][0]["NegativeKeywords"] == ["стоп", "минус"]


@pytest.mark.asyncio
async def test_negative_keyword_shared_sets_rejects_over_30() -> None:
    c = DirectClient(token="t")
    with pytest.raises(ValueError):
        await c.add_negative_keyword_shared_sets([{"Name": f"#{i}", "NegativeKeywords": ["x"]} for i in range(31)])


@pytest.mark.asyncio
@respx.mock
async def test_add_sitelinks_wraps_in_set() -> None:
    route = _route("sitelinks", {"AddResults": [{"Id": 1}]})
    c = DirectClient(token="t")
    await c.add_sitelinks(
        [
            {
                "Sitelinks": [
                    {"Title": "Главная", "Href": "https://example.com/"},
                ]
            }
        ]
    )
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["SitelinksSets"][0]["Sitelinks"][0]["Title"] == "Главная"


@pytest.mark.asyncio
@respx.mock
async def test_add_ad_extensions_callouts() -> None:
    route = _route("adextensions", {"AddResults": [{"Id": 1}]})
    c = DirectClient(token="t")
    await c.add_ad_extensions([{"Callout": {"CalloutText": "Бесплатная доставка"}}])
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["AdExtensions"][0]["Callout"]["CalloutText"] == "Бесплатная доставка"


@pytest.mark.asyncio
@respx.mock
async def test_add_ad_images_base64() -> None:
    route = _route("adimages", {"AddResults": [{"AdImageHash": "abc123"}]})
    c = DirectClient(token="t")
    await c.add_ad_images([{"ImageData": "iVBORw0KGgo=", "Name": "x.png", "Type": "AUTO"}])
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["AdImages"][0]["Name"] == "x.png"


@pytest.mark.asyncio
@respx.mock
async def test_delete_ad_images_uses_hashes() -> None:
    route = _route("adimages", {"DeleteResults": [{"AdImageHash": "abc"}]})
    c = DirectClient(token="t")
    await c.delete_ad_images(["abc", "def"])
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["SelectionCriteria"]["AdImageHashes"] == ["abc", "def"]


# --- Sprint 5B: ads/adgroups CRUD ---


@pytest.mark.asyncio
@respx.mock
async def test_add_text_ad_shortcut() -> None:
    route = _route("ads", {"AddResults": [{"Id": 1}]})
    c = DirectClient(token="t")
    await c.add_text_ad(
        adgroup_id=10,
        title="Куртка зимой",
        text="Скидка 50%",
        href="https://shop.example/",
        title2="в каталоге",
    )
    body = json.loads(route.calls.last.request.content)
    ad = body["params"]["Ads"][0]
    assert ad["AdGroupId"] == 10
    assert ad["TextAd"]["Title"] == "Куртка зимой"
    assert ad["TextAd"]["Title2"] == "в каталоге"


@pytest.mark.asyncio
async def test_add_ads_rejects_missing_type_block() -> None:
    c = DirectClient(token="t")
    with pytest.raises(ValueError, match="type-specific"):
        await c.add_ads([{"AdGroupId": 1}])


@pytest.mark.asyncio
async def test_add_ads_rejects_two_type_blocks() -> None:
    c = DirectClient(token="t")
    with pytest.raises(ValueError, match="type-specific"):
        await c.add_ads(
            [
                {
                    "AdGroupId": 1,
                    "TextAd": {"Title": "a", "Text": "b", "Href": "c"},
                    "MobileAppAd": {"Title": "a", "Text": "b"},
                }
            ]
        )


@pytest.mark.asyncio
async def test_add_ads_rejects_missing_adgroup() -> None:
    c = DirectClient(token="t")
    with pytest.raises(ValueError, match="AdGroupId"):
        await c.add_ads([{"TextAd": {"Title": "a", "Text": "b", "Href": "c"}}])


@pytest.mark.asyncio
@respx.mock
async def test_add_adgroups_requires_fields() -> None:
    c = DirectClient(token="t")
    with pytest.raises(ValueError, match="RegionIds"):
        await c.add_adgroups([{"Name": "g", "CampaignId": 1}])


@pytest.mark.asyncio
@respx.mock
async def test_add_adgroups_body() -> None:
    route = _route("adgroups", {"AddResults": [{"Id": 1}]})
    c = DirectClient(token="t")
    await c.add_adgroups(
        [
            {
                "Name": "Зимние куртки",
                "CampaignId": 100,
                "RegionIds": [213],
                "NegativeKeywords": {"Items": ["дешевая"]},
            }
        ]
    )
    body = json.loads(route.calls.last.request.content)
    g = body["params"]["AdGroups"][0]
    assert g["Name"] == "Зимние куртки"
    assert g["NegativeKeywords"]["Items"] == ["дешевая"]


@pytest.mark.asyncio
@respx.mock
async def test_ads_archive_unarchive_delete() -> None:
    for key in ("ArchiveResults", "UnarchiveResults", "DeleteResults"):
        _route("ads", {key: [{"Id": 1}]})
    c = DirectClient(token="t")
    for coro in (c.archive_ads([1]), c.unarchive_ads([1]), c.delete_ads([1])):
        result = await coro
        assert any(k.endswith("Results") for k in result)


# --- P3: campaigns.add, dynamic/smart ad targets ---


@pytest.mark.asyncio
async def test_add_campaigns_requires_type_block() -> None:
    c = DirectClient(token="t")
    with pytest.raises(ValueError, match="type-specific"):
        await c.add_campaigns([{"Name": "test", "StartDate": "2026-01-01"}])


@pytest.mark.asyncio
@respx.mock
async def test_add_campaigns_body() -> None:
    route = _route("campaigns", {"AddResults": [{"Id": 1}]})
    c = DirectClient(token="t")
    await c.add_campaigns(
        [
            {
                "Name": "Зима 2026",
                "StartDate": "2026-01-01",
                "TextCampaign": {
                    "BiddingStrategy": {
                        "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
                        "Network": {"BiddingStrategyType": "SERVING_OFF"},
                    },
                },
            }
        ]
    )
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "add"
    assert "TextCampaign" in body["params"]["Campaigns"][0]


@pytest.mark.asyncio
@respx.mock
async def test_smart_ad_targets_suspend_resume() -> None:
    for key in ("SuspendResults", "ResumeResults"):
        _route("smartadtargets", {key: [{"Id": 1}]})
    c = DirectClient(token="t")
    for coro in (c.suspend_smart_ad_targets([1]), c.resume_smart_ad_targets([1])):
        result = await coro
        assert any(k.endswith("Results") for k in result)


# --- CLI ---


@respx.mock
def test_cli_ads_add_text(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("ads", {"AddResults": [{"Id": 1}]})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["ads", "add-text", "--adgroup", "10", "--title", "t1", "--text", "txt", "--href", "https://example/", "-y"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["Ads"][0]["TextAd"]["Href"] == "https://example/"


@respx.mock
def test_cli_adgroups_add(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("adgroups", {"AddResults": [{"Id": 1}]})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "adgroups",
            "add",
            "--campaign",
            "100",
            "--name",
            "Тест",
            "--region",
            "213",
            "--negative-keyword",
            "дешево",
            "-y",
        ],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    g = body["params"]["AdGroups"][0]
    assert g["RegionIds"] == [213]
    assert g["NegativeKeywords"]["Items"] == ["дешево"]


@respx.mock
def test_cli_minus_sets_add(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("negativekeywordsharedsets", {"AddResults": [{"Id": 1}]})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["minus-sets", "add", "--name", "N1", "--words", "минус1,минус2", "-y"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["NegativeKeywordSharedSets"][0]["NegativeKeywords"] == ["минус1", "минус2"]


@respx.mock
def test_cli_extensions_add(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("adextensions", {"AddResults": [{"Id": 1}]})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["extensions", "add", "Доставка бесплатно", "Гарантия 2 года", "-y"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    texts = [e["Callout"]["CalloutText"] for e in body["params"]["AdExtensions"]]
    assert texts == ["Доставка бесплатно", "Гарантия 2 года"]


# --- Минус-слова на уровне группы/кампании + audiencetargets.setBids ---


@pytest.mark.asyncio
@respx.mock
async def test_set_adgroup_negative_keywords() -> None:
    route = _route("adgroups", {"UpdateResults": [{"Id": 10}]})
    c = DirectClient(token="t")
    await c.set_adgroup_negative_keywords(10, ["купить", "дешево"])
    body = json.loads(route.calls.last.request.content)
    g = body["params"]["AdGroups"][0]
    assert g["Id"] == 10
    assert g["NegativeKeywords"]["Items"] == ["купить", "дешево"]


@pytest.mark.asyncio
@respx.mock
async def test_set_campaign_negative_keywords_text_campaign() -> None:
    route = _route("campaigns", {"UpdateResults": [{"Id": 1}]})
    c = DirectClient(token="t")
    await c.set_campaign_negative_keywords(1, ["минус1"])
    body = json.loads(route.calls.last.request.content)
    campaign = body["params"]["Campaigns"][0]
    assert campaign["TextCampaign"]["NegativeKeywords"]["Items"] == ["минус1"]


@pytest.mark.asyncio
async def test_set_campaign_negative_keywords_validates_type() -> None:
    c = DirectClient(token="t")
    with pytest.raises(ValueError, match="campaign_type"):
        await c.set_campaign_negative_keywords(1, ["x"], campaign_type="BogusType")


@pytest.mark.asyncio
@respx.mock
async def test_set_audience_target_bids_by_id() -> None:
    route = _route("audiencetargets", {"SetBidsResults": [{"Id": 5}]})
    c = DirectClient(token="t")
    await c.set_audience_target_bids(
        [
            {"Id": 5, "ContextBid": 50_000_000, "StrategyPriority": "HIGH"},
        ]
    )
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "setBids"
    assert body["params"]["Bids"][0]["Id"] == 5
    assert body["params"]["Bids"][0]["ContextBid"] == 50_000_000


@pytest.mark.asyncio
async def test_set_audience_target_bids_rejects_multiple_scopes() -> None:
    c = DirectClient(token="t")
    with pytest.raises(ValueError, match="Id/AdGroupId/CampaignId"):
        await c.set_audience_target_bids(
            [
                {"Id": 1, "AdGroupId": 2, "ContextBid": 50_000_000},
            ]
        )


@pytest.mark.asyncio
async def test_set_audience_target_bids_rejects_no_scope() -> None:
    c = DirectClient(token="t")
    with pytest.raises(ValueError, match="Id/AdGroupId/CampaignId"):
        await c.set_audience_target_bids([{"ContextBid": 50_000_000}])


@respx.mock
def test_cli_audiences_set_bid_by_adgroup(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("audiencetargets", {"SetBidsResults": [{"AdGroupId": 10}]})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["audiences", "set-bid", "--adgroup", "10", "--context-bid", "40", "--priority", "HIGH", "-y"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    item = body["params"]["Bids"][0]
    assert item["AdGroupId"] == 10
    assert item["ContextBid"] == 40_000_000
    assert item["StrategyPriority"] == "HIGH"


@pytest.mark.asyncio
@respx.mock
async def test_add_creatives_video_extension() -> None:
    route = _route("creatives", {"AddResults": [{"Id": 1}]})
    c = DirectClient(token="t")
    await c.add_creatives([{"VideoExtensionCreative": {"VideoId": "abc"}}])
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "add"
    assert body["params"]["Creatives"][0]["VideoExtensionCreative"]["VideoId"] == "abc"


@pytest.mark.asyncio
async def test_add_creatives_rejects_over_10() -> None:
    c = DirectClient(token="t")
    with pytest.raises(ValueError):
        await c.add_creatives([{"VideoExtensionCreative": {"VideoId": str(i)}} for i in range(11)])


@respx.mock
def test_cli_creatives_add_video_extension(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("creatives", {"AddResults": [{"Id": 1}]})
    runner = CliRunner()
    result = runner.invoke(cli, ["creatives", "add-video-extension", "vid1", "vid2", "-y"])
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    ids = [c["VideoExtensionCreative"]["VideoId"] for c in body["params"]["Creatives"]]
    assert ids == ["vid1", "vid2"]


@respx.mock
def test_cli_dynamic_targets_set_bid(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("dynamictextadtargets", {"SetBidsResults": [{"Id": 5}]})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["dynamic-targets", "set-bid", "--id", "5", "--bid", "30", "-y"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["Bids"][0]["Bid"] == 30_000_000


@respx.mock
def test_cli_smart_targets_set_bid(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("smartadtargets", {"SetBidsResults": [{"Id": 7}]})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["smart-targets", "set-bid", "--id", "7", "--priority", "HIGH", "-y"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["Bids"][0]["StrategyPriority"] == "HIGH"


@respx.mock
def test_cli_client_update_from_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("clients", {"UpdateResults": [{}]})
    path = tmp_path / "client.json"
    path.write_text(json.dumps({"VatRate": 20}))
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["client", "update", "--from-json", str(path), "-y"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "update"
    assert body["params"]["VatRate"] == 20


def test_resolve_login_exact_and_substring(monkeypatch) -> None:
    from rb_yandex_direct.cli import _resolve_login

    monkeypatch.setenv(
        "YANDEX_DIRECT_MANAGED_LOGINS",
        "my-shop@yandex.ru,my-blog@yandex.ru,other@yandex.ru",
    )
    assert _resolve_login("my-shop@yandex.ru") == "my-shop@yandex.ru"
    assert _resolve_login("shop") == "my-shop@yandex.ru"
    assert _resolve_login("other") == "other@yandex.ru"
    assert _resolve_login(None) is None
    # Полный логин с @ проходит как есть без обращения к списку.
    assert _resolve_login("not-in-list@yandex.ru") == "not-in-list@yandex.ru"

    import click

    with pytest.raises(click.ClickException, match="неоднозначный"):
        _resolve_login("my")  # совпадёт с shop и blog
    with pytest.raises(click.ClickException, match="не найден"):
        _resolve_login("xyz")


def test_resolve_login_without_managed_list(monkeypatch) -> None:
    from rb_yandex_direct.cli import _resolve_login

    monkeypatch.delenv("YANDEX_DIRECT_MANAGED_LOGINS", raising=False)
    # Без списка — любая строка возвращается as-is (ожидается, что это полный логин).
    assert _resolve_login("something") == "something"


@respx.mock
def test_cli_accounts_merges_api_and_env(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    monkeypatch.setenv("YANDEX_DIRECT_MANAGED_LOGINS", "friend@yandex.ru")

    # agency call (без Client-Login) → падает с "not an agency"
    respx.post(f"{PROD_BASE}/agencyclients").mock(
        return_value=Response(
            200, json={"error": {"error_code": 8100, "error_string": "Not agency", "error_detail": ""}}
        )
    )
    # fallback clients.get (под агентским) отдаёт self
    # Нужен routing по заголовку: первый clients.get = self, второй = friend
    call_count = {"n": 0}

    def _clients_resp(request):
        call_count["n"] += 1
        login = request.headers.get("client-login", "")
        return Response(
            200,
            json={
                "result": {
                    "Clients": [
                        {"Login": login or "infinitylab", "Currency": "RUB"},
                    ]
                }
            },
        )

    respx.post(f"{PROD_BASE}/clients").mock(side_effect=_clients_resp)

    runner = CliRunner()
    result = runner.invoke(cli, ["accounts"])
    assert result.exit_code == 0, result.output
    assert "infinitylab" in result.output
    assert "friend@yandex.ru" in result.output


@respx.mock
def test_cli_campaigns_set_negative_keywords(monkeypatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    route = _route("campaigns", {"UpdateResults": [{"Id": 1}]})
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["campaigns", "set-negative-keywords", "1", "--words", "минус1,минус2", "-y"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    c = body["params"]["Campaigns"][0]
    assert c["TextCampaign"]["NegativeKeywords"]["Items"] == ["минус1", "минус2"]
