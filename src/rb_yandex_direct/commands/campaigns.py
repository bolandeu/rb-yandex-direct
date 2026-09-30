"""`yd campaigns` — кампании (сервис Campaigns)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import typer

from .. import output
from ..core import services
from ..core.errors import InvalidArguments
from ..providers.direct import DEFAULT_CAMPAIGN_FIELDS
from ._common import FromJsonOption, IdsArgument, emit_list, emit_object, mutate, read_json, read_lines

app = output.group("Кампании: список, изменение, статусы, бюджет, минус-фразы.")


class State(StrEnum):
    ON = "ON"
    OFF = "OFF"
    SUSPENDED = "SUSPENDED"
    ENDED = "ENDED"
    CONVERTED = "CONVERTED"
    ARCHIVED = "ARCHIVED"


class BudgetMode(StrEnum):
    STANDARD = "STANDARD"
    DISTRIBUTED = "DISTRIBUTED"


_FIELDS_HELP = f"Поле FieldNames вместо набора по умолчанию ({', '.join(DEFAULT_CAMPAIGN_FIELDS)}); повторяемая."

COLUMNS = [
    ("Id", "Id"),
    ("Название", "Name"),
    ("Тип", "Type"),
    ("Состояние", "State"),
    ("Статус", "Status"),
    ("Бюджет/день ₽", lambda c: services.rubles((c.get("DailyBudget") or {}).get("Amount"))),
]


@app.command("list")
@output.guard
def list_campaigns(
    ctx: typer.Context,
    ids: list[int] = typer.Option(None, "--id", help="Только эти кампании (повторяемая)."),
    states: list[State] = typer.Option(None, "--state", help="Фильтр по состоянию (повторяемая)."),
    types: list[str] = typer.Option(
        None, "--type", help="Фильтр по типу: TEXT_CAMPAIGN, UNIFIED_CAMPAIGN, SMART_CAMPAIGN… (повторяемая)."
    ),
    fields: list[str] = typer.Option(None, "--field", help=_FIELDS_HELP),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Список кампаний с фильтрами по Id, состоянию и типу.

    --json: {"ok": true, "count": N, "campaigns": [{Id, Name, Type, State, Status, DailyBudget, …}]};
    суммы — в микроединицах валюты, как в API.

    Example: {cli} campaigns list --state ON
    """
    criteria: dict[str, Any] = {}
    if ids:
        criteria["Ids"] = ids
    if states:
        criteria["States"] = [s.value for s in states]
    if types:
        criteria["Types"] = types
    items = services.run(
        services.direct(ctx.obj).list_campaigns(field_names=fields or None, selection_criteria=criteria)
    )
    emit_list(ctx, "campaigns", items, COLUMNS, title="Кампании")


@app.command("get")
@output.guard
def get_campaign(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(..., help="Id кампании."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Одна кампания по Id: общие поля (набор как у `campaigns list`).

    --json: {"ok": true, "campaign": {...}}; нет такой кампании — INVALID_ARGUMENTS.

    Example: {cli} campaigns get 12345 --json
    """
    campaign = services.run(services.direct(ctx.obj).get_campaign(campaign_id))
    if campaign is None:
        raise InvalidArguments(f"Кампания {campaign_id} не найдена (или нет доступа в этом кабинете).")
    emit_object(ctx, "campaign", campaign, title=f"Кампания {campaign_id}")


@app.command("suspend")
@output.guard
def suspend(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Остановить показы кампаний.

    Example: {cli} campaigns suspend 12345 67890 --confirm
    """
    _ids_mutation(ctx, "suspend", "Остановить", ids, confirm)


@app.command("resume")
@output.guard
def resume(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Возобновить показы остановленных кампаний.

    Example: {cli} campaigns resume 12345 --confirm
    """
    _ids_mutation(ctx, "resume", "Возобновить", ids, confirm)


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
    """Архивировать кампании (должны быть остановлены и без остатка средств).

    Example: {cli} campaigns archive 12345 --confirm
    """
    _ids_mutation(ctx, "archive", "Архивировать", ids, confirm)


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
    """Вернуть кампании из архива.

    Example: {cli} campaigns unarchive 12345 --confirm
    """
    _ids_mutation(ctx, "unarchive", "Разархивировать", ids, confirm)


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
    """Удалить кампании — необратимо; удалить можно только черновики и кампании без показов.

    Example: {cli} campaigns delete 12345 --dry-run
    """
    _ids_mutation(ctx, "delete", "Удалить", ids, confirm)


def _ids_mutation(ctx: typer.Context, method: str, verb: str, ids: list[int], confirm: bool) -> None:
    mutate(
        ctx,
        title=f"{verb} кампании {', '.join(map(str, ids))}",
        service="campaigns",
        method=method,
        params={"SelectionCriteria": {"Ids": ids}},
        confirm=confirm,
    )


@app.command("update")
@output.guard
def update(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(..., help="Id кампании."),
    name: str = typer.Option(None, "--name", help="Новое название."),
    start_date: str = typer.Option(None, "--start-date", help="Дата начала, YYYY-MM-DD."),
    end_date: str = typer.Option(None, "--end-date", help="Дата окончания, YYYY-MM-DD; пустая строка — снять."),
    daily_budget: float = typer.Option(None, "--daily-budget", help="Дневной бюджет, ₽."),
    budget_mode: BudgetMode = typer.Option(
        BudgetMode.STANDARD,
        "--budget-mode",
        help="Режим дневного бюджета: STANDARD — равномерно, DISTRIBUTED — быстро.",
    ),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить общие параметры кампании: название, даты, дневной бюджет.

    Стратегию и настройки типа меняет `campaigns update-json`.

    Example: {cli} campaigns update 12345 --name 'Весна 2026' --daily-budget 2000 --dry-run
    """
    item: dict[str, Any] = {"Id": campaign_id}
    if name:
        item["Name"] = name
    if start_date:
        item["StartDate"] = start_date
    if end_date is not None:
        item["EndDate"] = end_date or None
    if daily_budget is not None:
        item["DailyBudget"] = {"Amount": services.micros(daily_budget), "Mode": budget_mode.value}
    if len(item) == 1:
        raise InvalidArguments("Нечего менять: укажите --name, --start-date, --end-date или --daily-budget.")
    mutate(
        ctx,
        title=f"Изменить кампанию {campaign_id}",
        service="campaigns",
        method="update",
        params={"Campaigns": [item]},
        confirm=confirm,
    )


@app.command("set-budget")
@output.guard
def set_budget(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(..., help="Id кампании."),
    amount: float = typer.Argument(..., help="Дневной бюджет, ₽."),
    mode: BudgetMode = typer.Option(BudgetMode.STANDARD, "--mode", help="STANDARD — равномерно, DISTRIBUTED — быстро."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Задать дневной бюджет кампании в рублях.

    Example: {cli} campaigns set-budget 12345 1500 --confirm
    """
    item = {"Id": campaign_id, "DailyBudget": {"Amount": services.micros(amount), "Mode": mode.value}}
    mutate(
        ctx,
        title=f"Дневной бюджет {amount:g} ₽ ({mode.value}) для кампании {campaign_id}",
        service="campaigns",
        method="update",
        params={"Campaigns": [item]},
        confirm=confirm,
    )


@app.command("set-negative-keywords")
@output.guard
def set_negative_keywords(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(..., help="Id кампании."),
    words: list[str] = typer.Option(None, "--word", "-w", help="Минус-фраза (повторяемая)."),
    from_file: str = typer.Option(None, "--from-file", help="Файл с минус-фразами, по одной в строке."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Заменить минус-фразы кампании: переданный список целиком заменяет текущий.

    Example: {cli} campaigns set-negative-keywords 12345 -w бесплатно -w скачать --dry-run
    """
    phrases = read_lines(words, from_file)
    if not phrases:
        raise InvalidArguments("Укажите минус-фразы: --word или --from-file.")
    mutate(
        ctx,
        title=f"Минус-фразы кампании {campaign_id}: {len(phrases)} шт.",
        service="campaigns",
        method="update",
        params={"Campaigns": [{"Id": campaign_id, "NegativeKeywords": {"Items": phrases}}]},
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
    """Создать кампании из JSON: список CampaignAddItem или {"Campaigns": [...]}.

    Example: {cli} campaigns add-json --from-json campaigns.json --dry-run
    """
    _json_mutation(ctx, "add", "Создать", from_json, confirm)


@app.command("update-json")
@output.guard
def update_json(
    ctx: typer.Context,
    from_json: str = FromJsonOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить кампании из JSON: список CampaignUpdateItem (с Id) или {"Campaigns": [...]}.

    Так меняются стратегия, настройки и поля блока типа (TextCampaign, UnifiedCampaign…).

    Example: {cli} campaigns update-json --from-json update.json --dry-run
    """
    _json_mutation(ctx, "update", "Изменить", from_json, confirm)


def _json_mutation(ctx: typer.Context, method: str, verb: str, path: str, confirm: bool) -> None:
    data = read_json(path)
    items = data.get("Campaigns") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise InvalidArguments('Ожидается непустой список кампаний или {"Campaigns": [...]}.')
    mutate(
        ctx,
        title=f"{verb} кампании: {len(items)} шт.",
        service="campaigns",
        method=method,
        params={"Campaigns": items},
        confirm=confirm,
    )
