"""Группы объявлений и объявления: проверка и сборка тел запросов (сверено с WSDL ads/adgroups v5).

Команды собирают параметры отсюда, чтобы --dry-run показывал ровно то, что уйдёт в API,
а ошибки формы (нет обязательного поля, два блока типа) были INVALID_ARGUMENTS до запроса.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .errors import InvalidArguments

# Блоки типа в AdAddItem/AdUpdateItem: ровно один на объявление.
AD_TYPE_BLOCKS = frozenset(
    {
        "TextAd",
        "ResponsiveAd",
        "DynamicTextAd",
        "MobileAppAd",
        "TextImageAd",
        "MobileAppImageAd",
        "TextAdBuilderAd",
        "MobileAppAdBuilderAd",
        "MobileAppCpcVideoAdBuilderAd",
        "CpmBannerAdBuilderAd",
        "CpcVideoAdBuilderAd",
        "CpmVideoAdBuilderAd",
        "SmartAdBuilderAd",
        "ShoppingAd",
        "ListingAd",
    }
)

# Блоки типа в AdGroupAddItem/AdGroupUpdateItem: не больше одного (у текстовой группы — ни одного).
ADGROUP_TYPE_BLOCKS = frozenset(
    {
        "MobileAppAdGroup",
        "DynamicTextAdGroup",
        "DynamicTextFeedAdGroup",
        "CpmBannerKeywordsAdGroup",
        "CpmBannerUserProfileAdGroup",
        "CpmVideoAdGroup",
        "SmartAdGroup",
        "UnifiedAdGroup",
        "TextAdGroupFeedParams",
    }
)

# Поля объявлений для `ads get`: общие и по каждому типу (все значения enum из WSDL).
AD_FIELDS = ["Id", "AdGroupId", "CampaignId", "Type", "Subtype", "State", "Status", "StatusClarification", "AgeLabel"]
AD_TYPE_FIELDS: dict[str, list[str]] = {
    "TextAdFieldNames": [
        "Title",
        "Title2",
        "Text",
        "Href",
        "FinalUrl",
        "DisplayDomain",
        "DisplayUrlPath",
        "Mobile",
        "AdImageHash",
        "SitelinkSetId",
        "VCardId",
        "TurboPageId",
        "BusinessId",
        "AdExtensions",
        "VideoExtension",
        "AdImageModeration",
        "SitelinksModeration",
        "VCardModeration",
        "DisplayUrlPathModeration",
        "TurboPageModeration",
    ],
    "TextAdPriceExtensionFieldNames": ["Price", "OldPrice", "PriceCurrency", "PriceQualifier"],
    "ResponsiveAdFieldNames": [
        "Titles",
        "Texts",
        "Href",
        "AdImages",
        "VideoExtensions",
        "DisplayDomain",
        "DisplayUrlPath",
        "SitelinkSetId",
        "AdExtensions",
        "PriceExtension",
        "BusinessId",
    ],
    "MobileAppAdFieldNames": ["Title", "Text", "Action", "TrackingUrl", "AdImageHash", "Features"],
    "DynamicTextAdFieldNames": ["Text", "AdImageHash", "SitelinkSetId", "VCardId", "AdExtensions"],
    "TextImageAdFieldNames": ["AdImageHash", "Href", "FinalUrl", "TurboPageId"],
    "TextAdBuilderAdFieldNames": ["Creative", "Href", "FinalUrl", "TurboPageId"],
    "ShoppingAdFieldNames": ["FeedId", "DefaultTexts", "TitleSources", "TextSources", "SitelinkSetId", "BusinessId"],
    "ListingAdFieldNames": ["FeedId", "DefaultTexts", "TitleSources", "TextSources", "SitelinkSetId", "BusinessId"],
}

ADGROUP_FIELDS = [
    "Id",
    "Name",
    "CampaignId",
    "Type",
    "Subtype",
    "Status",
    "ServingStatus",
    "RegionIds",
    "RestrictedRegionIds",
    "NegativeKeywords",
    "NegativeKeywordSharedSetIds",
    "TrackingParams",
]
ADGROUP_TYPE_FIELDS: dict[str, list[str]] = {
    "MobileAppAdGroupFieldNames": ["StoreUrl", "TargetDeviceType", "TargetCarrier", "TargetOperatingSystemVersion"],
    "DynamicTextAdGroupFieldNames": ["DomainUrl", "DomainUrlProcessingStatus", "AutotargetingSettings"],
    "DynamicTextFeedAdGroupFieldNames": ["FeedId", "Source", "SourceType", "AutotargetingSettings"],
    "SmartAdGroupFieldNames": ["FeedId", "AdTitleSource", "AdBodySource"],
    "TextAdGroupFeedParamsFieldNames": ["FeedId", "FeedCategoryIds"],
    "UnifiedAdGroupFieldNames": ["OfferRetargeting"],
}


def _blocks(item: dict, allowed: frozenset[str]) -> list[str]:
    return sorted(allowed & item.keys())


def validate_ads(items: list[dict], *, update: bool = False) -> None:
    """ads.add / ads.update: не пусто, ≤ 1000, AdGroupId (или Id) и ровно один блок типа."""
    if not items:
        raise InvalidArguments("Список объявлений пуст.")
    if len(items) > 1000:
        raise InvalidArguments("ads.add/update — не более 1000 объявлений за вызов.")
    key = "Id" if update else "AdGroupId"
    for i, ad in enumerate(items):
        if not isinstance(ad, dict) or key not in ad:
            raise InvalidArguments(f"ads[{i}]: нет {key}.")
        blocks = _blocks(ad, AD_TYPE_BLOCKS)
        if len(blocks) != 1:
            raise InvalidArguments(
                f"ads[{i}]: нужен ровно один type-specific блок ({', '.join(sorted(AD_TYPE_BLOCKS))}), "
                f"найдено: {', '.join(blocks) or 'ни одного'}."
            )


def validate_adgroups(items: list[dict], *, update: bool = False) -> None:
    """adgroups.add / adgroups.update: не пусто, ≤ 1000, обязательные поля и не больше одного блока типа."""
    if not items:
        raise InvalidArguments("Список групп пуст.")
    if len(items) > 1000:
        raise InvalidArguments("adgroups.add/update — не более 1000 групп за вызов.")
    required = ("Id",) if update else ("Name", "CampaignId", "RegionIds")
    for i, group in enumerate(items):
        if not isinstance(group, dict):
            raise InvalidArguments(f"adgroups[{i}]: ожидается объект.")
        for name in required:
            if name not in group:
                raise InvalidArguments(f"adgroups[{i}]: нет {name}.")
        blocks = _blocks(group, ADGROUP_TYPE_BLOCKS)
        if len(blocks) > 1:
            raise InvalidArguments(f"adgroups[{i}]: не более одного блока типа, найдено: {', '.join(blocks)}.")


def items_from_json(data: Any, key: str) -> list[dict]:
    """Список объектов из JSON: сам список или {"<key>": [...]}."""
    items = data.get(key) if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise InvalidArguments(f'Ожидается непустой список или {{"{key}": [...]}}.')
    return items


def compact(block: dict[str, Any]) -> dict[str, Any]:
    """Убрать незаданные поля (None и пустые списки) — API не принимает null там, где поле необязательно."""
    return {k: v for k, v in block.items() if v is not None and v != []}


def price_extension(
    price: int | None, old_price: int | None, qualifier: str | None, currency: str | None
) -> dict[str, Any] | None:
    """PriceExtension из цен в микроединицах; без цены — None."""
    if price is None:
        return None
    return compact(
        {
            "Price": price,
            "OldPrice": old_price,
            "PriceQualifier": qualifier or "NONE",
            "PriceCurrency": currency or "RUB",
        }
    )


def callout_setting(add: Iterable[int], remove: Iterable[int], set_: Iterable[int]) -> dict[str, Any] | None:
    """CalloutSetting для ads.update: операции ADD/REMOVE/SET над уточнениями."""
    items = [
        *({"AdExtensionId": i, "Operation": "ADD"} for i in add),
        *({"AdExtensionId": i, "Operation": "REMOVE"} for i in remove),
        *({"AdExtensionId": i, "Operation": "SET"} for i in set_),
    ]
    return {"AdExtensions": items} if items else None


def mobile_app_features(pairs: Iterable[str]) -> list[dict[str, str]]:
    """`PRICE=YES` → {"Feature": "PRICE", "Enabled": "YES"}."""
    out = []
    for pair in pairs:
        feature, sep, enabled = pair.partition("=")
        if not sep or enabled.upper() not in ("YES", "NO"):
            raise InvalidArguments(f"--feature ожидает FEATURE=YES|NO, получено {pair!r}.")
        out.append({"Feature": feature.upper(), "Enabled": enabled.upper()})
    return out
