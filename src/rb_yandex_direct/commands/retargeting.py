"""`yd retargeting` — условия ретаргетинга (RetargetingLists) и `yd audiences` — их привязки к группам (AudienceTargets)."""

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
    ids_mutation,
    scope_item,
    values,
)

app = output.group("Условия ретаргетинга и подбора аудитории: цели и сегменты Метрики, аудитории.")
audiences_app = output.group("Нацеливание групп на аудитории: условия ретаргетинга и интересы, ставки в сетях.")


class ListType(StrEnum):
    RETARGETING = "RETARGETING"
    AUDIENCE = "AUDIENCE"


class Operator(StrEnum):
    ALL = "ALL"
    ANY = "ANY"
    NONE = "NONE"


class AudienceState(StrEnum):
    ON = "ON"
    SUSPENDED = "SUSPENDED"


GoalOption = typer.Option(None, "--goal", help="Id цели или сегмента Метрики (повторяемая).")
DaysOption = typer.Option(30, "--days", help="Срок, за который учитывается достижение цели, 1–540 дней.")
OperatorOption = typer.Option(
    Operator.ANY, "--operator", help="Как сочетать цели правила: ALL — все, ANY — любая, NONE — ни одной."
)

LIST_COLUMNS = [
    ("Id", "Id"),
    ("Название", "Name"),
    ("Тип", "Type"),
    ("Доступен", "IsAvailable"),
    ("Применение", "Scope"),
]


def _rule(goals: list[int], days: int, operator: Operator) -> dict[str, Any]:
    return {"Operator": operator.value, "Arguments": [{"ExternalId": g, "MembershipLifeSpan": days} for g in goals]}


@app.command("list")
@output.guard
def list_lists(
    ctx: typer.Context,
    ids: list[int] = IdFilter,
    types: list[ListType] = typer.Option(None, "--type", help="RETARGETING или AUDIENCE (повторяемая)."),
    fields: list[str] = FieldOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Условия ретаргетинга: правила из целей Метрики, доступность, где применимы.

    --json: {"ok": true, "count": N, "lists": [{Id, Name, Description, Type, Rules, IsAvailable, Scope}]}.

    Example: {cli} retargeting list --type AUDIENCE
    """
    items = services.run(
        services.direct(ctx.obj).list_retargeting_lists(
            ids=ids or None, types=values(types), field_names=fields or None
        )
    )
    emit_list(ctx, "lists", items, LIST_COLUMNS, title="Условия ретаргетинга")


@app.command("add")
@output.guard
def add(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Название (до 250 символов)."),
    goals: list[int] = GoalOption,
    days: int = DaysOption,
    operator: Operator = OperatorOption,
    description: str = typer.Option(None, "--description", help="Описание (до 4096 символов)."),
    list_type: ListType = typer.Option(ListType.RETARGETING, "--type", help="RETARGETING или AUDIENCE."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать условие ретаргетинга из одного правила (набор целей с оператором).

    Несколько правил — `retargeting add-json`.

    Example: {cli} retargeting add --name Корзина --goal 123456 --days 30 --dry-run
    """
    if not goals:
        raise InvalidArguments("Укажите хотя бы одну цель: --goal.")
    item: dict[str, Any] = {"Name": name, "Type": list_type.value, "Rules": [_rule(goals, days, operator)]}
    if description:
        item["Description"] = description
    mutate(
        ctx,
        title=f"Создать условие «{name}» ({len(goals)} целей, {operator.value})",
        service="retargetinglists",
        method="add",
        params={"RetargetingLists": [item]},
        confirm=confirm,
    )


@app.command("add-json")
@output.guard
def add_json(
    ctx: typer.Context,
    from_json: str = FromJsonOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать условия ретаргетинга из JSON: список RetargetingListAddItem или {"RetargetingLists": [...]}.

    Example: {cli} retargeting add-json --from-json lists.json --dry-run
    """
    data = read_json(from_json)
    items = data.get("RetargetingLists") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise InvalidArguments('Ожидается непустой список условий или {"RetargetingLists": [...]}.')
    mutate(
        ctx,
        title=f"Создать условия ретаргетинга: {len(items)} шт.",
        service="retargetinglists",
        method="add",
        params={"RetargetingLists": items},
        confirm=confirm,
    )


@app.command("update")
@output.guard
def update(
    ctx: typer.Context,
    list_id: int = typer.Argument(..., help="Id условия ретаргетинга."),
    name: str = typer.Option(None, "--name", help="Новое название."),
    description: str = typer.Option(None, "--description", help="Новое описание."),
    goals: list[int] = GoalOption,
    days: int = DaysOption,
    operator: Operator = OperatorOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить название, описание или правила условия; с --goal правила целиком заменяются одним новым.

    Example: {cli} retargeting update 4001 --name 'Корзина 30 дней' --dry-run
    """
    item: dict[str, Any] = {"Id": list_id}
    if name:
        item["Name"] = name
    if description is not None:
        item["Description"] = description
    if goals:
        item["Rules"] = [_rule(goals, days, operator)]
    if len(item) == 1:
        raise InvalidArguments("Нечего менять: укажите --name, --description или --goal.")
    mutate(
        ctx,
        title=f"Изменить условие ретаргетинга {list_id}",
        service="retargetinglists",
        method="update",
        params={"RetargetingLists": [item]},
        confirm=confirm,
    )


@app.command("delete")
@output.guard
def delete(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить условия ретаргетинга (используемые в группах или корректировках не удаляются).

    Example: {cli} retargeting delete 4001 --dry-run
    """
    ids_mutation(
        ctx,
        service="retargetinglists",
        method="delete",
        verb="Удалить",
        noun="условия ретаргетинга",
        ids=ids,
        confirm=confirm,
    )


# --- audiences ---------------------------------------------------------------------------------

AUDIENCE_COLUMNS = [
    ("Id", "Id"),
    ("Группа", "AdGroupId"),
    ("Условие", "RetargetingListId"),
    ("Интерес", "InterestId"),
    ("Состояние", "State"),
    ("Сети ₽", lambda a: services.rubles(a.get("ContextBid"))),
    ("Приоритет", "StrategyPriority"),
]


@audiences_app.command("list")
@output.guard
def audiences_list(
    ctx: typer.Context,
    ids: list[int] = IdFilter,
    adgroups: list[int] = AdGroupFilter,
    campaigns: list[int] = CampaignFilter,
    lists: list[int] = typer.Option(None, "--retargeting", help="Фильтр по условию ретаргетинга (повторяемая)."),
    interests: list[int] = typer.Option(None, "--interest", help="Фильтр по интересу (повторяемая)."),
    states: list[AudienceState] = typer.Option(None, "--state", help="ON или SUSPENDED (повторяемая)."),
    fields: list[str] = FieldOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Нацеливания на аудитории в группах: условие или интерес, состояние, ставка.

    Нужен хотя бы один из --id, --adgroup, --campaign, --retargeting, --interest.
    --json: {"ok": true, "count": N, "audiences": [{Id, AdGroupId, CampaignId, RetargetingListId,
    InterestId, State, ContextBid, StrategyPriority}]}.

    Example: {cli} audiences list --campaign 12345
    """
    if not (ids or adgroups or campaigns or lists or interests):
        raise InvalidArguments("Укажите хотя бы один фильтр: --id, --adgroup, --campaign, --retargeting, --interest.")
    items = services.run(
        services.direct(ctx.obj).list_audience_targets(
            adgroup_ids=adgroups or None,
            campaign_ids=campaigns or None,
            ids=ids or None,
            states=values(states),
            field_names=fields or None,
            retargeting_list_ids=lists or None,
            interest_ids=interests or None,
        )
    )
    emit_list(ctx, "audiences", items, AUDIENCE_COLUMNS, title="Нацеливания на аудитории")


@audiences_app.command("add")
@output.guard
def audiences_add(
    ctx: typer.Context,
    adgroup: int = typer.Option(..., "--adgroup", help="Группа объявлений."),
    retargeting: int = typer.Option(None, "--retargeting", help="Id условия ретаргетинга (или --interest)."),
    interest: int = typer.Option(None, "--interest", help="Id интереса (группы мобильных приложений)."),
    context_bid: float = typer.Option(None, "--context-bid", help="Ставка в сетях, ₽ (ручная стратегия)."),
    priority: Priority = PriorityOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Нацелить группу на аудиторию: условие ретаргетинга или интерес.

    Example: {cli} audiences add --adgroup 555 --retargeting 4001 --dry-run
    """
    if (retargeting is None) == (interest is None):
        raise InvalidArguments("Укажите ровно одно из --retargeting, --interest.")
    item: dict[str, Any] = {"AdGroupId": adgroup}
    if retargeting is not None:
        item["RetargetingListId"] = retargeting
    if interest is not None:
        item["InterestId"] = interest
    if context_bid is not None:
        item["ContextBid"] = services.micros(context_bid)
    if priority:
        item["StrategyPriority"] = priority.value
    mutate(
        ctx,
        title=f"Нацелить группу {adgroup} на аудиторию",
        service="audiencetargets",
        method="add",
        params={"AudienceTargets": [item]},
        confirm=confirm,
    )


@audiences_app.command("set-bids")
@output.guard
def audiences_set_bids(
    ctx: typer.Context,
    target_id: int = typer.Option(None, "--id", help="Id нацеливания."),
    adgroup: int = typer.Option(None, "--adgroup", help="Id группы — для всех её нацеливаний."),
    campaign: int = typer.Option(None, "--campaign", help="Id кампании — для всех её нацеливаний."),
    context_bid: float = typer.Option(None, "--context-bid", help="Ставка в сетях, ₽."),
    priority: Priority = PriorityOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Задать ставку в сетях или приоритет нацеливаниям на аудитории.

    Ровно одно из --id, --adgroup, --campaign.

    Example: {cli} audiences set-bids --id 5001 --context-bid 8 --dry-run
    """
    item = scope_item(target_id, adgroup, campaign)
    if context_bid is not None:
        item["ContextBid"] = services.micros(context_bid)
    if priority:
        item["StrategyPriority"] = priority.value
    if len(item) == 1:
        raise InvalidArguments("Нечего менять: укажите --context-bid или --priority.")
    mutate(
        ctx,
        title=f"Ставки нацеливаний на аудитории {item}",
        service="audiencetargets",
        method="setBids",
        params={"Bids": [item]},
        confirm=confirm,
    )


@audiences_app.command("suspend")
@output.guard
def audiences_suspend(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Остановить нацеливания на аудитории.

    Example: {cli} audiences suspend 5001 --confirm
    """
    ids_mutation(
        ctx,
        service="audiencetargets",
        method="suspend",
        verb="Остановить",
        noun="нацеливания",
        ids=ids,
        confirm=confirm,
    )


@audiences_app.command("resume")
@output.guard
def audiences_resume(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Возобновить нацеливания на аудитории.

    Example: {cli} audiences resume 5001 --confirm
    """
    ids_mutation(
        ctx,
        service="audiencetargets",
        method="resume",
        verb="Возобновить",
        noun="нацеливания",
        ids=ids,
        confirm=confirm,
    )


@audiences_app.command("delete")
@output.guard
def audiences_delete(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить нацеливания на аудитории.

    Example: {cli} audiences delete 5001 --dry-run
    """
    ids_mutation(
        ctx, service="audiencetargets", method="delete", verb="Удалить", noun="нацеливания", ids=ids, confirm=confirm
    )
