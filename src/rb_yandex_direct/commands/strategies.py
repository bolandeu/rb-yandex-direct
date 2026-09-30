"""`yd strategies` — пакетные стратегии (сервис Strategies): одна стратегия на несколько кампаний."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import typer

from .. import output
from ..core import services
from ..core.errors import InvalidArguments
from ..core.strategy import (
    ATTRIBUTION_MODELS,
    PACKAGE_STRATEGY_GET_FIELDS,
    PACKAGE_STRATEGY_TYPES,
    package_strategy_block,
    priority_goals,
)
from . import _strategy as st
from ._common import FromJsonOption, IdsArgument, emit_list, mutate, read_json

app = output.group("Пакетные стратегии: список, создание, изменение, архив (сервис Strategies).")

StrategyType = StrEnum("StrategyType", {t: t for t in PACKAGE_STRATEGY_TYPES})

COLUMNS = [
    ("Id", "Id"),
    ("Название", "Name"),
    ("Тип", "Type"),
    ("В архиве", "StatusArchived"),
    ("Счётчики", lambda s: (s.get("CounterIds") or {}).get("Items")),
]


@app.command("list")
@output.guard
def list_strategies(
    ctx: typer.Context,
    ids: list[int] = typer.Option(None, "--id", help="Только эти стратегии (повторяемая)."),
    types: list[StrategyType] = typer.Option(None, "--type", help="Фильтр по типу стратегии (повторяемая)."),
    archived: bool = typer.Option(
        None, "--archived/--active", help="Только архивные или только действующие (по умолчанию — все)."
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Пакетные стратегии кабинета со всеми параметрами (бюджет, цель, цена конверсии).

    --json: {"ok": true, "count": N, "strategies": [{Id, Name, Type, StatusArchived, CounterIds,
    PriorityGoals, <Блок типа>: {...}}]}; суммы — в микроединицах валюты.

    Example: {cli} strategies list --active
    """
    criteria: dict[str, Any] = {}
    if ids:
        criteria["Ids"] = ids
    if types:
        criteria["Types"] = [t.value for t in types]
    if archived is not None:
        criteria["IsArchived"] = "YES" if archived else "NO"
    params = {"SelectionCriteria": criteria, **PACKAGE_STRATEGY_GET_FIELDS}
    items = services.run(services.direct(ctx.obj).list_strategies(params))
    emit_list(ctx, "strategies", items, COLUMNS, title="Пакетные стратегии")


def _common_fields(
    item: dict[str, Any],
    counter_ids: list[int] | None,
    goals: list[str] | None,
    attribution_model: str | None,
) -> None:
    if counter_ids:
        item["CounterIds"] = {"Items": counter_ids}
    parsed_goals = priority_goals(goals)
    if parsed_goals:
        item["PriorityGoals"] = parsed_goals
    if attribution_model:
        model = attribution_model.upper()
        if model not in ATTRIBUTION_MODELS:
            raise InvalidArguments(f"--attribution-model: один из {', '.join(ATTRIBUTION_MODELS)}.")
        item["AttributionModel"] = model


CounterOption = typer.Option(None, "--counter-id", help="Счётчик Метрики (повторяемая).")
PriorityGoalOption = typer.Option(
    None, "--priority-goal", help="Ключевая цель ЦЕЛЬ=ЦЕННОСТЬ_₽ (повторяемая; для *_MULTIPLE_GOALS)."
)
AttributionOption = typer.Option(
    None, "--attribution-model", help="Модель атрибуции: LC, LSC, FC, LYDC, LSCCD, FCCD, LYDCCD, AUTO."
)


@app.command("add")
@output.guard
def add(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Название стратегии."),
    strategy_type: StrategyType = typer.Option(..., "--type", help="Тип стратегии: WB_MAXIMUM_CLICKS, AVERAGE_CPA…"),
    weekly_budget: float = st.WeeklyBudgetOption,
    bid_ceiling: float = st.BidCeilingOption,
    average_cpc: float = st.AverageCpcOption,
    average_cpa: float = st.AverageCpaOption,
    cpa: float = st.CpaOption,
    goal_id: int = st.GoalIdOption,
    crr: int = st.CrrOption,
    counter_ids: list[int] = CounterOption,
    goals: list[str] = PriorityGoalOption,
    attribution_model: str = AttributionOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать пакетную стратегию; кампании подключаются к ней через PackageBiddingStrategy.

    Обязательные параметры зависят от типа (AVERAGE_CPA — --average-cpa и --goal-id и т.д.);
    недостающий или лишний — INVALID_ARGUMENTS до запроса. Бюджеты и цены — в рублях.
    Бюджет на период и ExplorationBudget — через `strategies add-json`.

    Example: {cli} strategies add --name Клики --type WB_MAXIMUM_CLICKS --weekly-budget 15000 --dry-run
    """
    params = st.params(weekly_budget, bid_ceiling, average_cpc, average_cpa, cpa, goal_id, crr)
    item: dict[str, Any] = {"Name": name, **package_strategy_block(strategy_type.value, params)}
    _common_fields(item, counter_ids, goals, attribution_model)
    mutate(
        ctx,
        title=f"Создать пакетную стратегию «{name}» ({strategy_type.value})",
        service="strategies",
        method="add",
        params={"Strategies": [item]},
        confirm=confirm,
    )


@app.command("update")
@output.guard
def update(
    ctx: typer.Context,
    strategy_id: int = typer.Argument(..., help="Id стратегии."),
    strategy_type: StrategyType = typer.Option(
        None, "--type", help="Тип стратегии — нужен, чтобы менять её параметры (тип самой стратегии не меняется)."
    ),
    name: str = typer.Option(None, "--name", help="Новое название."),
    weekly_budget: float = st.WeeklyBudgetOption,
    bid_ceiling: float = st.BidCeilingOption,
    average_cpc: float = st.AverageCpcOption,
    average_cpa: float = st.AverageCpaOption,
    cpa: float = st.CpaOption,
    goal_id: int = st.GoalIdOption,
    crr: int = st.CrrOption,
    counter_ids: list[int] = CounterOption,
    goals: list[str] = PriorityGoalOption,
    attribution_model: str = AttributionOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить пакетную стратегию: название, параметры, счётчики, цели, атрибуцию.

    Параметры стратегии (--weekly-budget, --average-cpa…) требуют --type — он указывает
    блок, в который они пишутся; задано только то, что передано.

    Example: {cli} strategies update 555 --type WB_MAXIMUM_CLICKS --weekly-budget 20000 --dry-run
    """
    params = st.params(weekly_budget, bid_ceiling, average_cpc, average_cpa, cpa, goal_id, crr)
    item: dict[str, Any] = {"Id": strategy_id}
    if name:
        item["Name"] = name
    if params.given():
        if strategy_type is None:
            raise InvalidArguments("Параметры стратегии меняются с --type (тип стратегии, см. `strategies list`).")
        item.update(package_strategy_block(strategy_type.value, params, update=True))
    _common_fields(item, counter_ids, goals, attribution_model)
    if len(item) == 1:
        raise InvalidArguments("Нечего менять: укажите --name, параметры стратегии, --counter-id или цели.")
    mutate(
        ctx,
        title=f"Изменить пакетную стратегию {strategy_id}",
        service="strategies",
        method="update",
        params={"Strategies": [item]},
        confirm=confirm,
    )


@app.command("archive")
@output.guard
def archive(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Отправить пакетные стратегии в архив (к ним больше нельзя подключать кампании).

    Example: {cli} strategies archive 555 --confirm
    """
    _ids(ctx, "archive", "Архивировать", ids, confirm)


@app.command("unarchive")
@output.guard
def unarchive(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Вернуть пакетные стратегии из архива.

    Example: {cli} strategies unarchive 555 --confirm
    """
    _ids(ctx, "unarchive", "Разархивировать", ids, confirm)


def _ids(ctx: typer.Context, method: str, verb: str, ids: list[int], confirm: bool) -> None:
    mutate(
        ctx,
        title=f"{verb} стратегии {', '.join(map(str, ids))}",
        service="strategies",
        method=method,
        params={"SelectionCriteria": {"Ids": ids}},
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
    """Создать пакетные стратегии из JSON: список StrategyAddItem или {"Strategies": [...]}.

    Для всего, чего нет в опциях `strategies add`: CustomPeriodBudget, ExplorationBudget.

    Example: {cli} strategies add-json --from-json strategies.json --dry-run
    """
    data = read_json(from_json)
    items = data.get("Strategies") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise InvalidArguments('Ожидается непустой список стратегий или {"Strategies": [...]}.')
    mutate(
        ctx,
        title=f"Создать пакетные стратегии: {len(items)} шт.",
        service="strategies",
        method="add",
        params={"Strategies": items},
        confirm=confirm,
    )
