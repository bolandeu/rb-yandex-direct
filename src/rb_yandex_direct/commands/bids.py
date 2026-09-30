"""`yd bids` (сервис KeywordBids) и `yd bids-classic` (сервис Bids) — ставки фраз и автотаргетинга."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import typer

from .. import output
from ..core import services
from ..core.errors import InvalidArguments
from ._common import emit_list, mutate
from ._targeting import FieldOption, Priority, PriorityOption, ServingStatus, YesNo, scope_item, values

app = output.group("Ставки и торги по фразам и автотаргетингу (KeywordBids): просмотр, ручные ставки, автоподбор.")
classic_app = output.group(
    "Ставки через классический сервис Bids: цены позиций на поиске, прогноз охвата в сетях, автоподбор по позиции."
)

KeywordOption = typer.Option(None, "--keyword", help="Id фразы (или автотаргетинга).")
AdGroupOption = typer.Option(None, "--adgroup", help="Id группы — для всех её фраз.")
CampaignOption = typer.Option(None, "--campaign", help="Id кампании — для всех её фраз.")
KeywordsFilter = typer.Option(None, "--keyword", help="Фильтр по фразе (повторяемая).")
AdGroupsFilter = typer.Option(None, "--adgroup", help="Фильтр по группе (повторяемая).")
CampaignsFilter = typer.Option(None, "--campaign", help="Фильтр по кампании (повторяемая; у bids-classic — до 10).")
ServingFilter = typer.Option(None, "--serving-status", help="ELIGIBLE или RARELY_SERVED (повторяемая).")


def _require_filter(keywords: list[int] | None, adgroups: list[int] | None, campaigns: list[int] | None) -> None:
    if not (keywords or adgroups or campaigns):
        raise InvalidArguments("Укажите хотя бы один фильтр: --keyword, --adgroup или --campaign.")


def _rub(value: Any) -> float | None:
    return services.rubles(value) if isinstance(value, int) else None


KEYWORD_BID_COLUMNS = [
    ("Фраза", "KeywordId"),
    ("Группа", "AdGroupId"),
    ("Поиск ₽", lambda b: _rub((b.get("Search") or {}).get("Bid"))),
    ("Сети ₽", lambda b: _rub((b.get("Network") or {}).get("Bid"))),
    ("Приоритет", "StrategyPriority"),
    ("Показы", "ServingStatus"),
]


@app.command("list")
@output.guard
def list_bids(
    ctx: typer.Context,
    keywords: list[int] = KeywordsFilter,
    adgroups: list[int] = AdGroupsFilter,
    campaigns: list[int] = CampaignsFilter,
    serving: list[ServingStatus] = ServingFilter,
    fields: list[str] = FieldOption,
    search_fields: list[str] = typer.Option(
        None, "--search-field", help="Поле SearchFieldNames: Bid, AutotargetingSearchBidIsAuto, AuctionBids."
    ),
    network_fields: list[str] = typer.Option(None, "--network-field", help="Поле NetworkFieldNames: Bid, Coverage."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Ставки и торги по фразам: текущая ставка, аукцион на поиске (объём трафика → ставка/цена), охват в сетях.

    Нужен хотя бы один из --keyword, --adgroup, --campaign.
    --json: {"ok": true, "count": N, "bids": [{KeywordId, AdGroupId, CampaignId, ServingStatus,
    StrategyPriority, Search: {Bid, AutotargetingSearchBidIsAuto, AuctionBids}, Network: {Bid, Coverage}}]};
    суммы — в микроединицах валюты.

    Example: {cli} bids list --campaign 12345
    """
    _require_filter(keywords, adgroups, campaigns)
    items = services.run(
        services.direct(ctx.obj).get_keyword_bids(
            keyword_ids=keywords or None,
            adgroup_ids=adgroups or None,
            campaign_ids=campaigns or None,
            field_names=fields or None,
            serving_statuses=values(serving),
            search_field_names=search_fields or None,
            network_field_names=network_fields or None,
        )
    )
    emit_list(ctx, "bids", items, KEYWORD_BID_COLUMNS, title="Ставки")


@app.command("set")
@output.guard
def set_bids(
    ctx: typer.Context,
    keyword: int = KeywordOption,
    adgroup: int = AdGroupOption,
    campaign: int = CampaignOption,
    search_bid: float = typer.Option(None, "--search-bid", help="Ставка на поиске, ₽."),
    network_bid: float = typer.Option(None, "--network-bid", help="Ставка в сетях, ₽."),
    autotargeting_auto: YesNo = typer.Option(
        None, "--autotargeting-search-bid-is-auto", help="YES — ставка автотаргетинга на поиске подбирается сама."
    ),
    priority: Priority = PriorityOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Задать ставку (ручная стратегия) или приоритет (автостратегия) фразе, группе или кампании.

    Ровно одно из --keyword, --adgroup, --campaign; ставки — в рублях.

    Example: {cli} bids set --keyword 901 --search-bid 12.5 --dry-run
    """
    item = scope_item(keyword, adgroup, campaign, id_key="KeywordId")
    if search_bid is not None:
        item["SearchBid"] = services.micros(search_bid)
    if network_bid is not None:
        item["NetworkBid"] = services.micros(network_bid)
    if autotargeting_auto:
        item["AutotargetingSearchBidIsAuto"] = autotargeting_auto.value
    if priority:
        item["StrategyPriority"] = priority.value
    if len(item) == 1:
        raise InvalidArguments("Нечего менять: укажите --search-bid, --network-bid, --priority или автоставку.")
    mutate(
        ctx,
        title=f"Ставка {item}",
        service="keywordbids",
        method="set",
        params={"KeywordBids": [item]},
        confirm=confirm,
    )


@app.command("set-auto")
@output.guard
def set_auto(
    ctx: typer.Context,
    keyword: int = KeywordOption,
    adgroup: int = AdGroupOption,
    campaign: int = CampaignOption,
    target_traffic_volume: int = typer.Option(
        None, "--target-traffic-volume", help="Поиск: целевой объём трафика, 5–100 (100 — как у первого места)."
    ),
    target_coverage: int = typer.Option(None, "--target-coverage", help="Сети: целевой охват аудитории, 1–100 %."),
    increase_percent: int = typer.Option(None, "--increase-percent", help="Надбавка к рассчитанной ставке, 0–1000 %."),
    bid_ceiling: float = typer.Option(None, "--bid-ceiling", help="Максимальная ставка, ₽."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Однократно рассчитать и выставить ставки по правилу: объём трафика на поиске или охват в сетях.

    Ровно одно из --keyword, --adgroup, --campaign и одно из --target-traffic-volume,
    --target-coverage. Приоритет автостратегии — `bids set --priority`.

    Example: {cli} bids set-auto --campaign 12345 --target-traffic-volume 75 --bid-ceiling 40 --dry-run
    """
    if (target_traffic_volume is None) == (target_coverage is None):
        raise InvalidArguments("Укажите ровно одно: --target-traffic-volume (поиск) или --target-coverage (сети).")
    rule: dict[str, Any] = {}
    if increase_percent is not None:
        rule["IncreasePercent"] = increase_percent
    if bid_ceiling is not None:
        rule["BidCeiling"] = services.micros(bid_ceiling)
    if target_traffic_volume is not None:
        bidding_rule = {"SearchByTrafficVolume": {"TargetTrafficVolume": target_traffic_volume, **rule}}
    else:
        bidding_rule = {"NetworkByCoverage": {"TargetCoverage": target_coverage, **rule}}
    item = {**scope_item(keyword, adgroup, campaign, id_key="KeywordId"), "BiddingRule": bidding_rule}
    mutate(
        ctx,
        title=f"Автоподбор ставок {bidding_rule}",
        service="keywordbids",
        method="setAuto",
        params={"KeywordBids": [item]},
        confirm=confirm,
    )


# --- классический сервис Bids -------------------------------------------------------------------


class Position(StrEnum):
    PREMIUMFIRST = "PREMIUMFIRST"
    PREMIUMBLOCK = "PREMIUMBLOCK"
    FOOTERFIRST = "FOOTERFIRST"
    FOOTERBLOCK = "FOOTERBLOCK"
    P11 = "P11"
    P12 = "P12"
    P13 = "P13"
    P14 = "P14"
    P21 = "P21"
    P22 = "P22"
    P23 = "P23"
    P24 = "P24"


class CalculateBy(StrEnum):
    VALUE = "VALUE"
    DIFF = "DIFF"


class Scope(StrEnum):
    SEARCH = "SEARCH"
    NETWORK = "NETWORK"


CLASSIC_COLUMNS = [
    ("Фраза", "KeywordId"),
    ("Группа", "AdGroupId"),
    ("Поиск ₽", lambda b: _rub(b.get("Bid"))),
    ("Сети ₽", lambda b: _rub(b.get("ContextBid"))),
    ("Мин. цена ₽", lambda b: _rub(b.get("MinSearchPrice"))),
    ("Текущая цена ₽", lambda b: _rub(b.get("CurrentSearchPrice"))),
    ("Приоритет", "StrategyPriority"),
]


@classic_app.command("list")
@output.guard
def classic_list(
    ctx: typer.Context,
    keywords: list[int] = KeywordsFilter,
    adgroups: list[int] = AdGroupsFilter,
    campaigns: list[int] = CampaignsFilter,
    serving: list[ServingStatus] = ServingFilter,
    fields: list[str] = typer.Option(
        None,
        "--field",
        help="Поле FieldNames (повторяемая): Bid, ContextBid, CompetitorsBids, SearchPrices, ContextCoverage, "
        "MinSearchPrice, CurrentSearchPrice, AuctionBids, …",
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Ставки через сервис Bids: ставки, минимальная и текущая цена на поиске, цены позиций, охват в сетях.

    Нужен хотя бы один из --keyword, --adgroup, --campaign (кампаний — не больше 10).
    --json: {"ok": true, "count": N, "bids": [{KeywordId, AdGroupId, CampaignId, Bid, ContextBid,
    StrategyPriority, ServingStatus, MinSearchPrice, CurrentSearchPrice, …}]}; суммы — в микроединицах.

    Example: {cli} bids-classic list --campaign 12345 --field SearchPrices --field KeywordId
    """
    _require_filter(keywords, adgroups, campaigns)
    items = services.run(
        services.direct(ctx.obj).list_bids(
            keyword_ids=keywords or None,
            adgroup_ids=adgroups or None,
            campaign_ids=campaigns or None,
            field_names=fields or None,
            serving_statuses=values(serving),
        )
    )
    emit_list(ctx, "bids", items, CLASSIC_COLUMNS, title="Ставки (Bids)")


@classic_app.command("set")
@output.guard
def classic_set(
    ctx: typer.Context,
    keyword: int = KeywordOption,
    adgroup: int = AdGroupOption,
    campaign: int = CampaignOption,
    bid: float = typer.Option(None, "--bid", help="Ставка на поиске, ₽."),
    context_bid: float = typer.Option(None, "--context-bid", help="Ставка в сетях, ₽."),
    autotargeting_auto: YesNo = typer.Option(
        None, "--autotargeting-search-bid-is-auto", help="YES — ставка автотаргетинга на поиске подбирается сама."
    ),
    priority: Priority = PriorityOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Задать ставку или приоритет через сервис Bids (фраза, группа или кампания).

    Example: {cli} bids-classic set --keyword 901 --bid 12 --context-bid 5 --dry-run
    """
    item = scope_item(keyword, adgroup, campaign, id_key="KeywordId")
    if bid is not None:
        item["Bid"] = services.micros(bid)
    if context_bid is not None:
        item["ContextBid"] = services.micros(context_bid)
    if autotargeting_auto:
        item["AutotargetingSearchBidIsAuto"] = autotargeting_auto.value
    if priority:
        item["StrategyPriority"] = priority.value
    if len(item) == 1:
        raise InvalidArguments("Нечего менять: укажите --bid, --context-bid, --priority или автоставку.")
    mutate(ctx, title=f"Ставка {item}", service="bids", method="set", params={"Bids": [item]}, confirm=confirm)


@classic_app.command("set-auto")
@output.guard
def classic_set_auto(
    ctx: typer.Context,
    scopes: list[Scope] = typer.Option(..., "--scope", help="Где подбирать: SEARCH и/или NETWORK (повторяемая)."),
    keyword: int = KeywordOption,
    adgroup: int = AdGroupOption,
    campaign: int = CampaignOption,
    max_bid: float = typer.Option(None, "--max-bid", help="Максимальная ставка, ₽."),
    position: Position = typer.Option(None, "--position", help="Целевая позиция на поиске: P11…P24, PREMIUMBLOCK…"),
    increase_percent: int = typer.Option(None, "--increase-percent", help="Надбавка к цене позиции, %."),
    calculate_by: CalculateBy = typer.Option(
        None, "--calculate-by", help="VALUE — от цены позиции, DIFF — от разницы с соседней позицией."
    ),
    context_coverage: int = typer.Option(None, "--context-coverage", help="Целевой охват в сетях, %."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Однократно выставить ставки по позиции на поиске и/или охвату в сетях (bids.setAuto).

    Example: {cli} bids-classic set-auto --campaign 12345 --scope SEARCH --position P12 --max-bid 30 --dry-run
    """
    item: dict[str, Any] = {**scope_item(keyword, adgroup, campaign, id_key="KeywordId"), "Scope": values(scopes)}
    if max_bid is not None:
        item["MaxBid"] = services.micros(max_bid)
    if position:
        item["Position"] = position.value
    if increase_percent is not None:
        item["IncreasePercent"] = increase_percent
    if calculate_by:
        item["CalculateBy"] = calculate_by.value
    if context_coverage is not None:
        item["ContextCoverage"] = context_coverage
    mutate(
        ctx,
        title=f"Автоподбор ставок {item}",
        service="bids",
        method="setAuto",
        params={"Bids": [item]},
        confirm=confirm,
    )
