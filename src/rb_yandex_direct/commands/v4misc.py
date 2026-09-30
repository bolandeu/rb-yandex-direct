"""Прочие методы API Директа v4 Live: журнал событий, цели, метки, подсказки фраз, служебные.

Группы `events`, `goals`, `tags`, `v4` и команда `suggest`.
"""

from __future__ import annotations

from typing import Any

import typer

from .. import output
from ..core.errors import InvalidArguments
from . import _live
from ._common import emit_list

# --- events ---------------------------------------------------------------------------------

events_app = output.group("Журнал событий кабинета (API v4 GetEventsLog): модерация, деньги, остановки.")

EVENT_COLUMNS = [
    ("Время", "Timestamp"),
    ("Событие", "EventName"),
    ("Тип", "EventType"),
    ("Кампания", "CampaignID"),
    ("Объявление", "BannerID"),
    ("Описание", "TextDescription"),
]


@events_app.command("list")
@output.guard
def events_list(
    ctx: typer.Context,
    date_from: str = typer.Option(
        ..., "--from", help="С какого момента, ISO 8601: 2026-09-01 или 2026-09-01T00:00:00Z."
    ),
    date_to: str = typer.Option(None, "--to", help="По какой момент, ISO 8601; нет — по текущий."),
    currency: str = _live.CurrencyOption,
    campaigns: list[int] = typer.Option(None, "--campaign", help="Только эти кампании (повторяемая)."),
    banners: list[int] = typer.Option(None, "--banner", help="Только эти объявления (повторяемая)."),
    phrases: list[int] = typer.Option(None, "--phrase", help="Только эти фразы (повторяемая)."),
    accounts: list[int] = typer.Option(None, "--account", help="Только эти общие счета (повторяемая)."),
    event_types: list[str] = typer.Option(
        None, "--type", help="Тип события: MoneyIn, MoneyOut, BannerModerated, CampaignFinished… (повторяемая)."
    ),
    clients: list[str] = typer.Option(None, "--client", help="Логин клиента агентства (повторяемая)."),
    last_only: bool = typer.Option(False, "--last-only", help="Только последняя запись по каждому типу событий."),
    limit: int = typer.Option(None, "--limit", help="Сколько записей вернуть."),
    offset: int = typer.Option(None, "--offset", help="Сколько записей пропустить."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Записи журнала событий за период: модерация, зачисления, остановки по бюджету и др.

    Денежные значения — в валюте --currency (не в микроединицах).
    --json: {"ok": true, "count": N, "events": [{Timestamp, EventName, EventType, CampaignID,
    BannerID, PhraseID, AccountID, TextDescription, Attributes}]}.

    Example: {cli} events list --from 2026-09-01 --campaign 12345 --json
    """
    param: dict[str, Any] = {
        "TimestampFrom": _iso(date_from),
        "Currency": currency.upper(),
        "WithTextDescription": "Yes",
        "LastEventOnly": "Yes" if last_only else "No",
    }
    if date_to:
        param["TimestampTo"] = _iso(date_to)
    if clients:
        param["Logins"] = clients
    event_filter = {
        key: value
        for key, value in (
            ("CampaignIDS", campaigns),
            ("BannerIDS", banners),
            ("PhraseIDS", phrases),
            ("AccountIDS", accounts),
            ("EventType", event_types),
        )
        if value
    }
    if event_filter:
        param["Filter"] = event_filter
    if limit is not None:
        param["Limit"] = limit
    if offset is not None:
        param["Offset"] = offset
    items = _live.call(ctx, "GetEventsLog", param) or []
    emit_list(ctx, "events", items, EVENT_COLUMNS, title="События")


def _iso(value: str) -> str:
    """Дата без времени → начало суток UTC; остальное — как есть."""
    return f"{value}T00:00:00Z" if len(value) == 10 else value


# --- goals ----------------------------------------------------------------------------------

goals_app = output.group("Цели Метрики для статистики и ретаргетинга (API v4 GetStatGoals, GetRetargetingGoals).")


@goals_app.command("stat")
@output.guard
def goals_stat(
    ctx: typer.Context,
    campaigns: list[int] = typer.Option(..., "--campaign", help="Id кампании (повторяемая)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Цели Метрики, доступные в статистике кампаний (GetStatGoals).

    Их Id — для `--goal` отчётов и стратегий с оплатой за конверсии.
    --json: {"ok": true, "count": N, "goals": [{GoalID, Name, CampaignID?}]}.

    Example: {cli} goals stat --campaign 12345 --json
    """
    items = _live.call(ctx, "GetStatGoals", {"CampaignIDS": campaigns}) or []
    emit_list(ctx, "goals", items, [("Id", "GoalID"), ("Название", "Name")], title="Цели для статистики")


@goals_app.command("retargeting")
@output.guard
def goals_retargeting(
    ctx: typer.Context,
    clients: list[str] = typer.Option(None, "--client", help="Логин клиента агентства (повторяемая); нет — свой."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Цели и сегменты для условий ретаргетинга (GetRetargetingGoals).

    --json: {"ok": true, "count": N, "goals": [{GoalID, Name, GoalDomain, Type, Login}]}.

    Example: {cli} goals retargeting --json
    """
    items = _live.call(ctx, "GetRetargetingGoals", {"Logins": clients} if clients else {}) or []
    columns = [("Id", "GoalID"), ("Название", "Name"), ("Тип", "Type"), ("Домен", "GoalDomain"), ("Логин", "Login")]
    emit_list(ctx, "goals", items, columns, title="Цели для ретаргетинга")


# --- tags -----------------------------------------------------------------------------------

tags_app = output.group("Метки кампаний и объявлений (API v4): список и замена.")


@tags_app.command("campaigns")
@output.guard
def tags_campaigns(
    ctx: typer.Context,
    campaigns: list[int] = typer.Option(..., "--campaign", help="Id кампании (повторяемая)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Метки, заведённые в кампаниях (GetCampaignsTags).

    --json: {"ok": true, "count": N, "campaigns": [{CampaignID, Tags: [{TagID, Tag}]}]}.

    Example: {cli} tags campaigns --campaign 12345 --json
    """
    items = _live.call(ctx, "GetCampaignsTags", {"CampaignIDS": campaigns}) or []
    columns = [
        ("Кампания", "CampaignID"),
        ("Метки", lambda c: ", ".join(f"{t['Tag']} ({t['TagID']})" for t in c.get("Tags") or [])),
    ]
    emit_list(ctx, "campaigns", items, columns, title="Метки кампаний")


@tags_app.command("banners")
@output.guard
def tags_banners(
    ctx: typer.Context,
    campaigns: list[int] = typer.Option(None, "--campaign", help="Все объявления этих кампаний (повторяемая)."),
    banners: list[int] = typer.Option(None, "--banner", help="Эти объявления (повторяемая)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Какие метки назначены объявлениям (GetBannersTags): по кампаниям или по Id объявлений.

    --json: {"ok": true, "count": N, "banners": [{BannerID, TagIDS: [...]}]}.

    Example: {cli} tags banners --banner 777 --json
    """
    if bool(campaigns) == bool(banners):
        raise InvalidArguments("Укажите что-то одно: --campaign или --banner.")
    param = {"CampaignIDS": campaigns} if campaigns else {"BannerIDS": banners}
    items = _live.call(ctx, "GetBannersTags", param) or []
    columns = [("Объявление", "BannerID"), ("Id меток", lambda b: ", ".join(map(str, b.get("TagIDS") or [])))]
    emit_list(ctx, "banners", items, columns, title="Метки объявлений")


@tags_app.command("set-campaign")
@output.guard
def tags_set_campaign(
    ctx: typer.Context,
    campaign_id: int = typer.Argument(..., help="Id кампании."),
    tags: list[str] = typer.Option(None, "--tag", "-t", help="Метка (повторяемая); нет ни одной — удалить все."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Задать полный список меток кампании (UpdateCampaignsTags): не перечисленные — удаляются.

    Существующие метки сохраняют Id (и назначения объявлениям), новые создаются.

    Example: {cli} tags set-campaign 12345 -t распродажа -t зима --dry-run
    """
    current = _live.call(ctx, "GetCampaignsTags", {"CampaignIDS": [campaign_id]}) or []
    known = {t["Tag"]: t["TagID"] for c in current for t in c.get("Tags") or []}
    items = [{"TagID": known.get(tag, 0), "Tag": tag} for tag in dict.fromkeys(tags or [])]
    _live.mutate(
        ctx,
        title=f"Метки кампании {campaign_id}: {len(items)} шт.",
        method="UpdateCampaignsTags",
        param=[{"CampaignID": campaign_id, "Tags": items}],
        confirm=confirm,
    )


@tags_app.command("set-banners")
@output.guard
def tags_set_banners(
    ctx: typer.Context,
    banners: list[int] = typer.Option(..., "--banner", help="Id объявления (повторяемая)."),
    tag_ids: list[int] = typer.Option(None, "--tag-id", help="Id метки кампании (повторяемая); нет — снять все."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Назначить объявлениям метки кампании (UpdateBannersTags): прежние, не перечисленные, снимаются.

    Id меток — из `tags campaigns`.

    Example: {cli} tags set-banners --banner 777 --tag-id 16590 --dry-run
    """
    param = [{"BannerID": banner, "TagIDS": tag_ids or []} for banner in banners]
    _live.mutate(
        ctx, title=f"Метки объявлений: {len(banners)} шт.", method="UpdateBannersTags", param=param, confirm=confirm
    )


# --- suggest --------------------------------------------------------------------------------


@output.guard
def suggest(
    ctx: typer.Context,
    keywords: list[str] = typer.Argument(..., help="Исходные фразы."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Подсказать похожие ключевые фразы (API v4 GetKeywordsSuggestion, до 20 штук).

    Расходует баллы API. --json: {"ok": true, "count": N, "keywords": ["...", ...]}.

    Example: {cli} suggest 'купить диван' --json
    """
    words = _live.call(ctx, "GetKeywordsSuggestion", {"Keywords": keywords}) or []

    def render(_: dict) -> None:
        for word in words:
            output.human.echo(word)

    output.emit_success(ctx, {"count": len(words), "keywords": words}, render)


# --- v4 meta --------------------------------------------------------------------------------

v4_app = output.group("Служебные методы API v4 Live: проверка связи и версии.")


@v4_app.command("ping")
@output.guard
def v4_ping(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Проверить, что API v4 Live отвечает и принимает токен (PingAPI).

    --json: {"ok": true, "result": 1}.

    Example: {cli} v4 ping
    """
    result = _live.call(ctx, "PingAPI")
    output.emit_success(ctx, {"result": result}, lambda d: output.human.echo(f"API v4 Live: {d['result']}"))


@v4_app.command("version")
@output.guard
def v4_version(
    ctx: typer.Context,
    available: bool = typer.Option(False, "--available", help="Все доступные версии (GetAvailableVersions)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Версия API v4 (GetVersion) или список доступных (--available).

    --json: {"ok": true, "version": ...}.

    Example: {cli} v4 version --available --json
    """
    version = _live.call(ctx, "GetAvailableVersions" if available else "GetVersion")
    output.emit_success(ctx, {"version": version}, lambda d: output.human.echo(f"API v4: {d['version']}"))
