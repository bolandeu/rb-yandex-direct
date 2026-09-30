"""Стратегии показов: сборка BiddingStrategy кампании и пакетной стратегии (Strategies) из опций CLI.

Таблицы ниже — из WSDL Директа (campaigns.xml, strategies.xml): какие типы стратегий допустимы
для типа кампании и площадки (поиск/сети), какие поля у блока стратегии и какие из них обязательны.
Блок называется как тип в CamelCase: WB_MAXIMUM_CLICKS → WbMaximumClicks. Всё, что не покрыто
опциями (AVERAGE_ROI, CustomPeriodBudget, ExplorationBudget, пакетные стратегии кампаний), —
через `campaigns add-json`/`update-json` и `strategies add-json`.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from .errors import InvalidArguments

# Тип кампании в API → ключ блока в CampaignAddItem/CampaignUpdateItem.
CAMPAIGN_BLOCKS = {
    "TEXT_CAMPAIGN": "TextCampaign",
    "UNIFIED_CAMPAIGN": "UnifiedCampaign",
    "DYNAMIC_TEXT_CAMPAIGN": "DynamicTextCampaign",
    "SMART_CAMPAIGN": "SmartCampaign",
    "MOBILE_APP_CAMPAIGN": "MobileAppCampaign",
    "CPM_BANNER_CAMPAIGN": "CpmBannerCampaign",
}

# Допустимые BiddingStrategyType: (поиск, сети) — *CampaignSearch/NetworkStrategyTypeEnum без UNKNOWN.
STRATEGY_TYPES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "TEXT_CAMPAIGN": (
        (
            "AVERAGE_CPC", "AVERAGE_CPA", "PAY_FOR_CONVERSION", "WB_MAXIMUM_CONVERSION_RATE", "HIGHEST_POSITION",
            "IMPRESSIONS_BELOW_SEARCH", "SERVING_OFF", "WB_MAXIMUM_CLICKS", "WEEKLY_CLICK_PACKAGE", "AVERAGE_ROI",
            "AVERAGE_CRR", "PAY_FOR_CONVERSION_CRR", "AVERAGE_CPA_MULTIPLE_GOALS",
            "PAY_FOR_CONVERSION_MULTIPLE_GOALS", "MAX_PROFIT",
        ),
        (
            "AVERAGE_CPC", "AVERAGE_CPA", "PAY_FOR_CONVERSION", "WB_MAXIMUM_CONVERSION_RATE", "MAXIMUM_COVERAGE",
            "NETWORK_DEFAULT", "SERVING_OFF", "WB_MAXIMUM_CLICKS", "WEEKLY_CLICK_PACKAGE", "AVERAGE_ROI",
            "AVERAGE_CRR", "PAY_FOR_CONVERSION_CRR", "AVERAGE_CPA_MULTIPLE_GOALS",
            "PAY_FOR_CONVERSION_MULTIPLE_GOALS", "MAX_PROFIT",
        ),
    ),
    "UNIFIED_CAMPAIGN": (
        (
            "AVERAGE_CPC", "AVERAGE_CPA", "PAY_FOR_CONVERSION", "WB_MAXIMUM_CONVERSION_RATE", "HIGHEST_POSITION",
            "SERVING_OFF", "WB_MAXIMUM_CLICKS", "AVERAGE_CRR", "PAY_FOR_CONVERSION_CRR",
            "AVERAGE_CPA_MULTIPLE_GOALS", "PAY_FOR_CONVERSION_MULTIPLE_GOALS", "MAX_PROFIT",
        ),
        (
            "AVERAGE_CPC", "AVERAGE_CPA", "PAY_FOR_CONVERSION", "WB_MAXIMUM_CONVERSION_RATE", "NETWORK_DEFAULT",
            "SERVING_OFF", "WB_MAXIMUM_CLICKS", "AVERAGE_CRR", "PAY_FOR_CONVERSION_CRR",
            "AVERAGE_CPA_MULTIPLE_GOALS", "PAY_FOR_CONVERSION_MULTIPLE_GOALS", "MAX_PROFIT",
        ),
    ),
    "DYNAMIC_TEXT_CAMPAIGN": (
        (
            "AVERAGE_CPC", "AVERAGE_CPA", "PAY_FOR_CONVERSION", "WB_MAXIMUM_CONVERSION_RATE", "HIGHEST_POSITION",
            "IMPRESSIONS_BELOW_SEARCH", "WB_MAXIMUM_CLICKS", "WEEKLY_CLICK_PACKAGE", "AVERAGE_ROI", "AVERAGE_CRR",
            "PAY_FOR_CONVERSION_CRR", "SERVING_OFF",
        ),
        (
            "NETWORK_DEFAULT", "MAXIMUM_COVERAGE", "WB_MAXIMUM_CONVERSION_RATE", "WB_MAXIMUM_CLICKS", "AVERAGE_CPC",
            "AVERAGE_CPA", "PAY_FOR_CONVERSION", "AVERAGE_ROI", "AVERAGE_CRR", "PAY_FOR_CONVERSION_CRR",
            "WEEKLY_CLICK_PACKAGE", "SERVING_OFF",
        ),
    ),
    "SMART_CAMPAIGN": (
        (
            "AVERAGE_CPC_PER_CAMPAIGN", "AVERAGE_CPC_PER_FILTER", "AVERAGE_CPA_PER_CAMPAIGN",
            "AVERAGE_CPA_PER_FILTER", "PAY_FOR_CONVERSION_PER_CAMPAIGN", "PAY_FOR_CONVERSION_PER_FILTER",
            "AVERAGE_ROI", "AVERAGE_CRR", "PAY_FOR_CONVERSION_CRR", "SERVING_OFF",
        ),
        (
            "NETWORK_DEFAULT", "AVERAGE_CPC_PER_CAMPAIGN", "AVERAGE_CPC_PER_FILTER", "AVERAGE_CPA_PER_CAMPAIGN",
            "AVERAGE_CPA_PER_FILTER", "PAY_FOR_CONVERSION_PER_CAMPAIGN", "PAY_FOR_CONVERSION_PER_FILTER",
            "AVERAGE_ROI", "AVERAGE_CRR", "PAY_FOR_CONVERSION_CRR", "SERVING_OFF",
        ),
    ),
    "MOBILE_APP_CAMPAIGN": (
        (
            "AVERAGE_CPC", "AVERAGE_CPI", "WB_MAXIMUM_APP_INSTALLS", "HIGHEST_POSITION", "IMPRESSIONS_BELOW_SEARCH",
            "SERVING_OFF", "WB_MAXIMUM_CLICKS", "WEEKLY_CLICK_PACKAGE", "PAY_FOR_INSTALL",
        ),
        (
            "NETWORK_DEFAULT", "MAXIMUM_COVERAGE", "AVERAGE_CPC", "AVERAGE_CPI", "WB_MAXIMUM_APP_INSTALLS",
            "SERVING_OFF", "WB_MAXIMUM_CLICKS", "WEEKLY_CLICK_PACKAGE", "PAY_FOR_INSTALL",
        ),
    ),
    "CPM_BANNER_CAMPAIGN": (
        ("SERVING_OFF",),
        (
            "MANUAL_CPM", "WB_DECREASED_PRICE_FOR_REPEATED_IMPRESSIONS", "CP_DECREASED_PRICE_FOR_REPEATED_IMPRESSIONS",
            "WB_MAXIMUM_IMPRESSIONS", "CP_MAXIMUM_IMPRESSIONS", "WB_AVERAGE_CPV", "CP_AVERAGE_CPV",
        ),
    ),
}  # fmt: skip

# Блоки параметров стратегии, которые есть у типа кампании (*CampaignStrategyAddBase);
# NetworkDefault — только на площадке «сети».
_TEXT_BLOCKS = {
    "WbMaximumClicks", "WbMaximumConversionRate", "AverageCpc", "AverageCpa", "PayForConversion",
    "WeeklyClickPackage", "AverageRoi", "AverageCrr", "PayForConversionCrr", "AverageCpaMultipleGoals",
    "PayForConversionMultipleGoals", "MaxProfit",
}  # fmt: skip
CAMPAIGN_TYPE_BLOCKS: dict[str, set[str]] = {
    "TEXT_CAMPAIGN": _TEXT_BLOCKS | {"NetworkDefault"},
    "UNIFIED_CAMPAIGN": (_TEXT_BLOCKS - {"WeeklyClickPackage", "AverageRoi"}) | {"HighestPosition"},
    "DYNAMIC_TEXT_CAMPAIGN": {
        "WbMaximumClicks", "WbMaximumConversionRate", "AverageCpc", "AverageCpa", "PayForConversion",
        "WeeklyClickPackage", "AverageRoi", "AverageCrr", "PayForConversionCrr", "NetworkDefault",
    },
    "SMART_CAMPAIGN": {
        "AverageCpcPerCampaign", "AverageCpcPerFilter", "AverageCpaPerCampaign", "PayForConversionPerCampaign",
        "PayForConversionPerFilter", "AverageCpaPerFilter", "AverageRoi", "AverageCrr", "PayForConversionCrr",
        "NetworkDefault",
    },
    "MOBILE_APP_CAMPAIGN": {
        "HighestPosition", "WbMaximumClicks", "WbMaximumAppInstalls", "AverageCpc", "AverageCpi",
        "WeeklyClickPackage", "PayForInstall", "NetworkDefault",
    },
    "CPM_BANNER_CAMPAIGN": {
        "ManualCpm", "WbMaximumImpressions", "CpMaximumImpressions", "WbDecreasedPriceForRepeatedImpressions",
        "CpDecreasedPriceForRepeatedImpressions", "WbAverageCpv", "CpAverageCpv",
    },
}  # fmt: skip

# Поля блока стратегии кампании (Strategy*Add) → обязательные при создании.
CAMPAIGN_BLOCK_FIELDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "WbMaximumClicks": (("WeeklySpendLimit", "BidCeiling"), ("WeeklySpendLimit",)),
    "WbMaximumConversionRate": (("WeeklySpendLimit", "BidCeiling", "GoalId"), ("WeeklySpendLimit", "GoalId")),
    "WbMaximumAppInstalls": (("WeeklySpendLimit", "BidCeiling"), ("WeeklySpendLimit",)),
    "AverageCpc": (("AverageCpc", "WeeklySpendLimit"), ("AverageCpc",)),
    "AverageCpa": (("AverageCpa", "GoalId", "WeeklySpendLimit", "BidCeiling"), ("AverageCpa", "GoalId")),
    "PayForConversion": (("Cpa", "GoalId", "WeeklySpendLimit"), ("Cpa", "GoalId")),
    "AverageCpi": (("AverageCpi", "WeeklySpendLimit", "BidCeiling"), ("AverageCpi",)),
    "PayForInstall": (("AverageCpi", "WeeklySpendLimit"), ("AverageCpi",)),
    "AverageCpaPerCampaign": (("AverageCpa", "GoalId", "WeeklySpendLimit", "BidCeiling"), ("AverageCpa", "GoalId")),
    "PayForConversionPerCampaign": (("Cpa", "GoalId", "WeeklySpendLimit"), ("Cpa", "GoalId")),
    "PayForConversionPerFilter": (("Cpa", "GoalId", "WeeklySpendLimit"), ("Cpa", "GoalId")),
    "AverageCpaPerFilter": (
        ("FilterAverageCpa", "GoalId", "WeeklySpendLimit", "BidCeiling"), ("FilterAverageCpa", "GoalId"),
    ),
    "AverageCpcPerCampaign": (("AverageCpc", "WeeklySpendLimit", "BidCeiling"), ("AverageCpc",)),
    "AverageCpcPerFilter": (("FilterAverageCpc", "WeeklySpendLimit", "BidCeiling"), ()),
    "AverageCrr": (("Crr", "GoalId", "WeeklySpendLimit"), ("Crr", "GoalId")),
    "PayForConversionCrr": (("Crr", "GoalId", "WeeklySpendLimit"), ("Crr", "GoalId")),
    "WeeklyClickPackage": (("ClicksPerWeek", "AverageCpc", "BidCeiling"), ("ClicksPerWeek",)),
    "MaxProfit": (("WeeklySpendLimit",), ()),
    "AverageCpaMultipleGoals": (("WeeklySpendLimit", "BidCeiling"), ()),
    "PayForConversionMultipleGoals": (("WeeklySpendLimit",), ()),
    "NetworkDefault": (("LimitPercent",), ()),
    "HighestPosition": (("WeeklySpendLimit",), ()),
    "ManualCpm": (("WeeklySpendLimit",), ()),
    "WbMaximumImpressions": (("AverageCpm", "SpendLimit"), ("AverageCpm", "SpendLimit")),
    "WbDecreasedPriceForRepeatedImpressions": (("AverageCpm", "SpendLimit"), ("AverageCpm", "SpendLimit")),
    "WbAverageCpv": (("AverageCpv", "SpendLimit"), ("AverageCpv", "SpendLimit")),
}  # fmt: skip

# Блоки, которые опциями не собрать (нужны CustomPeriodBudget, ROI-коэффициенты): только через JSON.
JSON_ONLY_BLOCKS = {
    "AverageRoi", "CpMaximumImpressions", "CpDecreasedPriceForRepeatedImpressions", "CpAverageCpv",
}  # fmt: skip

# Пакетные стратегии (StrategyAddItem): тип задаётся самим блоком, поля — Strategy*AddItem.
PACKAGE_STRATEGY_FIELDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "WB_MAXIMUM_CLICKS": (("WeeklySpendLimit", "BidCeiling"), ()),
    "WB_MAXIMUM_CONVERSION_RATE": (("WeeklySpendLimit", "BidCeiling", "GoalId"), ("GoalId",)),
    "AVERAGE_CPC": (("AverageCpc", "WeeklySpendLimit"), ("AverageCpc",)),
    "AVERAGE_CPA": (("AverageCpa", "GoalId", "WeeklySpendLimit", "BidCeiling"), ("AverageCpa", "GoalId")),
    "MAX_PROFIT": (("WeeklySpendLimit",), ()),
    "PAY_FOR_CONVERSION": (("Cpa", "GoalId", "WeeklySpendLimit"), ("Cpa", "GoalId")),
    "AVERAGE_CPA_PER_CAMPAIGN": (("AverageCpa", "GoalId", "WeeklySpendLimit", "BidCeiling"), ("AverageCpa", "GoalId")),
    "PAY_FOR_CONVERSION_PER_CAMPAIGN": (("Cpa", "GoalId", "WeeklySpendLimit"), ("Cpa", "GoalId")),
    "PAY_FOR_CONVERSION_PER_FILTER": (("Cpa", "GoalId", "WeeklySpendLimit"), ("Cpa", "GoalId")),
    "AVERAGE_CPA_PER_FILTER": (
        ("FilterAverageCpa", "GoalId", "WeeklySpendLimit", "BidCeiling"), ("FilterAverageCpa", "GoalId"),
    ),
    "AVERAGE_CPC_PER_CAMPAIGN": (("AverageCpc", "WeeklySpendLimit", "BidCeiling"), ("AverageCpc",)),
    "AVERAGE_CPC_PER_FILTER": (("FilterAverageCpc", "WeeklySpendLimit", "BidCeiling"), ()),
    "AVERAGE_CRR": (("Crr", "GoalId", "WeeklySpendLimit"), ("Crr", "GoalId")),
    "PAY_FOR_CONVERSION_CRR": (("Crr", "GoalId", "WeeklySpendLimit"), ("Crr", "GoalId")),
    "AVERAGE_CPA_MULTIPLE_GOALS": (("WeeklySpendLimit", "BidCeiling"), ()),
    "PAY_FOR_CONVERSION_MULTIPLE_GOALS": (("GoalId", "WeeklySpendLimit"), ("GoalId",)),
}  # fmt: skip
PACKAGE_STRATEGY_TYPES = tuple(PACKAGE_STRATEGY_FIELDS)

# strategies.get: общие поля и поля каждого блока (Strategy*FieldEnum из WSDL).
_BUDGET = ["WeeklySpendLimit", "CustomPeriodBudget", "BudgetType"]
PACKAGE_STRATEGY_GET_FIELDS: dict[str, Any] = {
    "FieldNames": ["Id", "AttributionModel", "CounterIds", "PriorityGoals", "Type", "Name", "StatusArchived"],
    "StrategyMaximumClicksFieldNames": [*_BUDGET, "BidCeiling"],
    "StrategyMaximumConversionRateFieldNames": [*_BUDGET, "BidCeiling", "GoalId"],
    "StrategyAverageCpcFieldNames": ["AverageCpc", *_BUDGET],
    "StrategyAverageCpaFieldNames": ["AverageCpa", "GoalId", *_BUDGET, "BidCeiling", "ExplorationBudget"],
    "StrategyMaxProfitFieldNames": [*_BUDGET, "ExplorationBudget"],
    "StrategyPayForConversionFieldNames": ["Cpa", "GoalId", *_BUDGET],
    "StrategyAverageCpaPerCampaignFieldNames": ["AverageCpa", "GoalId", *_BUDGET, "BidCeiling", "ExplorationBudget"],
    "StrategyPayForConversionPerCampaignFieldNames": ["Cpa", "GoalId", *_BUDGET],
    "StrategyPayForConversionPerFilterFieldNames": ["Cpa", "GoalId", *_BUDGET],
    "StrategyAverageCpaPerFilterFieldNames": [
        "FilterAverageCpa", "GoalId", *_BUDGET, "BidCeiling", "ExplorationBudget",
    ],
    "StrategyAverageCpcPerCampaignFieldNames": ["AverageCpc", *_BUDGET, "BidCeiling"],
    "StrategyAverageCpcPerFilterFieldNames": ["FilterAverageCpc", *_BUDGET, "BidCeiling"],
    "StrategyAverageCrrFieldNames": ["Crr", "GoalId", *_BUDGET, "ExplorationBudget"],
    "StrategyPayForConversionCrrFieldNames": ["Crr", "GoalId", *_BUDGET],
    "StrategyAverageCpaMultipleGoalsFieldNames": [*_BUDGET, "ExplorationBudget", "BidCeiling"],
    "StrategyPayForConversionMultipleGoalsFieldNames": _BUDGET,
}  # fmt: skip

MULTIPLE_GOALS = {"AVERAGE_CPA_MULTIPLE_GOALS", "PAY_FOR_CONVERSION_MULTIPLE_GOALS"}
ATTRIBUTION_MODELS = ("LC", "LSC", "FC", "LYDC", "LSCCD", "FCCD", "LYDCCD", "AUTO")


@dataclass
class StrategyParams:
    """Параметры стратегии из опций CLI; деньги — в рублях, в запрос уходят микроединицы."""

    weekly_budget: float | None = None
    bid_ceiling: float | None = None
    average_cpc: float | None = None
    average_cpa: float | None = None
    cpa: float | None = None
    average_cpi: float | None = None
    average_cpm: float | None = None
    average_cpv: float | None = None
    spend_limit: float | None = None
    goal_id: int | None = None
    crr: int | None = None
    clicks_per_week: int | None = None
    limit_percent: int | None = None

    def given(self) -> set[str]:
        return {f.name for f in fields(self) if getattr(self, f.name) is not None}


# Поле API → (атрибут StrategyParams, деньги ли это: рубли → микроединицы).
_FIELD_SOURCES: dict[str, tuple[str, bool]] = {
    "WeeklySpendLimit": ("weekly_budget", True),
    "BidCeiling": ("bid_ceiling", True),
    "AverageCpc": ("average_cpc", True),
    "FilterAverageCpc": ("average_cpc", True),
    "AverageCpa": ("average_cpa", True),
    "FilterAverageCpa": ("average_cpa", True),
    "Cpa": ("cpa", True),
    "AverageCpi": ("average_cpi", True),
    "AverageCpm": ("average_cpm", True),
    "AverageCpv": ("average_cpv", True),
    "SpendLimit": ("spend_limit", True),
    "GoalId": ("goal_id", False),
    "Crr": ("crr", False),
    "ClicksPerWeek": ("clicks_per_week", False),
    "LimitPercent": ("limit_percent", False),
}


def option_name(attr: str) -> str:
    return "--" + attr.replace("_", "-")


def block_name(strategy_type: str) -> str:
    """WB_MAXIMUM_CLICKS → WbMaximumClicks: так в API называется блок параметров стратегии."""
    return "".join(part.capitalize() for part in strategy_type.split("_"))


def _fill(field_names: tuple[str, ...], params: StrategyParams) -> tuple[dict[str, Any], set[str]]:
    block: dict[str, Any] = {}
    used: set[str] = set()
    for field in field_names:
        attr, money = _FIELD_SOURCES[field]
        value = getattr(params, attr)
        if value is None:
            continue
        block[field] = round(value * 1_000_000) if money else value
        used.add(attr)
    return block, used


def _missing(block: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    return [option_name(_FIELD_SOURCES[f][0]) for f in required if f not in block]


def bidding_strategy(
    campaign_type: str,
    search: str | None,
    network: str | None,
    params: StrategyParams,
    *,
    placement_types: dict[str, str] | None = None,
    update: bool = False,
) -> dict[str, Any]:
    """BiddingStrategy для блока типа кампании: {"Search": {...}, "Network": {...}}.

    Параметры (`--weekly-budget`, `--goal-id`, …) попадают в блок той площадки, чья стратегия
    их принимает; параметр, который не принял никто, — ошибка, а не молчаливый пропуск.
    При `update` стороны без типа не передаются, обязательные поля не проверяются.
    """
    search_types, network_types = STRATEGY_TYPES[campaign_type]
    allowed_blocks = CAMPAIGN_TYPE_BLOCKS[campaign_type]
    result: dict[str, Any] = {}
    used: set[str] = set()
    for side, value, choices in (("Search", search, search_types), ("Network", network, network_types)):
        if value is None:
            continue
        value = value.upper()
        if value not in choices:
            raise InvalidArguments(
                f"Стратегия {value} недоступна на {'поиске' if side == 'Search' else 'в сетях'} "
                f"для {campaign_type}. Варианты: {', '.join(choices)}."
            )
        side_block: dict[str, Any] = {"BiddingStrategyType": value}
        name = block_name(value)
        if name in JSON_ONLY_BLOCKS:
            raise InvalidArguments(f"Стратегию {value} опциями не задать — используйте add-json/update-json.")
        if name in allowed_blocks and (name != "NetworkDefault" or side == "Network"):
            field_names, required = CAMPAIGN_BLOCK_FIELDS[name]
            block, block_used = _fill(field_names, params)
            missing = [] if update else _missing(block, required)
            if missing:
                raise InvalidArguments(f"Для стратегии {value} нужны: {', '.join(missing)}.")
            if block or not update:
                side_block[name] = block
            used |= block_used
        result[side] = side_block
    if placement_types and "Search" in result:
        result["Search"]["PlacementTypes"] = placement_types
    unused = params.given() - used
    if unused:
        names = ", ".join(sorted(option_name(a) for a in unused))
        raise InvalidArguments(f"{names}: не подходит к выбранным стратегиям ({search or '—'} / {network or '—'}).")
    return result


def package_strategy_block(strategy_type: str, params: StrategyParams, *, update: bool = False) -> dict[str, Any]:
    """Блок пакетной стратегии (Strategies.add/update): {"<Блок>": {...}} по типу."""
    strategy_type = strategy_type.upper()
    if strategy_type not in PACKAGE_STRATEGY_FIELDS:
        raise InvalidArguments(
            f"Тип пакетной стратегии {strategy_type}? Варианты: {', '.join(PACKAGE_STRATEGY_TYPES)}."
        )
    field_names, required = PACKAGE_STRATEGY_FIELDS[strategy_type]
    block, used = _fill(field_names, params)
    missing = [] if update else _missing(block, required)
    if missing:
        raise InvalidArguments(f"Для стратегии {strategy_type} нужны: {', '.join(missing)}.")
    unused = params.given() - used
    if unused:
        names = ", ".join(sorted(option_name(a) for a in unused))
        raise InvalidArguments(f"{names}: не подходит к стратегии {strategy_type}.")
    return {block_name(strategy_type): block}


def priority_goals(items: list[str] | None) -> dict[str, Any] | None:
    """`GOAL_ID=ЦЕННОСТЬ_₽` (повторяемая) → PriorityGoals {"Items": [{GoalId, Value}]}."""
    if not items:
        return None
    out = []
    for raw in items:
        goal, sep, value = raw.partition("=")
        try:
            out.append({"GoalId": int(goal), "Value": round(float(value) * 1_000_000) if sep else 0})
        except ValueError as exc:
            raise InvalidArguments(f"--priority-goal ожидает ЦЕЛЬ=ЦЕННОСТЬ_₽, получено {raw!r}.") from exc
    return {"Items": out}


def yes_no_pairs(items: list[str] | None, allowed: tuple[str, ...], option: str) -> list[tuple[str, str]]:
    """`ИМЯ=YES|NO` (повторяемая) → [(ИМЯ, YES|NO)] с проверкой имени по списку API."""
    out = []
    for raw in items or []:
        key, _, value = raw.partition("=")
        key, value = key.strip().upper(), (value.strip().upper() or "YES")
        if key not in allowed:
            raise InvalidArguments(f"{option} {key}: неизвестно. Варианты: {', '.join(allowed)}.")
        if value not in ("YES", "NO"):
            raise InvalidArguments(f"{option} {key}={value}: значение YES или NO.")
        out.append((key, value))
    return out
