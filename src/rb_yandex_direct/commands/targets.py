"""Условия нацеливания динамических объявлений и смарт-баннеров.

- `yd dynamic-targets` — по страницам сайта (DynamicTextAdTargets, объект Webpage);
- `yd dynamic-feed-targets` — по товарам фида (DynamicFeedAdTargets);
- `yd smart-targets` — фильтры смарт-баннеров (SmartAdTargets).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import typer

from .. import output
from ..core import services
from ..core.errors import InvalidArguments
from ._common import FromJsonOption, emit_list, mutate, read_json
from ._targeting import (
    AdGroupFilter,
    CampaignFilter,
    FieldOption,
    IdFilter,
    IdsArgument,
    Priority,
    PriorityOption,
    TargetState,
    YesNo,
    ids_mutation,
    parse_conditions,
    scope_item,
    values,
)

dynamic_app = output.group("Нацеливание динамических объявлений по страницам сайта: условия и ставки.")
feed_app = output.group("Нацеливание динамических объявлений по фиду: фильтры товаров и ставки.")
smart_app = output.group("Фильтры смарт-баннеров: аудитория, условия по фиду, цена клика или конверсии.")

StatesFilter = typer.Option(None, "--state", help="ON, OFF, SUSPENDED, DELETED (повторяемая).")
ScopeId = typer.Option(None, "--id", help="Id условия.")
ScopeAdGroup = typer.Option(None, "--adgroup", help="Id группы — для всех её условий.")
ScopeCampaign = typer.Option(None, "--campaign", help="Id кампании — для всех её условий.")
AvailableOption = typer.Option(None, "--available-items-only", help="YES — только товары в наличии.")

_WEBPAGE_CONDITION_HELP = (
    "Условие OPERAND:OPERATOR:ARG1|ARG2 (повторяемая); OPERAND — URL, DOMAIN, PAGE_TITLE, PAGE_CONTENT, "
    "OFFERS_LIST_URL; OPERATOR — EQUALS_ANY, NOT_EQUALS_ALL, CONTAINS_ANY, NOT_CONTAINS_ALL. Без условий — все страницы."
)
_FEED_CONDITION_HELP = (
    "Условие по полю фида OPERAND:OPERATOR:ARG1|ARG2 (повторяемая), например categoryId:EQUALS_ANY:12|15; "
    "OPERATOR — EQUALS_ANY, NOT_EQUALS_ALL, CONTAINS_ANY, NOT_CONTAINS_ALL, GREATER_THAN, LESS_THAN, IN_RANGE. "
    "Без условий — все товары."
)


class Audience(StrEnum):
    INTERESTED_IN_SIMILAR_PRODUCTS = "INTERESTED_IN_SIMILAR_PRODUCTS"
    VISITED_PRODUCT_PAGE = "VISITED_PRODUCT_PAGE"
    ALL_SEGMENTS = "ALL_SEGMENTS"


def _conditions_summary(item: dict) -> str:
    conditions = item.get("Conditions") or []
    if isinstance(conditions, dict):  # фид и смарт: {"Items": [...]}
        conditions = conditions.get("Items") or []
    return "; ".join(f"{c.get('Operand')} {c.get('Operator')} {'|'.join(c.get('Arguments') or [])}" for c in conditions)


def _json_items(path: str, key: str) -> list[dict]:
    data = read_json(path)
    items = data.get(key) if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise InvalidArguments(f'Ожидается непустой список условий или {{"{key}": [...]}}.')
    return items


def _require_list_filter(ids: list[int] | None, adgroups: list[int] | None, campaigns: list[int] | None) -> None:
    if not (ids or adgroups or campaigns):
        raise InvalidArguments("Укажите хотя бы один фильтр: --id, --adgroup или --campaign.")


# --- dynamic-targets (Webpages) -----------------------------------------------------------------

WEBPAGE_COLUMNS = [
    ("Id", "Id"),
    ("Группа", "AdGroupId"),
    ("Название", "Name"),
    ("Состояние", "State"),
    ("Поиск ₽", lambda t: services.rubles(t.get("Bid"))),
    ("Сети ₽", lambda t: services.rubles(t.get("ContextBid"))),
    ("Условия", _conditions_summary),
]


@dynamic_app.command("list")
@output.guard
def dynamic_list(
    ctx: typer.Context,
    ids: list[int] = IdFilter,
    adgroups: list[int] = AdGroupFilter,
    campaigns: list[int] = CampaignFilter,
    states: list[TargetState] = StatesFilter,
    fields: list[str] = FieldOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Условия нацеливания по страницам сайта: условия, ставки, состояние.

    Нужен хотя бы один из --id, --adgroup, --campaign.
    --json: {"ok": true, "count": N, "targets": [{Id, AdGroupId, CampaignId, Name, State, Bid,
    ContextBid, StrategyPriority, Conditions: [{Operand, Operator, Arguments}], ConditionType}]}.

    Example: {cli} dynamic-targets list --campaign 12345
    """
    _require_list_filter(ids, adgroups, campaigns)
    items = services.run(
        services.direct(ctx.obj).list_dynamic_text_ad_targets(
            adgroup_ids=adgroups or None,
            campaign_ids=campaigns or None,
            ids=ids or None,
            states=values(states),
            field_names=fields or None,
        )
    )
    emit_list(ctx, "targets", items, WEBPAGE_COLUMNS, title="Условия по страницам")


@dynamic_app.command("add")
@output.guard
def dynamic_add(
    ctx: typer.Context,
    adgroup: int = typer.Option(..., "--adgroup", help="Группа динамических объявлений."),
    name: str = typer.Option(..., "--name", help="Название условия."),
    conditions: list[str] = typer.Option(None, "--condition", help=_WEBPAGE_CONDITION_HELP),
    bid: float = typer.Option(None, "--bid", help="Ставка на поиске, ₽."),
    context_bid: float = typer.Option(None, "--context-bid", help="Ставка в сетях, ₽."),
    priority: Priority = PriorityOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Добавить условие нацеливания по страницам сайта.

    Example: {cli} dynamic-targets add --adgroup 555 --name Каталог --condition URL:CONTAINS_ANY:/catalog/ --bid 10 --dry-run
    """
    item: dict[str, Any] = {"AdGroupId": adgroup, "Name": name}
    parsed = parse_conditions(conditions)
    if parsed:
        item["Conditions"] = parsed
    if bid is not None:
        item["Bid"] = services.micros(bid)
    if context_bid is not None:
        item["ContextBid"] = services.micros(context_bid)
    if priority:
        item["StrategyPriority"] = priority.value
    mutate(
        ctx,
        title=f"Условие «{name}» в группе {adgroup}",
        service="dynamictextadtargets",
        method="add",
        params={"Webpages": [item]},
        confirm=confirm,
    )


@dynamic_app.command("add-json")
@output.guard
def dynamic_add_json(
    ctx: typer.Context,
    from_json: str = FromJsonOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Добавить условия по страницам из JSON: список WebpageAddItem или {"Webpages": [...]}.

    Example: {cli} dynamic-targets add-json --from-json targets.json --dry-run
    """
    items = _json_items(from_json, "Webpages")
    mutate(
        ctx,
        title=f"Условия по страницам: {len(items)} шт.",
        service="dynamictextadtargets",
        method="add",
        params={"Webpages": items},
        confirm=confirm,
    )


@dynamic_app.command("set-bids")
@output.guard
def dynamic_set_bids(
    ctx: typer.Context,
    target_id: int = ScopeId,
    adgroup: int = ScopeAdGroup,
    campaign: int = ScopeCampaign,
    bid: float = typer.Option(None, "--bid", help="Ставка на поиске, ₽."),
    context_bid: float = typer.Option(None, "--context-bid", help="Ставка в сетях, ₽."),
    priority: Priority = PriorityOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Задать ставки или приоритет условиям по страницам (ровно одно из --id, --adgroup, --campaign).

    Example: {cli} dynamic-targets set-bids --id 8001 --bid 10 --dry-run
    """
    item = scope_item(target_id, adgroup, campaign)
    if bid is not None:
        item["Bid"] = services.micros(bid)
    if context_bid is not None:
        item["ContextBid"] = services.micros(context_bid)
    if priority:
        item["StrategyPriority"] = priority.value
    if len(item) == 1:
        raise InvalidArguments("Нечего менять: укажите --bid, --context-bid или --priority.")
    mutate(
        ctx,
        title=f"Ставки условий по страницам {item}",
        service="dynamictextadtargets",
        method="setBids",
        params={"Bids": [item]},
        confirm=confirm,
    )


@dynamic_app.command("suspend")
@output.guard
def dynamic_suspend(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Остановить условия нацеливания по страницам.

    Example: {cli} dynamic-targets suspend 8001 --confirm
    """
    ids_mutation(
        ctx,
        service="dynamictextadtargets",
        method="suspend",
        verb="Остановить",
        noun="условия",
        ids=ids,
        confirm=confirm,
    )


@dynamic_app.command("resume")
@output.guard
def dynamic_resume(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Возобновить условия нацеливания по страницам.

    Example: {cli} dynamic-targets resume 8001 --confirm
    """
    ids_mutation(
        ctx,
        service="dynamictextadtargets",
        method="resume",
        verb="Возобновить",
        noun="условия",
        ids=ids,
        confirm=confirm,
    )


@dynamic_app.command("delete")
@output.guard
def dynamic_delete(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить условия нацеливания по страницам.

    Example: {cli} dynamic-targets delete 8001 --dry-run
    """
    ids_mutation(
        ctx, service="dynamictextadtargets", method="delete", verb="Удалить", noun="условия", ids=ids, confirm=confirm
    )


# --- dynamic-feed-targets (DynamicFeedAdTargets) ------------------------------------------------

FEED_COLUMNS = [
    ("Id", "Id"),
    ("Группа", "AdGroupId"),
    ("Название", "Name"),
    ("Состояние", "State"),
    ("Поиск ₽", lambda t: services.rubles(t.get("Bid"))),
    ("Сети ₽", lambda t: services.rubles(t.get("ContextBid"))),
    ("В наличии", "AvailableItemsOnly"),
    ("Условия", _conditions_summary),
]


@feed_app.command("list")
@output.guard
def feed_list(
    ctx: typer.Context,
    ids: list[int] = IdFilter,
    adgroups: list[int] = AdGroupFilter,
    campaigns: list[int] = CampaignFilter,
    states: list[TargetState] = StatesFilter,
    fields: list[str] = FieldOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Фильтры динамических объявлений по фиду: условия по полям товаров, ставки, состояние.

    Нужен хотя бы один из --id, --adgroup, --campaign.
    --json: {"ok": true, "count": N, "targets": [{Id, AdGroupId, CampaignId, Name, State, Bid,
    ContextBid, Conditions: {Items: [...]}, ConditionType, AvailableItemsOnly}]}.

    Example: {cli} dynamic-feed-targets list --campaign 12345
    """
    _require_list_filter(ids, adgroups, campaigns)
    items = services.run(
        services.direct(ctx.obj).list_dynamic_feed_ad_targets(
            adgroup_ids=adgroups or None,
            campaign_ids=campaigns or None,
            ids=ids or None,
            states=values(states),
            field_names=fields or None,
        )
    )
    emit_list(ctx, "targets", items, FEED_COLUMNS, title="Фильтры по фиду")


@feed_app.command("add")
@output.guard
def feed_add(
    ctx: typer.Context,
    adgroup: int = typer.Option(..., "--adgroup", help="Группа динамических объявлений по фиду."),
    name: str = typer.Option(..., "--name", help="Название фильтра."),
    conditions: list[str] = typer.Option(None, "--condition", help=_FEED_CONDITION_HELP),
    bid: float = typer.Option(None, "--bid", help="Ставка на поиске, ₽."),
    context_bid: float = typer.Option(None, "--context-bid", help="Ставка в сетях, ₽."),
    available_only: YesNo = AvailableOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Добавить фильтр динамических объявлений по фиду.

    Example: {cli} dynamic-feed-targets add --adgroup 555 --name Диваны --condition categoryId:EQUALS_ANY:12 --bid 10 --dry-run
    """
    item: dict[str, Any] = {"AdGroupId": adgroup, "Name": name}
    parsed = parse_conditions(conditions)
    if parsed:
        item["Conditions"] = {"Items": parsed}
    if bid is not None:
        item["Bid"] = services.micros(bid)
    if context_bid is not None:
        item["ContextBid"] = services.micros(context_bid)
    if available_only:
        item["AvailableItemsOnly"] = available_only.value
    mutate(
        ctx,
        title=f"Фильтр «{name}» в группе {adgroup}",
        service="dynamicfeedadtargets",
        method="add",
        params={"DynamicFeedAdTargets": [item]},
        confirm=confirm,
    )


@feed_app.command("add-json")
@output.guard
def feed_add_json(
    ctx: typer.Context,
    from_json: str = FromJsonOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Добавить фильтры по фиду из JSON: список DynamicFeedAdTargetAddItem или {"DynamicFeedAdTargets": [...]}.

    Example: {cli} dynamic-feed-targets add-json --from-json targets.json --dry-run
    """
    items = _json_items(from_json, "DynamicFeedAdTargets")
    mutate(
        ctx,
        title=f"Фильтры по фиду: {len(items)} шт.",
        service="dynamicfeedadtargets",
        method="add",
        params={"DynamicFeedAdTargets": items},
        confirm=confirm,
    )


@feed_app.command("set-bids")
@output.guard
def feed_set_bids(
    ctx: typer.Context,
    target_id: int = ScopeId,
    adgroup: int = ScopeAdGroup,
    campaign: int = ScopeCampaign,
    bid: float = typer.Option(None, "--bid", help="Ставка на поиске, ₽."),
    context_bid: float = typer.Option(None, "--context-bid", help="Ставка в сетях, ₽."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Задать ставки фильтрам по фиду (ровно одно из --id, --adgroup, --campaign).

    Example: {cli} dynamic-feed-targets set-bids --id 8101 --bid 10 --dry-run
    """
    item = scope_item(target_id, adgroup, campaign)
    if bid is not None:
        item["Bid"] = services.micros(bid)
    if context_bid is not None:
        item["ContextBid"] = services.micros(context_bid)
    if len(item) == 1:
        raise InvalidArguments("Нечего менять: укажите --bid или --context-bid.")
    mutate(
        ctx,
        title=f"Ставки фильтров по фиду {item}",
        service="dynamicfeedadtargets",
        method="setBids",
        params={"Bids": [item]},
        confirm=confirm,
    )


@feed_app.command("suspend")
@output.guard
def feed_suspend(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Остановить фильтры по фиду.

    Example: {cli} dynamic-feed-targets suspend 8101 --confirm
    """
    ids_mutation(
        ctx,
        service="dynamicfeedadtargets",
        method="suspend",
        verb="Остановить",
        noun="фильтры",
        ids=ids,
        confirm=confirm,
    )


@feed_app.command("resume")
@output.guard
def feed_resume(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Возобновить фильтры по фиду.

    Example: {cli} dynamic-feed-targets resume 8101 --confirm
    """
    ids_mutation(
        ctx,
        service="dynamicfeedadtargets",
        method="resume",
        verb="Возобновить",
        noun="фильтры",
        ids=ids,
        confirm=confirm,
    )


@feed_app.command("delete")
@output.guard
def feed_delete(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить фильтры по фиду.

    Example: {cli} dynamic-feed-targets delete 8101 --dry-run
    """
    ids_mutation(
        ctx, service="dynamicfeedadtargets", method="delete", verb="Удалить", noun="фильтры", ids=ids, confirm=confirm
    )


# --- smart-targets (SmartAdTargets) --------------------------------------------------------------

SMART_COLUMNS = [
    ("Id", "Id"),
    ("Группа", "AdGroupId"),
    ("Название", "Name"),
    ("Аудитория", "Audience"),
    ("Состояние", "State"),
    ("CPC ₽", lambda t: services.rubles(t.get("AverageCpc"))),
    ("CPA ₽", lambda t: services.rubles(t.get("AverageCpa"))),
    ("Условия", _conditions_summary),
]


def _smart_fields(
    item: dict[str, Any],
    *,
    conditions: list[str] | None,
    average_cpc: float | None,
    average_cpa: float | None,
    priority: Priority | None,
    audience: Audience | None,
    available_only: YesNo | None,
) -> dict[str, Any]:
    parsed = parse_conditions(conditions)
    if parsed:
        item["Conditions"] = {"Items": parsed}
    if average_cpc is not None:
        item["AverageCpc"] = services.micros(average_cpc)
    if average_cpa is not None:
        item["AverageCpa"] = services.micros(average_cpa)
    if priority:
        item["StrategyPriority"] = priority.value
    if audience:
        item["Audience"] = audience.value
    if available_only:
        item["AvailableItemsOnly"] = available_only.value
    return item


AverageCpcOption = typer.Option(None, "--average-cpc", help="Средняя цена клика, ₽ (стратегия с оплатой за клики).")
AverageCpaOption = typer.Option(
    None, "--average-cpa", help="Средняя цена конверсии, ₽ (стратегия с оплатой за конверсии)."
)


@smart_app.command("list")
@output.guard
def smart_list(
    ctx: typer.Context,
    ids: list[int] = IdFilter,
    adgroups: list[int] = AdGroupFilter,
    campaigns: list[int] = CampaignFilter,
    states: list[TargetState] = StatesFilter,
    fields: list[str] = FieldOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Фильтры смарт-баннеров: аудитория, условия по фиду, средние цены клика и конверсии.

    Нужен хотя бы один из --id, --adgroup, --campaign.
    --json: {"ok": true, "count": N, "targets": [{Id, AdGroupId, CampaignId, Name, State, Audience,
    AverageCpc, AverageCpa, StrategyPriority, Conditions: {Items}, ConditionType, AvailableItemsOnly}]}.

    Example: {cli} smart-targets list --campaign 12345
    """
    _require_list_filter(ids, adgroups, campaigns)
    items = services.run(
        services.direct(ctx.obj).list_smart_ad_targets(
            adgroup_ids=adgroups or None,
            campaign_ids=campaigns or None,
            ids=ids or None,
            states=values(states),
            field_names=fields or None,
        )
    )
    emit_list(ctx, "targets", items, SMART_COLUMNS, title="Фильтры смарт-баннеров")


@smart_app.command("add")
@output.guard
def smart_add(
    ctx: typer.Context,
    adgroup: int = typer.Option(..., "--adgroup", help="Группа смарт-баннеров."),
    name: str = typer.Option(..., "--name", help="Название фильтра."),
    audience: Audience = typer.Option(
        Audience.ALL_SEGMENTS,
        "--audience",
        help="Кому показывать: ALL_SEGMENTS, VISITED_PRODUCT_PAGE, INTERESTED_IN_SIMILAR_PRODUCTS.",
    ),
    conditions: list[str] = typer.Option(None, "--condition", help=_FEED_CONDITION_HELP),
    average_cpc: float = AverageCpcOption,
    average_cpa: float = AverageCpaOption,
    priority: Priority = PriorityOption,
    available_only: YesNo = AvailableOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Добавить фильтр смарт-баннеров.

    Example: {cli} smart-targets add --adgroup 555 --name Диваны --condition categoryId:EQUALS_ANY:12 --average-cpc 15 --dry-run
    """
    item = _smart_fields(
        {"AdGroupId": adgroup, "Name": name},
        conditions=conditions,
        average_cpc=average_cpc,
        average_cpa=average_cpa,
        priority=priority,
        audience=audience,
        available_only=available_only,
    )
    mutate(
        ctx,
        title=f"Фильтр «{name}» в группе {adgroup}",
        service="smartadtargets",
        method="add",
        params={"SmartAdTargets": [item]},
        confirm=confirm,
    )


@smart_app.command("add-json")
@output.guard
def smart_add_json(
    ctx: typer.Context,
    from_json: str = FromJsonOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Добавить фильтры смарт-баннеров из JSON: список SmartAdTargetAddItem или {"SmartAdTargets": [...]}.

    Example: {cli} smart-targets add-json --from-json targets.json --dry-run
    """
    items = _json_items(from_json, "SmartAdTargets")
    mutate(
        ctx,
        title=f"Фильтры смарт-баннеров: {len(items)} шт.",
        service="smartadtargets",
        method="add",
        params={"SmartAdTargets": items},
        confirm=confirm,
    )


@smart_app.command("update")
@output.guard
def smart_update(
    ctx: typer.Context,
    target_id: int = typer.Argument(..., help="Id фильтра."),
    name: str = typer.Option(None, "--name", help="Новое название."),
    audience: Audience = typer.Option(None, "--audience", help="Новая аудитория."),
    conditions: list[str] = typer.Option(None, "--condition", help=_FEED_CONDITION_HELP + " Заменяет все условия."),
    average_cpc: float = AverageCpcOption,
    average_cpa: float = AverageCpaOption,
    priority: Priority = PriorityOption,
    available_only: YesNo = AvailableOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить фильтр смарт-баннеров: название, аудиторию, условия, цены, приоритет.

    Example: {cli} smart-targets update 9001 --average-cpa 300 --dry-run
    """
    item: dict[str, Any] = {"Id": target_id}
    if name:
        item["Name"] = name
    item = _smart_fields(
        item,
        conditions=conditions,
        average_cpc=average_cpc,
        average_cpa=average_cpa,
        priority=priority,
        audience=audience,
        available_only=available_only,
    )
    if len(item) == 1:
        raise InvalidArguments("Нечего менять: укажите хотя бы один параметр фильтра.")
    mutate(
        ctx,
        title=f"Изменить фильтр {target_id}",
        service="smartadtargets",
        method="update",
        params={"SmartAdTargets": [item]},
        confirm=confirm,
    )


@smart_app.command("set-bids")
@output.guard
def smart_set_bids(
    ctx: typer.Context,
    target_id: int = ScopeId,
    adgroup: int = ScopeAdGroup,
    campaign: int = ScopeCampaign,
    average_cpc: float = AverageCpcOption,
    average_cpa: float = AverageCpaOption,
    priority: Priority = PriorityOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Задать средние цены клика/конверсии или приоритет фильтрам (ровно одно из --id, --adgroup, --campaign).

    Example: {cli} smart-targets set-bids --id 9001 --average-cpc 12 --dry-run
    """
    item = _smart_fields(
        scope_item(target_id, adgroup, campaign),
        conditions=None,
        average_cpc=average_cpc,
        average_cpa=average_cpa,
        priority=priority,
        audience=None,
        available_only=None,
    )
    if len(item) == 1:
        raise InvalidArguments("Нечего менять: укажите --average-cpc, --average-cpa или --priority.")
    mutate(
        ctx,
        title=f"Ставки фильтров смарт-баннеров {item}",
        service="smartadtargets",
        method="setBids",
        params={"Bids": [item]},
        confirm=confirm,
    )


@smart_app.command("suspend")
@output.guard
def smart_suspend(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Остановить фильтры смарт-баннеров.

    Example: {cli} smart-targets suspend 9001 --confirm
    """
    ids_mutation(
        ctx, service="smartadtargets", method="suspend", verb="Остановить", noun="фильтры", ids=ids, confirm=confirm
    )


@smart_app.command("resume")
@output.guard
def smart_resume(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Возобновить фильтры смарт-баннеров.

    Example: {cli} smart-targets resume 9001 --confirm
    """
    ids_mutation(
        ctx, service="smartadtargets", method="resume", verb="Возобновить", noun="фильтры", ids=ids, confirm=confirm
    )


@smart_app.command("delete")
@output.guard
def smart_delete(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить фильтры смарт-баннеров.

    Example: {cli} smart-targets delete 9001 --dry-run
    """
    ids_mutation(
        ctx, service="smartadtargets", method="delete", verb="Удалить", noun="фильтры", ids=ids, confirm=confirm
    )
