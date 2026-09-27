"""Тесты P0-read методов DirectClient и пресетов отчётов."""

import json
import pytest
import respx
from httpx import Response

from rb_yandex_direct.core.client import PROD_BASE, DirectClient
from rb_yandex_direct.core.reports import ReportsClient


def _route_service(service: str, payload: dict):
    return respx.post(f"{PROD_BASE}/{service}").mock(
        return_value=Response(200, json=payload, headers={"Units": "1/100/1000", "RequestId": "r1"})
    )


@pytest.mark.asyncio
@respx.mock
async def test_list_adgroups_with_filters() -> None:
    route = _route_service("adgroups", {"result": {"AdGroups": [{"Id": 1, "Name": "AG"}]}})
    c = DirectClient(token="t")
    data = await c.list_adgroups(campaign_ids=[100, 200], types=["TEXT_AD_GROUP"])
    assert data == [{"Id": 1, "Name": "AG"}]
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "get"
    assert body["params"]["SelectionCriteria"] == {
        "CampaignIds": [100, 200],
        "Types": ["TEXT_AD_GROUP"],
    }


@pytest.mark.asyncio
@respx.mock
async def test_list_ads_default_text_fields() -> None:
    route = _route_service("ads", {"result": {"Ads": []}})
    c = DirectClient(token="t")
    await c.list_ads(campaign_ids=[1])
    body = json.loads(route.calls.last.request.content)
    assert "TextAdFieldNames" in body["params"]
    assert "Title" in body["params"]["TextAdFieldNames"]


@pytest.mark.asyncio
@respx.mock
async def test_list_ads_moderation_filter() -> None:
    route = _route_service("ads", {"result": {"Ads": []}})
    c = DirectClient(token="t")
    await c.list_ads_in_moderation(campaign_ids=[1])
    body = json.loads(route.calls.last.request.content)
    assert set(body["params"]["SelectionCriteria"]["Statuses"]) == {
        "DRAFT", "MODERATION", "PREACCEPTED", "REJECTED",
    }


@pytest.mark.asyncio
@respx.mock
async def test_paginated_get_iterates_limited_by() -> None:
    pages = [
        {"result": {"Campaigns": [{"Id": i} for i in range(500)], "LimitedBy": 500}},
        {"result": {"Campaigns": [{"Id": i} for i in range(500, 730)]}},
    ]
    calls = iter(pages)
    respx.post(f"{PROD_BASE}/campaigns").mock(
        side_effect=lambda *_: Response(200, json=next(calls))
    )
    c = DirectClient(token="t")
    data = await c.list_campaigns(page_limit=500)
    assert len(data) == 730


@pytest.mark.asyncio
@respx.mock
async def test_keyword_bids_requires_filter() -> None:
    c = DirectClient(token="t")
    with pytest.raises(ValueError):
        await c.get_keyword_bids()


@pytest.mark.asyncio
@respx.mock
async def test_keyword_bids_ok() -> None:
    _route_service("keywordbids", {"result": {"KeywordBids": [{"KeywordId": 1, "Search": {"Bid": 30}}]}})
    c = DirectClient(token="t")
    data = await c.get_keyword_bids(keyword_ids=[1])
    assert data[0]["Search"]["Bid"] == 30


@pytest.mark.asyncio
@respx.mock
async def test_check_campaign_changes() -> None:
    route = _route_service("changes", {"result": {"Timestamp": "2026-01-01T00:00:00Z"}})
    c = DirectClient(token="t")
    await c.check_campaign_changes(timestamp="2026-01-01T00:00:00Z", campaign_ids=[1, 2])
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "checkCampaigns"
    assert body["params"]["Timestamp"] == "2026-01-01T00:00:00Z"
    assert body["params"]["CampaignIds"] == [1, 2]


@pytest.mark.asyncio
@respx.mock
async def test_check_dictionaries() -> None:
    route = _route_service("changes", {"result": {"Timestamp": "2026-04-01T00:00:00Z"}})
    c = DirectClient(token="t")
    result = await c.check_dictionaries("2026-03-01T00:00:00Z")
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "checkDictionaries"
    assert result["Timestamp"].startswith("2026")


@pytest.mark.asyncio
@respx.mock
async def test_negative_keyword_shared_sets() -> None:
    _route_service("negativekeywordsharedsets", {"result": {"NegativeKeywordSharedSets": [
        {"Id": 1, "Name": "Set1", "NegativeKeywords": {"Items": ["stop1", "stop2"]}}
    ]}})
    c = DirectClient(token="t")
    sets = await c.list_negative_keyword_shared_sets()
    assert sets[0]["Name"] == "Set1"


@pytest.mark.asyncio
@respx.mock
async def test_report_preset_campaign_performance() -> None:
    tsv = '"Report"\nDate\tCampaignId\tImpressions\tClicks\tCost\n2026-04-01\t1\t100\t10\t500\n'
    respx.post(f"{PROD_BASE}/reports").mock(
        return_value=Response(200, text=tsv, headers={"RequestId": "r1"})
    )
    rc = ReportsClient(token="t")
    rep = await rc.campaign_performance("2026-04-01", "2026-04-19")
    rows = rep.parse()
    assert len(rows) == 1
    assert rows[0]["CampaignId"] == "1"


@pytest.mark.asyncio
@respx.mock
async def test_report_search_query_with_filter() -> None:
    tsv = "Query\tImpressions\nтест\t10\n"
    route = respx.post(f"{PROD_BASE}/reports").mock(
        return_value=Response(200, text=tsv, headers={"RequestId": "r1"})
    )
    rc = ReportsClient(token="t")
    await rc.search_query_performance("2026-04-01", "2026-04-19", campaign_ids=[1, 2])
    body = json.loads(route.calls.last.request.content)
    filters = body["params"]["SelectionCriteria"]["Filter"]
    assert filters[0]["Field"] == "CampaignId"
    assert filters[0]["Values"] == ["1", "2"]
