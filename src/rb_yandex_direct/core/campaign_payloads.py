"""Сборка CampaignAddItem из опций `campaigns add <тип>` (перечни — из WSDL campaigns.xml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .errors import InvalidArguments
from .strategy import (
    ATTRIBUTION_MODELS,
    CAMPAIGN_BLOCKS,
    MULTIPLE_GOALS,
    StrategyParams,
    bidding_strategy,
    priority_goals,
    yes_no_pairs,
)

# Короткие имена типов в CLI → тип кампании API.
CAMPAIGN_TYPES = {
    "text": "TEXT_CAMPAIGN",
    "unified": "UNIFIED_CAMPAIGN",
    "dynamic": "DYNAMIC_TEXT_CAMPAIGN",
    "smart": "SMART_CAMPAIGN",
    "mobile-app": "MOBILE_APP_CAMPAIGN",
    "cpm-banner": "CPM_BANNER_CAMPAIGN",
}

# *CampaignSettingsEnum.
SETTINGS: dict[str, tuple[str, ...]] = {
    "TEXT_CAMPAIGN": (
        "EXCLUDE_PAUSED_COMPETING_ADS", "ADD_OPENSTAT_TAG", "ADD_METRICA_TAG", "ADD_TO_FAVORITES",
        "ENABLE_AREA_OF_INTEREST_TARGETING", "ENABLE_CURRENT_AREA_TARGETING", "ENABLE_REGULAR_AREA_TARGETING",
        "ENABLE_SITE_MONITORING", "ENABLE_BEHAVIORAL_TARGETING", "ENABLE_AUTOFOCUS", "REQUIRE_SERVICING",
        "ENABLE_RELATED_KEYWORDS", "ENABLE_EXTENDED_AD_TITLE", "MAINTAIN_NETWORK_CPC", "ENABLE_COMPANY_INFO",
        "CAMPAIGN_EXACT_PHRASE_MATCHING_ENABLED", "ALTERNATIVE_TEXTS_ENABLED",
    ),
    "UNIFIED_CAMPAIGN": (
        "ADD_METRICA_TAG", "ADD_TO_FAVORITES", "ENABLE_AREA_OF_INTEREST_TARGETING", "ENABLE_SITE_MONITORING",
        "REQUIRE_SERVICING", "ENABLE_COMPANY_INFO", "CAMPAIGN_EXACT_PHRASE_MATCHING_ENABLED",
        "ALTERNATIVE_TEXTS_ENABLED",
    ),
    "MOBILE_APP_CAMPAIGN": (
        "ADD_TO_FAVORITES", "ENABLE_AREA_OF_INTEREST_TARGETING", "ENABLE_CURRENT_AREA_TARGETING",
        "ENABLE_REGULAR_AREA_TARGETING", "ENABLE_BEHAVIORAL_TARGETING", "ENABLE_AUTOFOCUS", "REQUIRE_SERVICING",
        "MAINTAIN_NETWORK_CPC", "CAMPAIGN_EXACT_PHRASE_MATCHING_ENABLED",
    ),
    "DYNAMIC_TEXT_CAMPAIGN": (
        "ADD_OPENSTAT_TAG", "ADD_METRICA_TAG", "ADD_TO_FAVORITES", "ENABLE_AREA_OF_INTEREST_TARGETING",
        "ENABLE_CURRENT_AREA_TARGETING", "ENABLE_REGULAR_AREA_TARGETING", "ENABLE_SITE_MONITORING",
        "ENABLE_BEHAVIORAL_TARGETING", "REQUIRE_SERVICING", "ENABLE_EXTENDED_AD_TITLE", "ENABLE_COMPANY_INFO",
        "CAMPAIGN_EXACT_PHRASE_MATCHING_ENABLED",
    ),
    "CPM_BANNER_CAMPAIGN": (
        "ADD_OPENSTAT_TAG", "ADD_METRICA_TAG", "ADD_TO_FAVORITES", "ENABLE_AREA_OF_INTEREST_TARGETING",
        "ENABLE_CURRENT_AREA_TARGETING", "ENABLE_REGULAR_AREA_TARGETING", "ENABLE_SITE_MONITORING",
        "REQUIRE_SERVICING",
    ),
    "SMART_CAMPAIGN": (
        "ADD_TO_FAVORITES", "ENABLE_AREA_OF_INTEREST_TARGETING", "ENABLE_CURRENT_AREA_TARGETING",
        "ENABLE_REGULAR_AREA_TARGETING", "REQUIRE_SERVICING",
    ),
}  # fmt: skip

# Площадки поиска (*SearchStrategyPlacementTypes).
PLACEMENTS: dict[str, tuple[str, ...]] = {
    "TEXT_CAMPAIGN": ("SearchResults", "ProductGallery", "DynamicPlaces"),
    "DYNAMIC_TEXT_CAMPAIGN": ("SearchResults", "ProductGallery", "DynamicPlaces"),
    "UNIFIED_CAMPAIGN": ("SearchResults", "ProductGallery", "DynamicPlaces", "Maps", "SearchOrganizationList"),
}

# Стратегия по умолчанию (поиск, сети): ручное управление ставками без показов в сетях.
DEFAULT_STRATEGY = {
    "TEXT_CAMPAIGN": ("HIGHEST_POSITION", "SERVING_OFF"),
    "UNIFIED_CAMPAIGN": ("HIGHEST_POSITION", "SERVING_OFF"),
    "DYNAMIC_TEXT_CAMPAIGN": ("HIGHEST_POSITION", "SERVING_OFF"),
    "MOBILE_APP_CAMPAIGN": ("HIGHEST_POSITION", "SERVING_OFF"),
    "SMART_CAMPAIGN": (None, None),
    "CPM_BANNER_CAMPAIGN": ("SERVING_OFF", None),
}

VIDEO_TARGETS = ("CLICKS", "VIEWS")


@dataclass
class CampaignSpec:
    """Всё, что `campaigns add` собирает из опций (деньги — в рублях)."""

    name: str
    start_date: str | None = None
    end_date: str | None = None
    daily_budget: float | None = None
    budget_mode: str = "STANDARD"
    negative_keywords: list[str] = field(default_factory=list)
    blocked_ips: list[str] = field(default_factory=list)
    excluded_sites: list[str] = field(default_factory=list)
    time_zone: str | None = None
    client_info: str | None = None
    search_strategy: str | None = None
    network_strategy: str | None = None
    strategy: StrategyParams = field(default_factory=StrategyParams)
    placements: list[str] = field(default_factory=list)
    settings: list[str] = field(default_factory=list)
    counter_ids: list[int] = field(default_factory=list)
    priority_goals: list[str] = field(default_factory=list)
    tracking_params: str | None = None
    attribution_model: str | None = None
    frequency_cap: str | None = None
    video_target: str | None = None


def campaign_add_item(campaign_type: str, spec: CampaignSpec) -> dict[str, Any]:
    """CampaignAddItem для типа кампании API (TEXT_CAMPAIGN, …) с проверкой опций по WSDL."""
    item: dict[str, Any] = {"Name": spec.name, "StartDate": spec.start_date or date.today().isoformat()}
    if spec.end_date:
        item["EndDate"] = spec.end_date
    if spec.daily_budget is not None:
        item["DailyBudget"] = {"Amount": round(spec.daily_budget * 1_000_000), "Mode": spec.budget_mode}
    for key, values in (
        ("NegativeKeywords", spec.negative_keywords),
        ("BlockedIps", spec.blocked_ips),
        ("ExcludedSites", spec.excluded_sites),
    ):
        if values:
            item[key] = {"Items": values}
    if spec.time_zone:
        item["TimeZone"] = spec.time_zone
    if spec.client_info:
        item["ClientInfo"] = spec.client_info

    default_search, default_network = DEFAULT_STRATEGY[campaign_type]
    search = spec.search_strategy or default_search
    network = spec.network_strategy or default_network
    if search is None or network is None:
        raise InvalidArguments(
            f"Для {campaign_type} задайте стратегию явно: --search-strategy и --network-strategy "
            "(ручной стратегии у этого типа нет)."
        )
    placements = yes_no_pairs(spec.placements, PLACEMENTS.get(campaign_type, ()), "--placement")
    block: dict[str, Any] = {
        "BiddingStrategy": bidding_strategy(
            campaign_type,
            search,
            network,
            spec.strategy,
            placement_types=dict(placements) if placements else None,
        )
    }
    settings = yes_no_pairs(spec.settings, SETTINGS[campaign_type], "--setting")
    if settings:
        block["Settings"] = [{"Option": k, "Value": v} for k, v in settings]

    _type_specific(campaign_type, block, spec, {search.upper(), network.upper()})
    item[CAMPAIGN_BLOCKS[campaign_type]] = block
    return item


def _type_specific(campaign_type: str, block: dict[str, Any], spec: CampaignSpec, strategies: set[str]) -> None:
    rejected: list[str] = []
    goals = priority_goals(spec.priority_goals)
    if strategies & MULTIPLE_GOALS and not goals:
        raise InvalidArguments("Стратегии *_MULTIPLE_GOALS нужны цели: --priority-goal ЦЕЛЬ=ЦЕННОСТЬ_₽.")

    if campaign_type == "SMART_CAMPAIGN":
        if len(spec.counter_ids) != 1:
            raise InvalidArguments("Смарт-баннерам нужен ровно один счётчик Метрики: --counter-id.")
        block["CounterId"] = spec.counter_ids[0]
    elif spec.counter_ids:
        if campaign_type == "MOBILE_APP_CAMPAIGN":
            rejected.append("--counter-id")
        else:
            block["CounterIds"] = {"Items": spec.counter_ids}

    with_goals = campaign_type in ("TEXT_CAMPAIGN", "UNIFIED_CAMPAIGN", "DYNAMIC_TEXT_CAMPAIGN", "SMART_CAMPAIGN")
    for option, value, key in (
        ("--priority-goal", goals, "PriorityGoals"),
        ("--tracking-params", spec.tracking_params, "TrackingParams"),
        ("--attribution-model", spec.attribution_model and spec.attribution_model.upper(), "AttributionModel"),
    ):
        if not value:
            continue
        if with_goals:
            block[key] = value
        else:
            rejected.append(option)
    if block.get("AttributionModel") and block["AttributionModel"] not in ATTRIBUTION_MODELS:
        raise InvalidArguments(f"--attribution-model: один из {', '.join(ATTRIBUTION_MODELS)}.")

    if spec.frequency_cap:
        if campaign_type != "CPM_BANNER_CAMPAIGN":
            rejected.append("--frequency-cap")
        else:
            impressions, _, days = spec.frequency_cap.partition("/")
            try:
                block["FrequencyCap"] = {"Impressions": int(impressions), "PeriodDays": int(days)}
            except ValueError as exc:
                raise InvalidArguments("--frequency-cap ожидает ПОКАЗЫ/ДНИ, например 3/7.") from exc
    if spec.video_target:
        if campaign_type != "CPM_BANNER_CAMPAIGN":
            rejected.append("--video-target")
        elif spec.video_target.upper() not in VIDEO_TARGETS:
            raise InvalidArguments(f"--video-target: один из {', '.join(VIDEO_TARGETS)}.")
        else:
            block["VideoTarget"] = spec.video_target.upper()
    if spec.placements and campaign_type not in PLACEMENTS:
        rejected.append("--placement")
    if rejected:
        raise InvalidArguments(f"{', '.join(rejected)}: не применимо к {campaign_type}.")
