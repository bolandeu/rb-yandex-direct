"""Команды структуры объявлений: тела запросов к API, dry-run, ошибки формы до запроса."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from rb_yandex_direct.cli import app
from rb_yandex_direct.core import ads as ads_core
from rb_yandex_direct.core.errors import InvalidArguments
from rb_yandex_direct.providers.direct import PROD_BASE


@pytest.fixture(autouse=True)
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "t")


def _route(service: str, result: dict | None = None) -> respx.Route:
    return respx.post(f"{PROD_BASE}/{service}").mock(
        return_value=httpx.Response(200, json={"result": result or {}}, headers={"RequestId": "r1"})
    )


def _run(*args: str) -> tuple[int, dict]:
    result = CliRunner().invoke(app, ["--json", *args], prog_name="yd")
    return result.exit_code, json.loads(result.stdout) if result.stdout.strip() else {}


def _write(*args: str) -> tuple[int, dict]:
    return _run(*args, "--confirm", "--non-interactive")


def _body(route: respx.Route) -> dict:
    return json.loads(route.calls.last.request.content)


# --- adgroups -------------------------------------------------------------------------------------


@respx.mock
def test_adgroups_list_filters() -> None:
    route = _route("adgroups", {"AdGroups": [{"Id": 1, "Name": "g"}]})
    code, data = _run(
        "adgroups", "list", "--campaign", "5", "--status", "REJECTED", "--serving-status", "RARELY_SERVED"
    )
    assert code == 0, data
    assert data["count"] == 1
    criteria = _body(route)["params"]["SelectionCriteria"]
    assert criteria == {"CampaignIds": [5], "Statuses": ["REJECTED"], "ServingStatuses": ["RARELY_SERVED"]}


def test_adgroups_list_needs_campaign_or_id() -> None:
    code, data = _run("adgroups", "list")
    assert code == 2
    assert data["error"]["code"] == "INVALID_ARGUMENTS"


@respx.mock
def test_adgroups_get_requests_type_fields() -> None:
    route = _route("adgroups", {"AdGroups": [{"Id": 555}]})
    code, data = _run("adgroups", "get", "555")
    assert code == 0
    assert data["adgroup"]["Id"] == 555
    params = _body(route)["params"]
    assert "MobileAppAdGroupFieldNames" in params
    assert "UnifiedAdGroupFieldNames" in params


@respx.mock
def test_adgroups_get_missing_is_invalid_arguments() -> None:
    _route("adgroups", {"AdGroups": []})
    assert _run("adgroups", "get", "1")[0] == 2


@respx.mock
def test_adgroups_add_text_group() -> None:
    route = _route("adgroups", {"AddResults": [{"Id": 99}]})
    code, data = _write(
        "adgroups", "add", "--campaign", "1", "--name", "g", "--region", "213", "--region", "2",
        "--negative-keyword", "бу", "--minus-set", "7", "--tracking-params", "utm_source=yd",
    )  # fmt: skip
    assert code == 0, data
    assert data["ids"] == [99]
    (item,) = _body(route)["params"]["AdGroups"]
    assert item == {
        "Name": "g",
        "CampaignId": 1,
        "RegionIds": [213, 2],
        "NegativeKeywords": {"Items": ["бу"]},
        "NegativeKeywordSharedSetIds": {"Items": [7]},
        "TrackingParams": "utm_source=yd",
    }


@pytest.mark.parametrize(
    ("args", "block"),
    [
        (["--type", "dynamic", "--domain-url", "example.com"], {"DynamicTextAdGroup": {"DomainUrl": "example.com"}}),
        (["--type", "dynamic-feed", "--feed-id", "3"], {"DynamicTextFeedAdGroup": {"FeedId": 3}}),
        (["--type", "smart", "--feed-id", "3", "--ad-title-source", "name"], {"SmartAdGroup": {"FeedId": 3, "AdTitleSource": "name"}}),
        (["--type", "unified", "--offer-retargeting", "YES"], {"UnifiedAdGroup": {"OfferRetargeting": "YES"}}),
        (["--feed-id", "3", "--feed-category", "11"], {"TextAdGroupFeedParams": {"FeedId": 3, "FeedCategoryIds": {"Items": [11]}}}),
        (
            ["--type", "mobile-app", "--store-url", "https://apps.apple.com/app/id1", "--device", "DEVICE_TYPE_MOBILE"],
            {
                "MobileAppAdGroup": {
                    "StoreUrl": "https://apps.apple.com/app/id1",
                    "TargetDeviceType": ["DEVICE_TYPE_MOBILE"],
                    "TargetCarrier": "WI_FI_AND_CELLULAR",
                    "TargetOperatingSystemVersion": "1.0",
                }
            },
        ),
    ],
)  # fmt: skip
def test_adgroups_add_type_blocks(args: list[str], block: dict) -> None:
    code, data = _run("adgroups", "add", "--campaign", "1", "--name", "g", "--region", "0", *args, "--dry-run")
    assert code == 0, data
    (item,) = data["params"]["AdGroups"]
    assert {k: v for k, v in item.items() if k in ads_core.ADGROUP_TYPE_BLOCKS} == block


@pytest.mark.parametrize("kind", ["dynamic", "dynamic-feed", "smart", "mobile-app"])
def test_adgroups_add_type_requires_its_option(kind: str) -> None:
    code, data = _run("adgroups", "add", "--campaign", "1", "--name", "g", "--region", "0", "--type", kind, "--dry-run")
    assert code == 2
    assert "нужен" in data["error"]["message"]


@respx.mock
def test_adgroups_update_blocks_and_clear_tracking() -> None:
    route = _route("adgroups", {"UpdateResults": [{"Id": 5}]})
    code, _ = _write("adgroups", "update", "5", "--tracking-params", "", "--offer-retargeting", "NO", "--region", "1")
    assert code == 0
    (item,) = _body(route)["params"]["AdGroups"]
    assert item == {"Id": 5, "RegionIds": [1], "TrackingParams": "", "UnifiedAdGroup": {"OfferRetargeting": "NO"}}


def test_adgroups_update_nothing_is_error() -> None:
    assert _run("adgroups", "update", "5", "--dry-run")[0] == 2


@respx.mock
def test_adgroups_set_negative_keywords_from_file(tmp_path: Path) -> None:
    route = _route("adgroups", {"UpdateResults": [{"Id": 5}]})
    words = tmp_path / "minus.txt"
    words.write_text("бу\n# комментарий\n\nремонт\n", encoding="utf-8")
    code, _ = _write("adgroups", "set-negative-keywords", "5", "--from-file", str(words), "-w", "даром")
    assert code == 0
    assert _body(route)["params"]["AdGroups"][0]["NegativeKeywords"] == {"Items": ["даром", "бу", "ремонт"]}


def test_adgroups_add_json_validates(tmp_path: Path) -> None:
    path = tmp_path / "g.json"
    path.write_text(json.dumps({"AdGroups": [{"Name": "g", "CampaignId": 1}]}), encoding="utf-8")
    code, data = _run("adgroups", "add-json", "--from-json", str(path), "--dry-run")
    assert code == 2
    assert "RegionIds" in data["error"]["message"]


def test_adgroups_json_rejects_two_type_blocks() -> None:
    with pytest.raises(InvalidArguments, match="не более одного"):
        ads_core.validate_adgroups(
            [{"Name": "g", "CampaignId": 1, "RegionIds": [0], "SmartAdGroup": {}, "UnifiedAdGroup": {}}]
        )


# --- ads ------------------------------------------------------------------------------------------


@respx.mock
def test_ads_list_criteria() -> None:
    route = _route("ads", {"Ads": [{"Id": 1, "TextAd": {"Title": "t"}}]})
    code, data = _run("ads", "list", "--adgroup", "5", "--type", "TEXT_AD", "--mobile", "NO", "--extension", "9")
    assert code == 0, data
    criteria = _body(route)["params"]["SelectionCriteria"]
    assert criteria == {"AdGroupIds": [5], "Types": ["TEXT_AD"], "Mobile": "NO", "AdExtensionIds": [9]}


def test_ads_list_needs_filter() -> None:
    assert _run("ads", "list", "--state", "ON")[0] == 2


@respx.mock
def test_ads_get_all_type_fields() -> None:
    route = _route("ads", {"Ads": [{"Id": 7}]})
    code, data = _run("ads", "get", "7")
    assert code == 0
    assert data["ad"] == {"Id": 7}
    assert "ResponsiveAdFieldNames" in _body(route)["params"]


@respx.mock
def test_ads_get_missing() -> None:
    _route("ads", {"Ads": []})
    assert _run("ads", "get", "7")[0] == 2


@respx.mock
def test_ads_moderation_statuses() -> None:
    route = _route("ads", {"Ads": []})
    assert _run("ads", "moderation", "--campaign", "3")[0] == 0
    assert _body(route)["params"]["SelectionCriteria"]["Statuses"] == ["DRAFT", "MODERATION", "PREACCEPTED", "REJECTED"]


@respx.mock
@pytest.mark.parametrize("method", ["moderate", "suspend", "resume", "archive", "unarchive", "delete"])
def test_ads_status_methods(method: str) -> None:
    route = _route("ads", {f"{method.capitalize()}Results": [{"Id": 1}]})
    code, data = _write("ads", method, "1", "2")
    assert code == 0, data
    body = _body(route)
    assert (body["method"], body["params"]) == (method, {"SelectionCriteria": {"Ids": [1, 2]}})


@respx.mock
def test_ads_add_text_full() -> None:
    route = _route("ads", {"AddResults": [{"Id": 42}]})
    code, data = _write(
        "ads", "add-text", "--adgroup", "5", "--title", "T", "--text", "X", "--href", "https://e.com",
        "--callout", "1", "--callout", "2", "--price", "1990", "--price-qualifier", "FROM", "--video-extension", "3",
    )  # fmt: skip
    assert code == 0, data
    (ad,) = _body(route)["params"]["Ads"]
    assert ad["AdGroupId"] == 5
    assert ad["TextAd"] == {
        "Title": "T",
        "Text": "X",
        "Href": "https://e.com",
        "Mobile": "NO",
        "AdExtensionIds": [1, 2],
        "VideoExtension": {"CreativeId": 3},
        "PriceExtension": {"Price": 1_990_000_000, "PriceQualifier": "FROM", "PriceCurrency": "RUB"},
    }


def test_ads_add_text_needs_link() -> None:
    assert _run("ads", "add-text", "--adgroup", "5", "--title", "T", "--text", "X", "--dry-run")[0] == 2


def test_ads_add_responsive_dry_run() -> None:
    code, data = _run(
        "ads", "add-responsive", "--adgroup", "5", "--title", "A", "--title", "B", "--text", "X",
        "--image-hash", "h1", "--href", "https://e.com", "--dry-run",
    )  # fmt: skip
    assert code == 0
    assert data["dry_run"] is True
    assert data["params"]["Ads"][0]["ResponsiveAd"] == {
        "Titles": ["A", "B"],
        "Texts": ["X"],
        "Href": "https://e.com",
        "AdImageHashes": ["h1"],
    }


def test_ads_add_mobile_app_features() -> None:
    code, data = _run(
        "ads", "add-mobile-app", "--adgroup", "5", "--title", "A", "--text", "X", "--feature", "icon=yes", "--dry-run"
    )
    assert code == 0
    block = data["params"]["Ads"][0]["MobileAppAd"]
    assert block["Action"] == "INSTALL"
    assert block["Features"] == [{"Feature": "ICON", "Enabled": "YES"}]


def test_ads_add_mobile_app_bad_feature() -> None:
    args = ("ads", "add-mobile-app", "--adgroup", "5", "--title", "A", "--text", "X", "--feature", "ICON", "--dry-run")
    assert _run(*args)[0] == 2


@pytest.mark.parametrize(
    ("args", "block", "expected"),
    [
        (["add-image", "--image-hash", "h", "--turbo", "3"], "TextImageAd", {"AdImageHash": "h", "TurboPageId": 3}),
        (["add-builder", "--creative", "9", "--href", "https://e.com"], "TextAdBuilderAd", {"Creative": {"CreativeId": 9}, "Href": "https://e.com"}),
        (["add-shopping", "--feed", "7", "--default-text", "D"], "ShoppingAd", {"FeedId": 7, "DefaultTexts": ["D"]}),
        (["add-shopping", "--feed", "7", "--default-text", "D", "--listing"], "ListingAd", {"FeedId": 7, "DefaultTexts": ["D"]}),
    ],
)  # fmt: skip
def test_ads_typed_add(args: list[str], block: str, expected: dict) -> None:
    code, data = _run("ads", args[0], "--adgroup", "5", *args[1:], "--dry-run")
    assert code == 0, data
    assert data["params"]["Ads"][0][block] == expected


@pytest.mark.parametrize("command", ["add-image", "add-builder"])
def test_ads_image_like_need_link(command: str) -> None:
    extra = ["--image-hash", "h"] if command == "add-image" else ["--creative", "9"]
    assert _run("ads", command, "--adgroup", "5", *extra, "--dry-run")[0] == 2


@respx.mock
def test_ads_update_callouts_and_clear_image() -> None:
    route = _route("ads", {"UpdateResults": [{"Id": 7}]})
    code, _ = _write("ads", "update", "7", "--image-hash", "", "--callout-add", "1", "--callout-remove", "2")
    assert code == 0
    (ad,) = _body(route)["params"]["Ads"]
    assert ad == {
        "Id": 7,
        "TextAd": {
            "AdImageHash": None,
            "CalloutSetting": {
                "AdExtensions": [
                    {"AdExtensionId": 1, "Operation": "ADD"},
                    {"AdExtensionId": 2, "Operation": "REMOVE"},
                ]
            },
        },
    }


def test_ads_update_nothing() -> None:
    assert _run("ads", "update", "7", "--dry-run")[0] == 2


@respx.mock
def test_ads_partial_failure_is_exit_5_with_report() -> None:
    _route("ads", {"AddResults": [{"Errors": [{"Code": 5005, "Message": "Поле задано неверно"}]}]})
    code, data = _write("ads", "add-text", "--adgroup", "5", "--title", "T", "--text", "X", "--href", "https://e.com")
    assert code == 5
    assert data["ok"] is False
    assert data["failed"] == 1
    assert data["errors"][0]["Code"] == 5005


def test_ads_add_json_and_update_json_validate(tmp_path: Path) -> None:
    add = tmp_path / "a.json"
    add.write_text(json.dumps([{"AdGroupId": 1}]), encoding="utf-8")
    assert _run("ads", "add-json", "--from-json", str(add), "--dry-run")[0] == 2
    upd = tmp_path / "u.json"
    upd.write_text(json.dumps({"Ads": [{"Id": 1, "ResponsiveAd": {"Titles": ["A"]}}]}), encoding="utf-8")
    code, data = _run("ads", "update-json", "--from-json", str(upd), "--dry-run")
    assert code == 0
    assert data["params"]["Ads"][0]["ResponsiveAd"] == {"Titles": ["A"]}


def test_items_from_json_rejects_empty() -> None:
    with pytest.raises(InvalidArguments):
        ads_core.items_from_json({"Ads": []}, "Ads")


def test_validate_ads_limits() -> None:
    with pytest.raises(InvalidArguments, match="пуст"):
        ads_core.validate_ads([])
    with pytest.raises(InvalidArguments, match="1000"):
        ads_core.validate_ads([{"AdGroupId": 1, "TextAd": {}}] * 1001)
    with pytest.raises(InvalidArguments, match="пуст"):
        ads_core.validate_adgroups([])
    with pytest.raises(InvalidArguments, match="1000"):
        ads_core.validate_adgroups([{"Id": 1}] * 1001, update=True)
    with pytest.raises(InvalidArguments, match="объект"):
        ads_core.validate_adgroups(["x"])  # ty: ignore[invalid-argument-type]


def test_price_extension_and_callouts_helpers() -> None:
    assert ads_core.price_extension(None, None, None, None) is None
    assert ads_core.price_extension(1, 2, None, None) == {
        "Price": 1,
        "OldPrice": 2,
        "PriceQualifier": "NONE",
        "PriceCurrency": "RUB",
    }
    assert ads_core.callout_setting([], [], []) is None
    assert ads_core.callout_setting([], [], [5]) == {"AdExtensions": [{"AdExtensionId": 5, "Operation": "SET"}]}


# --- images / videos / creatives ------------------------------------------------------------------


@respx.mock
def test_images_add_sends_base64_but_previews_size(tmp_path: Path) -> None:
    png = tmp_path / "b.png"
    png.write_bytes(b"\x89PNG-data")
    code, data = _run("images", "add", str(png), "--dry-run")
    assert code == 0
    assert data["params"]["AdImages"][0]["ImageData"] == "<9 байт>"

    route = _route("adimages", {"AddResults": [{"AdImageHash": "h1"}]})
    code, data = _write("images", "add", str(png), "--type", "WIDE")
    assert code == 0, data
    (item,) = _body(route)["params"]["AdImages"]
    assert base64.b64decode(item["ImageData"]) == b"\x89PNG-data"
    assert (item["Name"], item["Type"]) == ("b.png", "WIDE")


def test_images_add_missing_file() -> None:
    code, data = _run("images", "add", "/nonexistent/x.png", "--dry-run")
    assert code == 2
    assert "Не удалось прочитать" in data["error"]["message"]


@respx.mock
def test_images_list_and_delete() -> None:
    route = _route("adimages", {"AdImages": [{"AdImageHash": "h"}]})
    code, _ = _run("images", "list", "--associated", "NO", "--hash", "h")
    assert code == 0
    assert _body(route)["params"]["SelectionCriteria"] == {"AdImageHashes": ["h"], "Associated": "NO"}
    route = _route("adimages", {"DeleteResults": [{}]})
    assert _write("images", "delete", "h1", "h2")[0] == 0
    assert _body(route)["params"] == {"SelectionCriteria": {"AdImageHashes": ["h1", "h2"]}}


@respx.mock
def test_videos_add_url_and_file(tmp_path: Path) -> None:
    route = _route("advideos", {"AddResults": [{"Id": "v1"}]})
    code, data = _write("videos", "add", "--url", "https://e.com/v.mp4")
    assert code == 0, data
    assert _body(route)["params"] == {"AdVideos": [{"Url": "https://e.com/v.mp4"}]}
    clip = tmp_path / "v.mp4"
    clip.write_bytes(b"MP4")
    code, _ = _write("videos", "add", "--file", str(clip))
    assert code == 0
    (item,) = _body(route)["params"]["AdVideos"]
    assert (base64.b64decode(item["VideoData"]), item["Name"]) == (b"MP4", "v.mp4")


def test_videos_add_needs_exactly_one_source(tmp_path: Path) -> None:
    assert _run("videos", "add", "--dry-run")[0] == 2
    assert _run("videos", "add", "--url", "u", "--file", "f", "--dry-run")[0] == 2


@respx.mock
def test_videos_list() -> None:
    route = _route("advideos", {"AdVideos": [{"Id": "v1", "Status": "READY"}]})
    code, data = _run("videos", "list", "v1")
    assert code == 0
    assert data["videos"][0]["Status"] == "READY"
    assert _body(route)["params"]["SelectionCriteria"] == {"Ids": ["v1"]}


@respx.mock
def test_creatives_list_and_add() -> None:
    route = _route("creatives", {"Creatives": []})
    assert _run("creatives", "list", "--type", "SMART_CREATIVE", "--id", "3")[0] == 0
    assert _body(route)["params"]["SelectionCriteria"] == {"Ids": [3], "Types": ["SMART_CREATIVE"]}
    route = _route("creatives", {"AddResults": [{"Id": 1}, {"Id": 2}]})
    code, data = _write("creatives", "add-video-extension", "vid1", "vid2")
    assert code == 0
    assert data["ids"] == [1, 2]
    assert _body(route)["params"]["Creatives"][1] == {"VideoExtensionCreative": {"VideoId": "vid2"}}


def test_creatives_add_limit() -> None:
    ids = [str(i) for i in range(11)]
    assert _run("creatives", "add-video-extension", *ids, "--dry-run")[0] == 2


# --- sitelinks / vcards / extensions / turbo / businesses / leads ---------------------------------


@respx.mock
def test_sitelinks_add_parses_links() -> None:
    route = _route("sitelinks", {"AddResults": [{"Id": 11}]})
    code, _ = _write(
        "sitelinks", "add", "--link", "Доставка|https://e.com/d", "--link", "Оплата|https://e.com/p|Картой"
    )
    assert code == 0
    assert _body(route)["params"] == {
        "SitelinksSets": [
            {
                "Sitelinks": [
                    {"Title": "Доставка", "Href": "https://e.com/d"},
                    {"Title": "Оплата", "Href": "https://e.com/p", "Description": "Картой"},
                ]
            }
        ]
    }


def test_sitelinks_add_bad_link_and_limit() -> None:
    assert _run("sitelinks", "add", "--link", "без ссылки", "--dry-run")[0] == 2
    many = [arg for i in range(9) for arg in ("--link", f"t{i}|https://e.com/{i}")]
    assert _run("sitelinks", "add", *many, "--dry-run")[0] == 2


@respx.mock
def test_sitelinks_list_without_filter_has_no_criteria() -> None:
    route = _route("sitelinks", {"SitelinksSets": [{"Id": 1, "Sitelinks": [{"Title": "a"}]}]})
    code, data = _run("sitelinks", "list")
    assert code == 0
    assert data["count"] == 1
    assert "SelectionCriteria" not in _body(route)["params"]
    assert _run("sitelinks", "list", "--id", "1")[0] == 0
    assert _body(route)["params"]["SelectionCriteria"] == {"Ids": [1]}


@respx.mock
def test_vcards_list_filters_campaign_after_response() -> None:
    _route("vcards", {"VCards": [{"Id": 1, "CampaignId": 5}, {"Id": 2, "CampaignId": 6}]})
    code, data = _run("vcards", "list", "--campaign", "6")
    assert code == 0
    assert [v["Id"] for v in data["vcards"]] == [2]


@respx.mock
def test_vcards_add_typed() -> None:
    route = _route("vcards", {"AddResults": [{"Id": 1}]})
    code, data = _write(
        "vcards", "add", "--campaign", "5", "--country", "Россия", "--city", "Москва", "--company", "Р",
        "--work-time", "0#4#9#00#18#00", "--phone-country-code", "+7", "--phone-city-code", "495",
        "--phone-number", "1234567", "--messenger", "telegram|shop",
    )  # fmt: skip
    assert code == 0, data
    (item,) = _body(route)["params"]["VCards"]
    assert item["Phone"] == {"CountryCode": "+7", "CityCode": "495", "PhoneNumber": "1234567"}
    assert item["InstantMessenger"] == {"MessengerClient": "telegram", "MessengerLogin": "shop"}


def test_vcards_add_bad_messenger_and_json_validation(tmp_path: Path) -> None:
    base = ["vcards", "add", "--campaign", "5", "--country", "Р", "--city", "М", "--company", "Р", "--work-time", "0"]
    phone = ["--phone-country-code", "+7", "--phone-city-code", "495", "--phone-number", "1"]
    assert _run(*base, *phone, "--messenger", "telegram", "--dry-run")[0] == 2
    path = tmp_path / "v.json"
    path.write_text(json.dumps([{"CampaignId": 1}]), encoding="utf-8")
    code, data = _run("vcards", "add-json", "--from-json", str(path), "--dry-run")
    assert code == 2
    assert "Country" in data["error"]["message"]


@respx.mock
def test_extensions_list_and_add() -> None:
    route = _route("adextensions", {"AdExtensions": [{"Id": 1, "Callout": {"CalloutText": "Доставка"}}]})
    code, _ = _run("extensions", "list", "--state", "ON", "--modified-since", "2026-09-01T00:00:00Z")
    assert code == 0
    assert _body(route)["params"]["SelectionCriteria"] == {"States": ["ON"], "ModifiedSince": "2026-09-01T00:00:00Z"}
    route = _route("adextensions", {"AddResults": [{"Id": 1}]})
    assert _write("extensions", "add", "Доставка за день")[0] == 0
    assert _body(route)["params"] == {"AdExtensions": [{"Callout": {"CalloutText": "Доставка за день"}}]}


def test_extensions_add_too_long() -> None:
    assert _run("extensions", "add", "x" * 26, "--dry-run")[0] == 2


@respx.mock
@pytest.mark.parametrize(
    ("group", "service"), [("sitelinks", "sitelinks"), ("vcards", "vcards"), ("extensions", "adextensions")]
)
def test_deletes(group: str, service: str) -> None:
    route = _route(service, {"DeleteResults": [{"Id": 1}]})
    assert _write(group, "delete", "1")[0] == 0
    assert _body(route)["params"] == {"SelectionCriteria": {"Ids": [1]}}


@respx.mock
def test_turbo_businesses_leads() -> None:
    route = _route("turbopages", {"TurboPages": [{"Id": 1}]})
    assert _run("turbo", "list", "--bound-with-href", "https://e.com")[0] == 0
    params = _body(route)["params"]
    assert params["SelectionCriteria"] == {"BoundWithHrefs": ["https://e.com"]}
    assert "BoundWithHref" in params["FieldNames"]

    route = _route("businesses", {"Businesses": [{"Id": 1, "Name": "Р"}]})
    code, data = _run("businesses")
    assert (code, data["count"]) == (0, 1)
    assert "SelectionCriteria" not in _body(route)["params"]

    route = _route("leads", {"Leads": [{"Id": "l1"}]})
    code, data = _run("leads", "--turbo-page", "3", "--date-from", "2026-09-01", "--date-to", "2026-09-02")
    assert code == 0, data
    assert _body(route)["params"]["SelectionCriteria"] == {
        "TurboPageIds": [3],
        "DateTimeFrom": "2026-09-01T00:00:00Z",
        "DateTimeTo": "2026-09-02T23:59:59Z",
    }


def test_human_output_renders_tables() -> None:
    with respx.mock:
        _route("sitelinks", {"SitelinksSets": [{"Id": 1, "Sitelinks": [{"Title": "Доставка"}]}]})
        result = CliRunner().invoke(app, ["sitelinks", "list"], prog_name="yd")
    assert result.exit_code == 0
    assert "Доставка" in result.stdout
