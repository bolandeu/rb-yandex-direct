"""Тесты P1-read методов (Спринт 4)."""

import json
import pytest
import respx
from httpx import Response

from rb_yandex_direct.core.client import PROD_BASE, DirectClient


def _route(service: str, payload: dict):
    return respx.post(f"{PROD_BASE}/{service}").mock(
        return_value=Response(200, json={"result": payload}, headers={"RequestId": "r1"})
    )


@pytest.mark.asyncio
@respx.mock
async def test_list_bid_modifiers_filters() -> None:
    route = _route("bidmodifiers", {"BidModifiers": [{"Id": 1, "Type": "MOBILE_ADJUSTMENT"}]})
    c = DirectClient(token="t")
    await c.list_bid_modifiers(campaign_ids=[1, 2], types=["MOBILE_ADJUSTMENT"])
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["SelectionCriteria"] == {
        "CampaignIds": [1, 2],
        "Types": ["MOBILE_ADJUSTMENT"],
    }
    assert "MobileAdjustment" in body["params"]["FieldNames"]


@pytest.mark.asyncio
@respx.mock
async def test_list_retargeting_lists() -> None:
    _route("retargetinglists", {"RetargetingLists": [
        {"Id": 1, "Name": "Все посетители", "Type": "RETARGETING"},
    ]})
    c = DirectClient(token="t")
    data = await c.list_retargeting_lists()
    assert data[0]["Name"] == "Все посетители"


@pytest.mark.asyncio
@respx.mock
async def test_list_audience_targets_by_adgroup() -> None:
    route = _route("audiencetargets", {"AudienceTargets": [
        {"Id": 7, "AdGroupId": 50, "RetargetingListId": 1, "State": "ON"},
    ]})
    c = DirectClient(token="t")
    await c.list_audience_targets(adgroup_ids=[50])
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["SelectionCriteria"]["AdGroupIds"] == [50]


@pytest.mark.asyncio
@respx.mock
async def test_keywords_has_search_volume_with_regions() -> None:
    route = _route("keywordsresearch", {"SearchVolumeItems": [
        {"Phrase": "купить диван", "HasSearchVolume": True},
        {"Phrase": "купить бегемота", "HasSearchVolume": False},
    ]})
    c = DirectClient(token="t")
    result = await c.keywords_has_search_volume(
        keywords=["купить диван", "купить бегемота"],
        region_ids=[213, 2],
    )
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "hasSearchVolume"
    assert body["params"]["RegionIds"] == [213, 2]
    assert result[0]["HasSearchVolume"] is True


@pytest.mark.asyncio
@respx.mock
async def test_keywords_deduplicate() -> None:
    route = _route("keywordsresearch", {"DeduplicationResult": [{"KeywordId": 1, "State": "SUSPENDED"}]})
    c = DirectClient(token="t")
    await c.keywords_deduplicate([1, 2, 3])
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "deduplicate"
    assert body["params"]["KeywordIds"] == [1, 2, 3]


@pytest.mark.asyncio
@respx.mock
async def test_mcp_keywords_deduplicate_dry_run(monkeypatch) -> None:
    from rb_yandex_direct import mcp_server
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    result = await mcp_server.keywords_deduplicate(keyword_ids=[1, 2])
    assert result["requires_confirm"] is True
    assert result["action"] == "keywordsresearch.deduplicate"
    assert respx.calls.call_count == 0
