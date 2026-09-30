"""`yd wordstat` — статистика поисковых запросов Wordstat через API Директа v4 Live.

Официальный путь через кабинет Директа (баллы API, до 1000 фраз в сутки на пользователя,
до 5 отчётов на сервере, хранятся 5 часов). Отдельный инструмент `wordstat` из tools
берёт частоты у сторонних провайдеров (XML River, XMLStock) без кабинета Директа.
"""

from __future__ import annotations

from typing import Any

import typer

from .. import output
from ..core.errors import InvalidArguments
from . import _live
from ._common import emit_list, table

app = output.group(
    "Wordstat через API Директа v4: отчёты о поисковых запросах (create/list/get/delete, run — всё сразу)."
)

PhrasesArgument = typer.Argument(..., help="Ключевые фразы (до 10), можно с минус-словами: 'диван -кожаный'.")
RegionOption = typer.Option(
    None, "--region", "-r", help="Id региона (повторяемая); минус — исключить: -r 1 -r -219. Нет — все регионы."
)
ReportIdArgument = typer.Argument(..., help="Id отчёта (из `wordstat create` / `wordstat list`).")


def _create_param(phrases: list[str], regions: list[int] | None) -> dict:
    if len(phrases) > 10:
        raise InvalidArguments("Не больше 10 фраз в одном отчёте Wordstat.")
    param: dict[str, Any] = {"Phrases": phrases}
    if regions:
        param["GeoID"] = regions
    return param


def _rows(report: list[dict]) -> list[dict]:
    """Плоские строки для таблицы: исходная фраза, запрос, показы, тип (with/also)."""
    rows = []
    for item in report or []:
        for kind, key in (("with", "SearchedWith"), ("also", "SearchedAlso")):
            rows += [{"Seed": item.get("Phrase"), "Kind": kind, **row} for row in item.get(key) or []]
    return rows


ROW_COLUMNS = [("Фраза", "Seed"), ("Запрос", "Phrase"), ("Показы/мес", "Shows"), ("Тип", "Kind")]


def _emit_report(ctx: typer.Context, report_id: int, report: list[dict]) -> None:
    rows = _rows(report)

    def render(_: dict) -> None:
        output.human.console.print(table(f"Wordstat, отчёт {report_id} ({len(rows)})", rows, ROW_COLUMNS))

    output.emit_success(ctx, {"report_id": report_id, "report": report}, render)


@app.command("create")
@output.guard
def create(
    ctx: typer.Context,
    phrases: list[str] = PhrasesArgument,
    regions: list[int] = RegionOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Запустить формирование отчёта Wordstat (CreateNewWordstatReport); вернуть его Id.

    Отчёт готовится до минуты: статус — `wordstat list`, данные — `wordstat get`.
    Расходует баллы API. --json: {"ok": true, "report_id": N}.

    Example: {cli} wordstat create 'купить диван' 'диван недорого' -r 213
    """
    report_id = _live.call(ctx, "CreateNewWordstatReport", _create_param(phrases, regions))
    output.emit_success(ctx, {"report_id": report_id}, lambda d: output.human.echo(f"Отчёт Wordstat: {d['report_id']}"))


@app.command("list")
@output.guard
def list_reports(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Отчёты Wordstat на сервере (до пяти) и их статус: Done, Pending, Failed.

    --json: {"ok": true, "count": N, "reports": [{ReportID, StatusReport}]}.

    Example: {cli} wordstat list --json
    """
    items = _live.call(ctx, "GetWordstatReportList") or []
    emit_list(ctx, "reports", items, [("Id", "ReportID"), ("Статус", "StatusReport")], title="Отчёты Wordstat")


@app.command("get")
@output.guard
def get(
    ctx: typer.Context,
    report_id: int = ReportIdArgument,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Готовый отчёт Wordstat: по каждой фразе — запросы с ней (SearchedWith) и похожие (SearchedAlso).

    --json: {"ok": true, "report_id": N, "report": [{Phrase, GeoID, SearchedWith: [{Phrase, Shows}],
    SearchedAlso: [...]}]}; Shows — число запросов за прошлый месяц.

    Example: {cli} wordstat get 12345 --json
    """
    _emit_report(ctx, report_id, _live.call(ctx, "GetWordstatReport", report_id) or [])


@app.command("delete")
@output.guard
def delete(
    ctx: typer.Context,
    report_id: int = ReportIdArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить отчёт Wordstat с сервера — освободить место (их не больше пяти; сами удаляются через 5 часов).

    Example: {cli} wordstat delete 12345 --confirm
    """
    _live.mutate(
        ctx,
        title=f"Удалить отчёт Wordstat {report_id}",
        method="DeleteWordstatReport",
        param=report_id,
        confirm=confirm,
    )


@app.command("run")
@output.guard
def run(
    ctx: typer.Context,
    phrases: list[str] = PhrasesArgument,
    regions: list[int] = RegionOption,
    timeout: float = typer.Option(120.0, "--timeout", help="Сколько секунд ждать готовности отчёта."),
    keep: bool = typer.Option(False, "--keep", help="Не удалять отчёт с сервера после получения."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Всё сразу: создать отчёт, дождаться готовности, получить и удалить с сервера.

    --json — как у `wordstat get`. Расходует баллы API (до 1000 фраз в сутки).

    Example: {cli} wordstat run 'купить диван' -r 213 --json
    """
    report_id = _live.call(ctx, "CreateNewWordstatReport", _create_param(phrases, regions))
    _live.wait_ready(ctx, "GetWordstatReportList", "ReportID", "StatusReport", report_id, timeout)
    report = _live.call(ctx, "GetWordstatReport", report_id) or []
    if not keep:
        _live.call(ctx, "DeleteWordstatReport", report_id)
    _emit_report(ctx, report_id, report)
