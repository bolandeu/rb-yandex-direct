"""`yd campaigns` — кампании (сервис Campaigns)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import typer

from .. import output
from ..core import services
from ..core.campaign_payloads import CAMPAIGN_TYPES, CampaignSpec, campaign_add_item
from ..core.errors import InvalidArguments
from ..core.strategy import CAMPAIGN_BLOCKS, bidding_strategy
from ..providers.direct import DEFAULT_CAMPAIGN_FIELDS
from . import _strategy as st
from ._common import FromJsonOption, IdsArgument, emit_list, emit_object, mutate, read_json, read_lines

app = output.group("Кампании: список, создание, изменение, стратегия, статусы, бюджет, минус-фразы.")


class State(StrEnum):
    ON = "ON"
    OFF = "OFF"
    SUSPENDED = "SUSPENDED"
    ENDED = "ENDED"
    CONVERTED = "CONVERTED"
    ARCHIVED = "ARCHIVED"


class Status(StrEnum):
    ACCEPTED = "ACCEPTED"
    DRAFT = "DRAFT"
    MODERATION = "MODERATION"
    REJECTED = "REJECTED"


class PaymentStatus(StrEnum):
    ALLOWED = "ALLOWED"
    DISALLOWED = "DISALLOWED"


class CampaignKind(StrEnum):
    TEXT = "text"
    UNIFIED = "unified"
    DYNAMIC = "dynamic"
    SMART = "smart"
    MOBILE_APP = "mobile-app"
    CPM_BANNER = "cpm-banner"


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
    statuses: list[Status] = typer.Option(None, "--status", help="Фильтр по статусу модерации (повторяемая)."),
    payment: list[PaymentStatus] = typer.Option(
        None, "--payment-status", help="Фильтр по возможности оплаты: ALLOWED, DISALLOWED (повторяемая)."
    ),
    types: list[str] = typer.Option(
        None, "--type", help="Фильтр по типу: TEXT_CAMPAIGN, UNIFIED_CAMPAIGN, SMART_CAMPAIGN… (повторяемая)."
    ),
    fields: list[str] = typer.Option(None, "--field", help=_FIELDS_HELP),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Список кампаний с фильтрами по Id, состоянию, статусу, оплате и типу.

    --json: {"ok": true, "count": N, "campaigns": [{Id, Name, Type, State, Status, DailyBudget, …}]};
    суммы — в микроединицах валюты, как в API.

    Example: {cli} campaigns list --state ON
    """
    criteria: dict[str, Any] = {}
    if ids:
        criteria["Ids"] = ids
    if states:
        criteria["States"] = [s.value for s in states]
    if statuses:
        criteria["Statuses"] = [s.value for s in statuses]
    if payment:
        criteria["StatusesPayment"] = [s.value for s in payment]
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
    """Кампания целиком: общие поля и блок её типа (стратегия, настройки, счётчики, цели, минус-фразы).

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


@app.command("add")
@output.guard
def add(
    ctx: typer.Context,
    kind: CampaignKind = typer.Argument(
        ..., help="Тип кампании: text, unified, dynamic, smart, mobile-app, cpm-banner."
    ),
    name: str = typer.Option(..., "--name", help="Название кампании."),
    start_date: str = typer.Option(None, "--start-date", help="Дата начала, YYYY-MM-DD (по умолчанию сегодня)."),
    end_date: str = typer.Option(None, "--end-date", help="Дата окончания, YYYY-MM-DD."),
    daily_budget: float = typer.Option(None, "--daily-budget", help="Дневной бюджет, ₽ (для ручных стратегий)."),
    budget_mode: BudgetMode = typer.Option(BudgetMode.STANDARD, "--budget-mode", help="Режим дневного бюджета."),
    search_strategy: str = typer.Option(
        None,
        "--search-strategy",
        help="Стратегия на поиске: HIGHEST_POSITION, WB_MAXIMUM_CLICKS, AVERAGE_CPA, SERVING_OFF…",
    ),
    network_strategy: str = typer.Option(
        None, "--network-strategy", help="Стратегия в сетях: SERVING_OFF, NETWORK_DEFAULT, WB_MAXIMUM_CLICKS…"
    ),
    weekly_budget: float = st.WeeklyBudgetOption,
    bid_ceiling: float = st.BidCeilingOption,
    average_cpc: float = st.AverageCpcOption,
    average_cpa: float = st.AverageCpaOption,
    cpa: float = st.CpaOption,
    goal_id: int = st.GoalIdOption,
    crr: int = st.CrrOption,
    clicks_per_week: int = st.ClicksPerWeekOption,
    limit_percent: int = st.LimitPercentOption,
    average_cpi: float = st.AverageCpiOption,
    average_cpm: float = st.AverageCpmOption,
    average_cpv: float = st.AverageCpvOption,
    spend_limit: float = st.SpendLimitOption,
    placements: list[str] = typer.Option(
        None, "--placement", help="Площадка поиска ИМЯ=YES|NO: SearchResults, ProductGallery, DynamicPlaces, Maps…"
    ),
    settings: list[str] = typer.Option(None, "--setting", help="Настройка ИМЯ=YES|NO, например ADD_METRICA_TAG=YES."),
    counter_ids: list[int] = typer.Option(None, "--counter-id", help="Счётчик Метрики (повторяемая; смарт — один)."),
    priority_goals: list[str] = typer.Option(
        None, "--priority-goal", help="Ключевая цель ЦЕЛЬ=ЦЕННОСТЬ_₽ (повторяемая; нужна для *_MULTIPLE_GOALS)."
    ),
    words: list[str] = typer.Option(None, "--negative-keyword", "-w", help="Минус-фраза кампании (повторяемая)."),
    blocked_ips: list[str] = typer.Option(None, "--blocked-ip", help="Запрещённый IP (повторяемая)."),
    excluded_sites: list[str] = typer.Option(None, "--excluded-site", help="Запрещённая площадка (повторяемая)."),
    tracking_params: str = typer.Option(None, "--tracking-params", help="UTM-метки для всех ссылок кампании."),
    attribution_model: str = typer.Option(
        None, "--attribution-model", help="Модель атрибуции: LC, LSC, FC, LYDC, LSCCD, FCCD, LYDCCD, AUTO."
    ),
    time_zone: str = typer.Option(None, "--time-zone", help="Часовой пояс, например Europe/Moscow."),
    frequency_cap: str = typer.Option(
        None, "--frequency-cap", help="Частота показов ПОКАЗЫ/ДНИ (cpm-banner), например 3/7."
    ),
    video_target: str = typer.Option(None, "--video-target", help="Цель видео (cpm-banner): VIEWS или CLICKS."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать кампанию нужного типа из опций: стратегия, бюджет, настройки, счётчики, цели.

    Без стратегии text/unified/dynamic/mobile-app создаются с ручными ставками на поиске
    (HIGHEST_POSITION) без сетей; smart и cpm-banner требуют стратегию явно. Параметры
    стратегии (--weekly-budget, --goal-id, --average-cpa…) идут в блок той площадки, чья
    стратегия их принимает; лишний или недостающий параметр — INVALID_ARGUMENTS до запроса.
    Чего нет в опциях (пакетные стратегии, AVERAGE_ROI, временной таргетинг) — `campaigns
    add-json`. --json: как у изменяющих команд, `ids` — Id созданной кампании.

    \b
    Ещё примеры:
      {cli} campaigns add unified --name Лиды --search-strategy AVERAGE_CPA --network-strategy AVERAGE_CPA --average-cpa 800 --goal-id 12345 --counter-id 987 --dry-run
      {cli} campaigns add smart --name Фид --search-strategy AVERAGE_CPC_PER_CAMPAIGN --network-strategy NETWORK_DEFAULT --average-cpc 25 --counter-id 987 --dry-run

    Example: {cli} campaigns add text --name 'Весна 2026' --search-strategy WB_MAXIMUM_CLICKS --weekly-budget 10000 --dry-run
    """
    campaign_type = CAMPAIGN_TYPES[kind.value]
    spec = CampaignSpec(
        name=name,
        start_date=start_date,
        end_date=end_date,
        daily_budget=daily_budget,
        budget_mode=budget_mode.value,
        negative_keywords=words or [],
        blocked_ips=blocked_ips or [],
        excluded_sites=excluded_sites or [],
        time_zone=time_zone,
        search_strategy=search_strategy,
        network_strategy=network_strategy,
        strategy=st.params(
            weekly_budget,
            bid_ceiling,
            average_cpc,
            average_cpa,
            cpa,
            goal_id,
            crr,
            clicks_per_week,
            limit_percent,
            average_cpi,
            average_cpm,
            average_cpv,
            spend_limit,
        ),
        placements=placements or [],
        settings=settings or [],
        counter_ids=counter_ids or [],
        priority_goals=priority_goals or [],
        tracking_params=tracking_params,
        attribution_model=attribution_model,
        frequency_cap=frequency_cap,
        video_target=video_target,
    )
    mutate(
        ctx,
        title=f"Создать кампанию «{name}» ({campaign_type})",
        service="campaigns",
        method="add",
        params={"Campaigns": [campaign_add_item(campaign_type, spec)]},
        confirm=confirm,
    )


@app.command("set-strategy")
@output.guard
def set_strategy(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(..., help="Id кампании."),
    campaign_type: str = typer.Option(
        None, "--campaign-type", help="Тип кампании (TEXT_CAMPAIGN…); по умолчанию узнаётся запросом campaigns.get."
    ),
    search_strategy: str = typer.Option(None, "--search-strategy", help="Новая стратегия на поиске."),
    network_strategy: str = typer.Option(None, "--network-strategy", help="Новая стратегия в сетях."),
    weekly_budget: float = st.WeeklyBudgetOption,
    bid_ceiling: float = st.BidCeilingOption,
    average_cpc: float = st.AverageCpcOption,
    average_cpa: float = st.AverageCpaOption,
    cpa: float = st.CpaOption,
    goal_id: int = st.GoalIdOption,
    crr: int = st.CrrOption,
    clicks_per_week: int = st.ClicksPerWeekOption,
    limit_percent: int = st.LimitPercentOption,
    average_cpi: float = st.AverageCpiOption,
    average_cpm: float = st.AverageCpmOption,
    average_cpv: float = st.AverageCpvOption,
    spend_limit: float = st.SpendLimitOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Сменить стратегию кампании или её параметры (бюджет, цель, цену конверсии).

    Задайте стратегию площадки (--search-strategy/--network-strategy) и её параметры;
    незаданная площадка не меняется. Тип кампании берётся из campaigns.get, если не передан
    --campaign-type (тогда и --dry-run делает один запрос на чтение).

    Example: {cli} campaigns set-strategy 12345 --campaign-type TEXT_CAMPAIGN --search-strategy WB_MAXIMUM_CLICKS --weekly-budget 7000 --dry-run
    """
    if not (search_strategy or network_strategy):
        raise InvalidArguments("Укажите --search-strategy и/или --network-strategy.")
    if campaign_type is None:
        found = services.run(services.direct(ctx.obj).get_campaign(campaign_id, field_names=["Id", "Type"]))
        if found is None:
            raise InvalidArguments(f"Кампания {campaign_id} не найдена (или нет доступа в этом кабинете).")
        campaign_type = found["Type"]
    campaign_type = campaign_type.upper()
    if campaign_type not in CAMPAIGN_BLOCKS:
        raise InvalidArguments(f"Тип кампании {campaign_type}? Варианты: {', '.join(CAMPAIGN_BLOCKS)}.")
    strategy = bidding_strategy(
        campaign_type,
        search_strategy,
        network_strategy,
        st.params(
            weekly_budget,
            bid_ceiling,
            average_cpc,
            average_cpa,
            cpa,
            goal_id,
            crr,
            clicks_per_week,
            limit_percent,
            average_cpi,
            average_cpm,
            average_cpv,
            spend_limit,
        ),
        update=True,
    )
    mutate(
        ctx,
        title=f"Стратегия кампании {campaign_id}",
        service="campaigns",
        method="update",
        params={"Campaigns": [{"Id": campaign_id, CAMPAIGN_BLOCKS[campaign_type]: {"BiddingStrategy": strategy}}]},
        confirm=confirm,
    )
