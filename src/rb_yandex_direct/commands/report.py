"""`yd report` — статистические отчёты (сервис Reports): пресеты и произвольный отчёт."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import typer

from .. import output
from ..core import services
from ..core.report_payloads import DATE_RANGE_TYPES, PROCESSING_MODES, REPORT_TYPES, ReportSpec, report_params
from ..providers.reports import PRESETS, Report, ReportsClient, report_name
from ._common import table

app = output.group("Отчёты: эффективность кампаний, объявлений, поисковых запросов, аккаунта и произвольные.")

DateRange = StrEnum("DateRange", {r: r for r in DATE_RANGE_TYPES})
ProcessingMode = StrEnum("ProcessingMode", {m: m for m in PROCESSING_MODES})

DateFromOption = typer.Option(None, "--date-from", help="Начало периода, YYYY-MM-DD (вместе с --date-to).")
DateToOption = typer.Option(None, "--date-to", help="Конец периода, YYYY-MM-DD.")
RangeOption = typer.Option(
    None,
    "--range",
    help="Готовый период вместо дат: LAST_7_DAYS, LAST_30_DAYS, LAST_MONTH… (по умолчанию LAST_30_DAYS).",
)
CampaignOption = typer.Option(None, "--campaign", help="Только эти кампании (повторяемая).")
AdGroupOption = typer.Option(None, "--adgroup", help="Только эти группы (повторяемая).")
FilterOption = typer.Option(
    None, "--filter", help="Фильтр Поле:ОПЕРАТОР:знач1,знач2, например Clicks:GREATER_THAN:10 (повторяемая)."
)
OrderOption = typer.Option(None, "--order-by", help="Сортировка Поле[:ASC|DESC] (повторяемая).")
GoalOption = typer.Option(None, "--goal", help="Цель Метрики для конверсий (повторяемая, до 10).")
AttributionOption = typer.Option(
    None, "--attribution-model", help="Модель атрибуции: LC, LSC, FC, LYDC, LSCCD, FCCD, LYDCCD, AUTO (повторяемая)."
)
VatOption = typer.Option(True, "--vat/--no-vat", help="Суммы с НДС или без.")
DiscountOption = typer.Option(True, "--discount/--no-discount", help="Суммы с учётом скидки или без.")
LimitOption = typer.Option(None, "--limit", help="Не больше N строк.")
ModeOption = typer.Option(
    ProcessingMode.auto, "--mode", help="Режим формирования: auto, online (сразу) или offline (в очереди)."
)
MicrosOption = typer.Option(
    False, "--micros", help="Деньги в микроединицах, как в остальном API (по умолчанию — рубли)."
)


def _emit(ctx: typer.Context, report: Report, params: dict[str, Any]) -> None:
    rows = report.parse()

    def render(_: dict) -> None:
        if not rows:
            output.human.echo("Отчёт пуст.")
            return
        columns = [(name, name) for name in rows[0]]
        output.human.console.print(table(f"{params['ReportType']} ({len(rows)})", rows, columns))

    output.emit_success(
        ctx,
        {
            "report_type": params["ReportType"],
            "report_name": params["ReportName"],
            "request_id": report.request_id,
            "count": len(rows),
            "rows": rows,
        },
        render_human=render,
    )


def _run(ctx: typer.Context, spec: ReportSpec, mode: str, micros: bool) -> None:
    params = report_params(spec)
    params.setdefault("ReportName", report_name(params))
    # Заголовки не зависят от токена: dry-run работает и без входа.
    headers = ReportsClient("", **services.connection(ctx.obj)).headers(processing_mode=mode, money_in_micros=micros)
    if output.is_dry_run(ctx):
        output.emit_success(
            ctx,
            {"dry_run": True, "headers": headers, "params": params},
            render_human=lambda d: output.human.console.print_json(data=d["params"]),
        )
        return
    output.vecho(ctx, f"Отчёт {params['ReportName']}: жду готовности…")
    _emit(ctx, services.run(services.reports(ctx.obj).fetch(params, headers)), params)


def _preset(
    ctx: typer.Context,
    preset: str,
    date_from: str | None,
    date_to: str | None,
    date_range: DateRange | None,
    campaign_ids: list[int] | None,
    goals: list[int] | None,
    attribution: list[str] | None,
    vat: bool,
    micros: bool,
) -> None:
    report_type, fields = PRESETS[preset]
    spec = ReportSpec(
        report_type=report_type,
        fields=fields,
        date_from=date_from,
        date_to=date_to,
        date_range=date_range.value if date_range else None,
        campaign_ids=campaign_ids or [],
        goals=goals or [],
        attribution_models=attribution or [],
        include_vat=vat,
    )
    _run(ctx, spec, "auto", micros)


@app.command("campaigns")
@output.guard
def campaigns(
    ctx: typer.Context,
    date_from: str = DateFromOption,
    date_to: str = DateToOption,
    date_range: DateRange = RangeOption,
    campaign_ids: list[int] = CampaignOption,
    goals: list[int] = GoalOption,
    attribution: list[str] = AttributionOption,
    vat: bool = VatOption,
    micros: bool = MicrosOption,
    dry_run: bool = output.DryRunOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Эффективность кампаний по дням: показы, клики, расход, CTR, CPC, конверсии, отказы.

    --json: {"ok": true, "report_type", "report_name", "request_id", "count": N, "rows": [{Поле: значение}]};
    числа — числами, `--` API — null, деньги — в рублях (--micros — в микроединицах).
    --dry-run печатает запрос к API без выполнения.

    Example: {cli} report campaigns --date-from 2026-09-01 --date-to 2026-09-27
    """
    _preset(ctx, "campaigns", date_from, date_to, date_range, campaign_ids, goals, attribution, vat, micros)


@app.command("ads")
@output.guard
def ads(
    ctx: typer.Context,
    date_from: str = DateFromOption,
    date_to: str = DateToOption,
    date_range: DateRange = RangeOption,
    campaign_ids: list[int] = CampaignOption,
    goals: list[int] = GoalOption,
    attribution: list[str] = AttributionOption,
    vat: bool = VatOption,
    micros: bool = MicrosOption,
    dry_run: bool = output.DryRunOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Эффективность объявлений по дням: показы, клики, расход, CTR, CPC, конверсии.

    --json: как у `report campaigns`.

    Example: {cli} report ads --range LAST_7_DAYS --campaign 12345 --json
    """
    _preset(ctx, "ads", date_from, date_to, date_range, campaign_ids, goals, attribution, vat, micros)


@app.command("queries")
@output.guard
def queries(
    ctx: typer.Context,
    date_from: str = DateFromOption,
    date_to: str = DateToOption,
    date_range: DateRange = RangeOption,
    campaign_ids: list[int] = CampaignOption,
    goals: list[int] = GoalOption,
    attribution: list[str] = AttributionOption,
    vat: bool = VatOption,
    micros: bool = MicrosOption,
    dry_run: bool = output.DryRunOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Реальные поисковые запросы пользователей: по какой фразе и с каким типом соответствия был показ.

    Основа для минус-слов и новых ключевых фраз. --json: как у `report campaigns`.

    Example: {cli} report queries --date-from 2026-09-01 --date-to 2026-09-27 --campaign 12345
    """
    _preset(ctx, "queries", date_from, date_to, date_range, campaign_ids, goals, attribution, vat, micros)


@app.command("account")
@output.guard
def account(
    ctx: typer.Context,
    date_from: str = DateFromOption,
    date_to: str = DateToOption,
    date_range: DateRange = RangeOption,
    goals: list[int] = GoalOption,
    attribution: list[str] = AttributionOption,
    vat: bool = VatOption,
    micros: bool = MicrosOption,
    dry_run: bool = output.DryRunOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Итог по кабинету по дням: показы, клики, расход, CTR, CPC, конверсии, цена конверсии.

    --json: как у `report campaigns`.

    Example: {cli} report account --range LAST_MONTH
    """
    _preset(ctx, "account", date_from, date_to, date_range, None, goals, attribution, vat, micros)


@app.command("custom")
@output.guard
def custom(
    ctx: typer.Context,
    report_type: str = typer.Option(..., "--type", help="Тип отчёта (см. `report types`), например CUSTOM_REPORT."),
    fields: list[str] = typer.Option(..., "--field", help="Поле отчёта (повторяемая): Date, CampaignId, Clicks, Cost…"),
    date_from: str = DateFromOption,
    date_to: str = DateToOption,
    date_range: DateRange = RangeOption,
    campaign_ids: list[int] = CampaignOption,
    adgroup_ids: list[int] = AdGroupOption,
    filters: list[str] = FilterOption,
    order_by: list[str] = OrderOption,
    goals: list[int] = GoalOption,
    attribution: list[str] = AttributionOption,
    vat: bool = VatOption,
    discount: bool = DiscountOption,
    limit: int = LimitOption,
    name: str = typer.Option(None, "--name", help="Имя отчёта в очереди (по умолчанию — хэш параметров)."),
    mode: ProcessingMode = ModeOption,
    micros: bool = MicrosOption,
    dry_run: bool = output.DryRunOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Произвольный отчёт: любой тип, поля, фильтры, сортировка, цели и модели атрибуции.

    Какие поля допустимы в каком типе — в документации Reports (fields-list);
    несовместимые поля API отвергает кодом 4000. --json: как у `report campaigns`.

    \b
    Ещё примеры:
      {cli} report custom --type CRITERIA_PERFORMANCE_REPORT --field Criterion --field Clicks --field Cost --range LAST_7_DAYS --filter Clicks:GREATER_THAN:0 --order-by Cost:DESC --limit 50

    Example: {cli} report custom --type CUSTOM_REPORT --date-from 2026-09-01 --date-to 2026-09-27 --field Date --field Clicks --field Cost
    """
    spec = ReportSpec(
        report_type=report_type,
        fields=fields,
        date_from=date_from,
        date_to=date_to,
        date_range=date_range.value if date_range else None,
        campaign_ids=campaign_ids or [],
        adgroup_ids=adgroup_ids or [],
        filters=filters or [],
        order_by=order_by or [],
        goals=goals or [],
        attribution_models=attribution or [],
        include_vat=vat,
        include_discount=discount,
        limit=limit,
        name=name,
    )
    _run(ctx, spec, mode.value, micros)


@app.command("types")
@output.guard
def types(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Типы отчётов и готовые периоды (--range), которые принимает `report custom` (без запроса к API).

    Example: {cli} report types --json
    """
    output.emit_success(
        ctx,
        {"report_types": list(REPORT_TYPES), "date_ranges": list(DATE_RANGE_TYPES)},
        render_human=lambda d: output.human.echo(
            "Типы отчётов:\n  " + "\n  ".join(d["report_types"]) + "\nПериоды:\n  " + "\n  ".join(d["date_ranges"])
        ),
    )
