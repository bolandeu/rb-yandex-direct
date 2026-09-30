"""Тесты P1-read методов (Спринт 4)."""

import json

import pytest
import respx
from httpx import Response

from rb_yandex_direct.providers.direct import PROD_BASE, DirectClient


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
        "Levels": ["CAMPAIGN", "AD_GROUP"],
    }
    assert body["params"]["FieldNames"] == ["Id", "CampaignId", "AdGroupId", "Level", "Type"]
    assert body["params"]["MobileAdjustmentFieldNames"] == ["BidModifier", "OperatingSystemType"]
    assert "RegionalAdjustmentFieldNames" in body["params"]


@pytest.mark.asyncio
@respx.mock
async def test_list_retargeting_lists() -> None:
    _route(
        "retargetinglists",
        {
            "RetargetingLists": [
                {"Id": 1, "Name": "Все посетители", "Type": "RETARGETING"},
            ]
        },
    )
    c = DirectClient(token="t")
    data = await c.list_retargeting_lists()
    assert data[0]["Name"] == "Все посетители"


@pytest.mark.asyncio
@respx.mock
async def test_list_audience_targets_by_adgroup() -> None:
    route = _route(
        "audiencetargets",
        {
            "AudienceTargets": [
                {"Id": 7, "AdGroupId": 50, "RetargetingListId": 1, "State": "ON"},
            ]
        },
    )
    c = DirectClient(token="t")
    await c.list_audience_targets(adgroup_ids=[50])
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["SelectionCriteria"]["AdGroupIds"] == [50]


@pytest.mark.asyncio
@respx.mock
async def test_keywords_has_search_volume_with_regions() -> None:
    route = _route(
        "keywordsresearch",
        {
            "HasSearchVolumeResults": [
                {"Keyword": "купить диван", "AllDevices": "YES"},
                {"Keyword": "купить бегемота", "AllDevices": "NO"},
            ]
        },
    )
    c = DirectClient(token="t")
    result = await c.keywords_has_search_volume(
        keywords=["купить диван", "купить бегемота"],
        region_ids=[213, 2],
    )
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "hasSearchVolume"
    assert body["params"]["SelectionCriteria"] == {
        "Keywords": ["купить диван", "купить бегемота"],
        "RegionIds": [213, 2],
    }
    assert "AllDevices" in body["params"]["FieldNames"]
    assert result[0]["AllDevices"] == "YES"


@pytest.mark.asyncio
@respx.mock
async def test_keywords_deduplicate() -> None:
    route = _route("keywordsresearch", {"Delete": {"Ids": [2]}})
    c = DirectClient(token="t")
    result = await c.keywords_deduplicate(
        [{"Id": 1, "Keyword": "диван"}, {"Id": 2, "Keyword": "диван"}], operations=["MERGE_DUPLICATES"]
    )
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "deduplicate"
    assert body["params"] == {
        "Keywords": [{"Id": 1, "Keyword": "диван"}, {"Id": 2, "Keyword": "диван"}],
        "Operation": ["MERGE_DUPLICATES"],
    }
    assert result["Delete"]["Ids"] == [2]
