"""ReportDefinition сервиса Reports из опций CLI: период, фильтры, сортировка, цели, атрибуция."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import InvalidArguments
from .strategy import ATTRIBUTION_MODELS

REPORT_TYPES = (
    "ACCOUNT_PERFORMANCE_REPORT",
    "CAMPAIGN_PERFORMANCE_REPORT",
    "ADGROUP_PERFORMANCE_REPORT",
    "AD_PERFORMANCE_REPORT",
    "CRITERIA_PERFORMANCE_REPORT",
    "CUSTOM_REPORT",
    "REACH_AND_FREQUENCY_PERFORMANCE_REPORT",
    "SEARCH_QUERY_PERFORMANCE_REPORT",
)
DATE_RANGE_TYPES = (
    "CUSTOM_DATE", "TODAY", "YESTERDAY", "LAST_3_DAYS", "LAST_5_DAYS", "LAST_7_DAYS", "LAST_14_DAYS",
    "LAST_30_DAYS", "LAST_90_DAYS", "LAST_365_DAYS", "THIS_WEEK_MON_TODAY", "THIS_WEEK_SUN_TODAY", "LAST_WEEK",
    "LAST_BUSINESS_WEEK", "LAST_WEEK_SUN_SAT", "THIS_MONTH", "LAST_MONTH", "ALL_TIME", "AUTO",
)  # fmt: skip
FILTER_OPERATORS = (
    "EQUALS", "NOT_EQUALS", "IN", "NOT_IN", "LESS_THAN", "GREATER_THAN", "STARTS_WITH_IGNORE_CASE",
    "DOES_NOT_START_WITH_IGNORE_CASE", "STARTS_WITH_ANY_IGNORE_CASE", "DOES_NOT_START_WITH_ALL_IGNORE_CASE",
)  # fmt: skip
PROCESSING_MODES = ("auto", "online", "offline")


@dataclass
class ReportSpec:
    report_type: str
    fields: list[str]
    date_from: str | None = None
    date_to: str | None = None
    date_range: str | None = None
    campaign_ids: list[int] = field(default_factory=list)
    adgroup_ids: list[int] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    order_by: list[str] = field(default_factory=list)
    goals: list[int] = field(default_factory=list)
    attribution_models: list[str] = field(default_factory=list)
    include_vat: bool = True
    include_discount: bool = True
    limit: int | None = None
    name: str | None = None


def _filter(raw: str) -> dict[str, Any]:
    """`Поле:ОПЕРАТОР:знач1,знач2` → элемент Filter."""
    parts = raw.split(":", 2)
    if len(parts) != 3 or not all(p.strip() for p in parts):
        raise InvalidArguments(f"--filter ожидает Поле:ОПЕРАТОР:значения, получено {raw!r}.")
    name, operator, values = (p.strip() for p in parts)
    operator = operator.upper()
    if operator not in FILTER_OPERATORS:
        raise InvalidArguments(f"--filter {raw!r}: оператор один из {', '.join(FILTER_OPERATORS)}.")
    return {"Field": name, "Operator": operator, "Values": [v.strip() for v in values.split(",") if v.strip()]}


def _order(raw: str) -> dict[str, str]:
    """`Поле[:ASC|DESC]` → элемент OrderBy."""
    name, _, order = raw.partition(":")
    item = {"Field": name.strip()}
    if order:
        order = {"ASC": "ASCENDING", "DESC": "DESCENDING"}.get(order.strip().upper(), order.strip().upper())
        if order not in ("ASCENDING", "DESCENDING"):
            raise InvalidArguments(f"--order-by {raw!r}: порядок ASC или DESC.")
        item["SortOrder"] = order
    return item


def report_params(spec: ReportSpec) -> dict[str, Any]:
    """ReportDefinition без ReportName (его даёт provider по хэшу параметров, если не задан)."""
    report_type = spec.report_type.upper()
    if report_type not in REPORT_TYPES:
        raise InvalidArguments(f"Тип отчёта {report_type}? Варианты: {', '.join(REPORT_TYPES)}.")
    if not spec.fields:
        raise InvalidArguments("Нужно хотя бы одно поле отчёта (--field).")
    date_range = (spec.date_range or ("CUSTOM_DATE" if spec.date_from or spec.date_to else "LAST_30_DAYS")).upper()
    if date_range not in DATE_RANGE_TYPES:
        raise InvalidArguments(f"--range: один из {', '.join(DATE_RANGE_TYPES)}.")
    criteria: dict[str, Any] = {}
    if date_range == "CUSTOM_DATE":
        if not (spec.date_from and spec.date_to):
            raise InvalidArguments("Период CUSTOM_DATE: нужны --date-from и --date-to (YYYY-MM-DD).")
        criteria = {"DateFrom": spec.date_from, "DateTo": spec.date_to}
    elif spec.date_from or spec.date_to:
        raise InvalidArguments(f"--date-from/--date-to — только без --range (сейчас {date_range}).")
    filters = [_filter(f) for f in spec.filters]
    if spec.campaign_ids:
        filters.append({"Field": "CampaignId", "Operator": "IN", "Values": [str(i) for i in spec.campaign_ids]})
    if spec.adgroup_ids:
        filters.append({"Field": "AdGroupId", "Operator": "IN", "Values": [str(i) for i in spec.adgroup_ids]})
    if filters:
        criteria["Filter"] = filters
    params: dict[str, Any] = {
        "SelectionCriteria": criteria,
        "FieldNames": spec.fields,
        "ReportType": report_type,
        "DateRangeType": date_range,
        "Format": "TSV",
        "IncludeVAT": "YES" if spec.include_vat else "NO",
        "IncludeDiscount": "YES" if spec.include_discount else "NO",
    }
    if spec.order_by:
        params["OrderBy"] = [_order(o) for o in spec.order_by]
    if spec.goals:
        if len(spec.goals) > 10:
            raise InvalidArguments("--goal: не больше 10 целей.")
        params["Goals"] = [str(g) for g in spec.goals]
    if spec.attribution_models:
        models = [m.upper() for m in spec.attribution_models]
        bad = [m for m in models if m not in ATTRIBUTION_MODELS]
        if bad:
            raise InvalidArguments(f"--attribution-model {', '.join(bad)}? Варианты: {', '.join(ATTRIBUTION_MODELS)}.")
        params["AttributionModels"] = models
    if spec.limit:
        params["Page"] = {"Limit": spec.limit}
    if spec.name:
        params["ReportName"] = spec.name
    return params
