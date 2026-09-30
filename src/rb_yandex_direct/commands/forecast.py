"""`yd forecast` — прогноз бюджета по фразам (API Директа v4 Live: CreateNewForecast и др.)."""

from __future__ import annotations

from typing import Any

import typer

from .. import output
from ..core.errors import InvalidArguments
from . import _live
from ._common import emit_list, table

app = output.group("Прогноз бюджета через API Директа v4: показы, клики, цены клика по фразам.")

PhrasesArgument = typer.Argument(..., help="Ключевые фразы (до 100).")
RegionOption = typer.Option(None, "--region", "-r", help="Id региона (повторяемая); минус — исключить.")
MinusOption = typer.Option(None, "--minus-word", "-m", help="Минус-слово для всех фраз (повторяемая).")
AuctionOption = typer.Option(False, "--auction-bids", help="Добавить ставки аукциона по позициям (AuctionBids=Yes).")
ForecastIdArgument = typer.Argument(..., help="Id прогноза (из `forecast create` / `forecast list`).")

PHRASE_COLUMNS = [
    ("Фраза", "Phrase"),
    ("Показы", "Shows"),
    ("Клики", "Clicks"),
    ("Клики 1-е место", "FirstPlaceClicks"),
    ("Клики спец", "PremiumClicks"),
    ("CTR %", "CTR"),
    ("Цена min", "Min"),
    ("Цена спец max", "PremiumMax"),
]


def _create_param(
    phrases: list[str], regions: list[int] | None, currency: str, minus: list[str] | None, auction: bool
) -> dict:
    if len(phrases) > 100:
        raise InvalidArguments("Не больше 100 фраз в одном прогнозе.")
    param: dict[str, Any] = {
        "Phrases": phrases,
        "Currency": currency.upper(),
        "AuctionBids": "Yes" if auction else "No",
    }
    if regions:
        param["GeoID"] = regions
    if minus:
        param["CommonMinusWords"] = minus
    return param


def _emit_forecast(ctx: typer.Context, forecast_id: int, forecast: dict) -> None:
    def render(_: dict) -> None:
        rows = forecast.get("Phrases") or []
        output.human.console.print(table(f"Прогноз {forecast_id} ({len(rows)})", rows, PHRASE_COLUMNS))
        common = forecast.get("Common") or {}
        if common:
            output.human.key_values("Итого", common)

    output.emit_success(ctx, {"forecast_id": forecast_id, "forecast": forecast}, render)


@app.command("create")
@output.guard
def create(
    ctx: typer.Context,
    phrases: list[str] = PhrasesArgument,
    regions: list[int] = RegionOption,
    currency: str = _live.CurrencyOption,
    minus_words: list[str] = MinusOption,
    auction_bids: bool = AuctionOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Запустить расчёт прогноза бюджета (CreateNewForecast); вернуть его Id.

    Прогноз готовится до минуты: статус — `forecast list`, данные — `forecast get`.
    --json: {"ok": true, "forecast_id": N}.

    Example: {cli} forecast create 'купить диван' 'диван недорого' -r 213
    """
    param = _create_param(phrases, regions, currency, minus_words, auction_bids)
    forecast_id = _live.call(ctx, "CreateNewForecast", param)
    output.emit_success(ctx, {"forecast_id": forecast_id}, lambda d: output.human.echo(f"Прогноз: {d['forecast_id']}"))


@app.command("list")
@output.guard
def list_forecasts(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Прогнозы на сервере (до пяти) и их статус: Done, Pending, Failed.

    --json: {"ok": true, "count": N, "forecasts": [{ForecastID, StatusForecast}]}.

    Example: {cli} forecast list --json
    """
    items = _live.call(ctx, "GetForecastList") or []
    emit_list(ctx, "forecasts", items, [("Id", "ForecastID"), ("Статус", "StatusForecast")], title="Прогнозы")


@app.command("get")
@output.guard
def get(
    ctx: typer.Context,
    forecast_id: int = ForecastIdArgument,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Готовый прогноз: по каждой фразе показы, клики, CTR и цены клика, плюс итог (Common).

    Цены — в валюте прогноза (не в микроединицах). --json: {"ok": true, "forecast_id": N,
    "forecast": {"Phrases": [{Phrase, Shows, Clicks, FirstPlaceClicks, PremiumClicks, CTR, Min, Max,
    PremiumMin, PremiumMax, …}], "Common": {…}}}.

    Example: {cli} forecast get 12345 --json
    """
    _emit_forecast(ctx, forecast_id, _live.call(ctx, "GetForecast", forecast_id) or {})


@app.command("delete")
@output.guard
def delete(
    ctx: typer.Context,
    forecast_id: int = ForecastIdArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить прогноз с сервера — освободить место (их не больше пяти).

    Example: {cli} forecast delete 12345 --confirm
    """
    _live.mutate(
        ctx, title=f"Удалить прогноз {forecast_id}", method="DeleteForecastReport", param=forecast_id, confirm=confirm
    )


@app.command("run")
@output.guard
def run(
    ctx: typer.Context,
    phrases: list[str] = PhrasesArgument,
    regions: list[int] = RegionOption,
    currency: str = _live.CurrencyOption,
    minus_words: list[str] = MinusOption,
    auction_bids: bool = AuctionOption,
    timeout: float = typer.Option(120.0, "--timeout", help="Сколько секунд ждать готовности прогноза."),
    keep: bool = typer.Option(False, "--keep", help="Не удалять прогноз с сервера после получения."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Всё сразу: создать прогноз, дождаться готовности, получить и удалить с сервера.

    --json — как у `forecast get`.

    Example: {cli} forecast run 'купить диван' -r 213 --json
    """
    param = _create_param(phrases, regions, currency, minus_words, auction_bids)
    forecast_id = _live.call(ctx, "CreateNewForecast", param)
    _live.wait_ready(ctx, "GetForecastList", "ForecastID", "StatusForecast", forecast_id, timeout)
    forecast = _live.call(ctx, "GetForecast", forecast_id) or {}
    if not keep:
        _live.call(ctx, "DeleteForecastReport", forecast_id)
    _emit_forecast(ctx, forecast_id, forecast)
