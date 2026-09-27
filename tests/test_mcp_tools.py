"""Every MCP tool runs against a mocked Direct API: read tools once, write tools as dry-run and with confirm.

Arguments are synthesized from each tool's signature (overridden where the
tool validates structure), so a new tool is covered automatically.
"""

from __future__ import annotations

import asyncio
import inspect
import typing
from pathlib import Path

import httpx
import pytest
import respx

from rb_yandex_direct import mcp_server
from rb_yandex_direct.core.client import PROD_BASE

TOOLS = {t.name: t.fn for t in mcp_server.mcp._tool_manager.list_tools()}
REPORT_TSV = "Date\tClicks\n2026-09-01\t10\nTotal rows: 1\n"

TEXT_AD = {"AdGroupId": 1, "TextAd": {"Title": "t", "Text": "x", "Href": "https://example.com"}}
OVERRIDES: dict[str, dict] = {
    "add_ads": {"ads": [TEXT_AD]},
    "update_ads": {"ads": [{"Id": 1, "TextAd": {"Title": "t2"}}]},
    "add_adgroups": {"groups": [{"Name": "g", "CampaignId": 1, "RegionIds": [213]}]},
    "add_campaigns": {"campaigns": [{"Name": "c", "StartDate": "2026-10-01", "TextCampaign": {}}]},
    "add_keywords": {"keywords": [{"AdGroupId": 1, "Keyword": "диван"}]},
    "add_retargeting_lists": {"lists": [{"Name": "r", "Rules": []}]},
    "add_negative_keyword_shared_sets": {"sets": [{"Name": "n", "NegativeKeywords": ["бу"]}]},
    "update_negative_keyword_shared_set": {"set_id": 1, "name": "n"},
    "set_keyword_bids": {"bids": [{"KeywordId": 1, "SearchBid": 1_000_000}]},
    "set_keyword_bids_auto": {"bids": [{"KeywordId": 1, "BiddingRule": {}}]},
    "set_audience_target_bids": {"bids": [{"Id": 1, "ContextBid": 1_000_000}]},
    "set_dynamic_text_ad_target_bids": {"bids": [{"Id": 1, "Bid": 1_000_000}]},
    "set_smart_ad_target_bids": {"bids": [{"Id": 1, "AverageCpc": 1_000_000}]},
    "toggle_bid_modifiers": {"toggles": [{"CampaignId": 1, "Type": "DEMOGRAPHICS_ADJUSTMENT", "Enabled": "NO"}]},
    "get_keyword_bids": {"campaign_ids": [1]},
    "add_text_ad": {"adgroup_id": 1, "title": "t", "text": "x", "href": "https://example.com"},
}


def _value(name: str, hint: object) -> object:
    hint_s = str(hint)
    if "list[int]" in hint_s:
        return [1]
    if "list[str]" in hint_s:
        return ["x"]
    if "list[dict]" in hint_s:
        return [{"Id": 1, "Name": "x", "AdGroupId": 1, "CampaignId": 1}]
    if "dict" in hint_s:
        return {"ClientInfo": "x"}
    if hint is float:
        return 100.0
    if hint is int:
        return 1
    if "date" in name or name == "timestamp":
        return "2026-09-01"
    return "x"


def _args(name: str, fn: typing.Callable, tmp_path: Path) -> dict:
    hints = typing.get_type_hints(fn)
    args = {}
    for pname, param in inspect.signature(fn).parameters.items():
        if param.default is inspect.Parameter.empty:
            args[pname] = _value(pname, hints.get(pname))
    if name == "add_ad_images_from_file":
        image = tmp_path / "banner.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n")
        args["file_paths"] = [str(image)]
    return {**args, **OVERRIDES.get(name, {})}


def _api(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/reports"):
        return httpx.Response(200, text=REPORT_TSV)
    return httpx.Response(200, json={"result": {}}, headers={"Units": "1/2/3"})


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_tool_runs(name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")
    monkeypatch.setenv("YANDEX_DIRECT_MANAGED_LOGINS", "a@yandex.ru")
    fn = TOOLS[name]
    args = _args(name, fn, tmp_path)
    writes = "confirm" in inspect.signature(fn).parameters
    with respx.mock(assert_all_called=False) as router:
        route = router.post(url__startswith=PROD_BASE).mock(side_effect=_api)
        if writes:
            preview = asyncio.run(fn(**args))
            assert route.call_count == 0, "a write tool without confirm must not call the API"
            assert preview
            args["confirm"] = True
        asyncio.run(fn(**args))
    assert route.call_count >= 1


def test_tool_without_token_asks_to_log_in() -> None:
    from yandex_oauth.errors import AuthRequired

    with pytest.raises(AuthRequired, match="direct"):
        asyncio.run(TOOLS["list_campaigns"]())
