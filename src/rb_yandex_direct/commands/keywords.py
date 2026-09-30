"""`yd keywords` — ключевые фразы (сервис Keywords) и исследование фраз (KeywordsResearch)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import typer

from .. import output
from ..core import services
from ..core.errors import InvalidArguments
from ._common import emit_list, emit_object, mutate, read_lines
from ._targeting import (
    AdGroupFilter,
    CampaignFilter,
    FieldOption,
    IdFilter,
    IdsArgument,
    Priority,
    PriorityOption,
    ServingStatus,
    ids_mutation,
    values,
)

app = output.group("Ключевые фразы: список, добавление, изменение, статусы, спрос и дубли.")

MAX_ADD = 1000


class KeywordState(StrEnum):
    ON = "ON"
    OFF = "OFF"
    SUSPENDED = "SUSPENDED"


class KeywordStatus(StrEnum):
    DRAFT = "DRAFT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DedupOperation(StrEnum):
    MERGE_DUPLICATES = "MERGE_DUPLICATES"
    ELIMINATE_OVERLAPPING = "ELIMINATE_OVERLAPPING"


# Настройки автотаргетинга (AutotargetingSettings): категории запросов и упоминания брендов.
AUTOTARGETING_CATEGORIES = ("Exact", "Narrow", "Alternative", "Accessory", "Broader")
AUTOTARGETING_BRANDS = ("WithoutBrands", "WithAdvertiserBrand", "WithCompetitorsBrand")
# Фраза-маркер автотаргетинга: аргументом её не передать (Click примет за опцию).
AUTOTARGETING_PHRASE = "---autotargeting"
_AUTOTARGETING_HELP = (
    "Настройка автотаргетинга NAME=YES|NO (повторяемая): "
    f"{', '.join(AUTOTARGETING_CATEGORIES + AUTOTARGETING_BRANDS)}. Применяется только к фразе автотаргетинга."
)

COLUMNS = [
    ("Id", "Id"),
    ("Фраза", "Keyword"),
    ("Группа", "AdGroupId"),
    ("Кампания", "CampaignId"),
    ("Состояние", "State"),
    ("Статус", "Status"),
    ("Поиск ₽", lambda k: services.rubles(k.get("Bid"))),
    ("Сети ₽", lambda k: services.rubles(k.get("ContextBid"))),
]


def autotargeting_settings(specs: list[str] | None) -> dict[str, Any] | None:
    """`Exact=YES` … → {"Categories": {...}, "BrandOptions": {...}}; пусто — None."""
    if not specs:
        return None
    categories: dict[str, str] = {}
    brands: dict[str, str] = {}
    lookup = {name.lower(): name for name in AUTOTARGETING_CATEGORIES + AUTOTARGETING_BRANDS}
    for spec in specs:
        name, _, value = spec.partition("=")
        key = lookup.get(name.strip().lower())
        value = value.strip().upper()
        if key is None or value not in ("YES", "NO"):
            raise InvalidArguments(
                f"--autotargeting {spec!r}: ожидается NAME=YES|NO, NAME из {', '.join(lookup.values())}."
            )
        (categories if key in AUTOTARGETING_CATEGORIES else brands)[key] = value
    settings: dict[str, Any] = {}
    if categories:
        settings["Categories"] = categories
    if brands:
        settings["BrandOptions"] = brands
    return settings


@app.command("list")
@output.guard
def list_keywords(
    ctx: typer.Context,
    ids: list[int] = IdFilter,
    adgroups: list[int] = AdGroupFilter,
    campaigns: list[int] = CampaignFilter,
    states: list[KeywordState] = typer.Option(None, "--state", help="Фильтр по состоянию (повторяемая)."),
    statuses: list[KeywordStatus] = typer.Option(None, "--status", help="Фильтр по статусу модерации (повторяемая)."),
    serving: list[ServingStatus] = typer.Option(
        None, "--serving-status", help="ELIGIBLE — показывается, RARELY_SERVED — мало показов (повторяемая)."
    ),
    modified_since: str = typer.Option(
        None, "--modified-since", help="Изменённые после момента, YYYY-MM-DDThh:mm:ssZ."
    ),
    fields: list[str] = FieldOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Список ключевых фраз с фильтрами по Id, группам, кампаниям, состоянию и статусу.

    Нужен хотя бы один из --id, --adgroup, --campaign.
    --json: {"ok": true, "count": N, "keywords": [{Id, Keyword, AdGroupId, CampaignId, State, Status,
    ServingStatus, Bid, ContextBid, StrategyPriority}]}; ставки — в микроединицах валюты.

    Example: {cli} keywords list --adgroup 555
    """
    if not (ids or adgroups or campaigns):
        raise InvalidArguments("Укажите хотя бы один фильтр: --id, --adgroup или --campaign.")
    items = services.run(
        services.direct(ctx.obj).list_keywords(
            adgroup_ids=adgroups or None,
            campaign_ids=campaigns or None,
            keyword_ids=ids or None,
            states=values(states),
            field_names=fields or None,
            statuses=values(statuses),
            serving_statuses=values(serving),
            modified_since=modified_since,
        )
    )
    emit_list(ctx, "keywords", items, COLUMNS, title="Ключевые фразы")


@app.command("add")
@output.guard
def add(
    ctx: typer.Context,
    phrases: list[str] = typer.Argument(None, help="Фразы (или --from-file)."),
    adgroup: int = typer.Option(..., "--adgroup", help="Группа объявлений, куда добавить фразы."),
    from_file: str = typer.Option(None, "--from-file", help="Файл с фразами, по одной в строке."),
    search_bid: float = typer.Option(None, "--search-bid", help="Ставка на поиске, ₽ (ручная стратегия)."),
    network_bid: float = typer.Option(None, "--network-bid", help="Ставка в сетях, ₽ (ручная стратегия)."),
    priority: Priority = PriorityOption,
    user_param1: str = typer.Option(None, "--user-param1", help="Значение {param1} для подстановки в ссылку."),
    user_param2: str = typer.Option(None, "--user-param2", help="Значение {param2} для подстановки в ссылку."),
    autotargeting_phrase: bool = typer.Option(
        False, "--autotargeting-phrase", help="Добавить и фразу автотаргетинга (---autotargeting)."
    ),
    autotargeting: list[str] = typer.Option(None, "--autotargeting", help=_AUTOTARGETING_HELP),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Добавить ключевые фразы в группу (до 1000 за вызов); ставки — в рублях.

    Автотаргетинг — `--autotargeting-phrase` с настройками `--autotargeting Exact=YES …`.

    Example: {cli} keywords add 'купить диван' 'диван недорого' --adgroup 555 --search-bid 15 --dry-run
    """
    texts = read_lines(phrases, from_file) + ([AUTOTARGETING_PHRASE] if autotargeting_phrase else [])
    if not texts:
        raise InvalidArguments("Укажите фразы аргументами, через --from-file или --autotargeting-phrase.")
    if len(texts) > MAX_ADD:
        raise InvalidArguments(f"Не более {MAX_ADD} фраз за вызов, получено {len(texts)}.")
    settings = autotargeting_settings(autotargeting)
    items: list[dict[str, Any]] = []
    for text in texts:
        item: dict[str, Any] = {"AdGroupId": adgroup, "Keyword": text}
        if search_bid is not None:
            item["Bid"] = services.micros(search_bid)
        if network_bid is not None:
            item["ContextBid"] = services.micros(network_bid)
        if priority:
            item["StrategyPriority"] = priority.value
        if user_param1 is not None:
            item["UserParam1"] = user_param1
        if user_param2 is not None:
            item["UserParam2"] = user_param2
        if settings and text == AUTOTARGETING_PHRASE:
            item["AutotargetingSettings"] = settings
        items.append(item)
    mutate(
        ctx,
        title=f"Добавить {len(items)} фраз в группу {adgroup}",
        service="keywords",
        method="add",
        params={"Keywords": items},
        confirm=confirm,
    )


@app.command("update")
@output.guard
def update(
    ctx: typer.Context,
    keyword_id: int = typer.Argument(..., help="Id ключевой фразы."),
    keyword: str = typer.Option(None, "--keyword", help="Новый текст фразы."),
    user_param1: str = typer.Option(None, "--user-param1", help="Значение {param1}; пустая строка — очистить."),
    user_param2: str = typer.Option(None, "--user-param2", help="Значение {param2}; пустая строка — очистить."),
    autotargeting: list[str] = typer.Option(None, "--autotargeting", help=_AUTOTARGETING_HELP),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить текст фразы, параметры подстановки или настройки автотаргетинга.

    Ставки и приоритет меняет `bids set`.

    Example: {cli} keywords update 901 --keyword 'купить угловой диван' --dry-run
    """
    item: dict[str, Any] = {"Id": keyword_id}
    if keyword:
        item["Keyword"] = keyword
    if user_param1 is not None:
        item["UserParam1"] = user_param1
    if user_param2 is not None:
        item["UserParam2"] = user_param2
    settings = autotargeting_settings(autotargeting)
    if settings:
        item["AutotargetingSettings"] = settings
    if len(item) == 1:
        raise InvalidArguments("Нечего менять: укажите --keyword, --user-param1/2 или --autotargeting.")
    mutate(
        ctx,
        title=f"Изменить фразу {keyword_id}",
        service="keywords",
        method="update",
        params={"Keywords": [item]},
        confirm=confirm,
    )


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
    """Остановить показы по ключевым фразам.

    Example: {cli} keywords suspend 901 902 --confirm
    """
    ids_mutation(ctx, service="keywords", method="suspend", verb="Остановить", noun="фразы", ids=ids, confirm=confirm)


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
    """Возобновить показы по остановленным ключевым фразам.

    Example: {cli} keywords resume 901 --confirm
    """
    ids_mutation(ctx, service="keywords", method="resume", verb="Возобновить", noun="фразы", ids=ids, confirm=confirm)


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
    """Удалить ключевые фразы — необратимо.

    Example: {cli} keywords delete 901 --dry-run
    """
    ids_mutation(ctx, service="keywords", method="delete", verb="Удалить", noun="фразы", ids=ids, confirm=confirm)


@app.command("check-volume")
@output.guard
def check_volume(
    ctx: typer.Context,
    phrases: list[str] = typer.Argument(None, help="Фразы для проверки (или --from-file)."),
    from_file: str = typer.Option(None, "--from-file", help="Файл с фразами, по одной в строке."),
    regions: list[int] = typer.Option(
        None, "--region", help="Регион Яндекса (213 — Москва, 2 — СПб; по умолчанию 225 — Россия), повторяемая."
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Есть ли у фраз поисковый спрос — по всем устройствам, телефонам, планшетам, компьютерам.

    Только чтение (keywordsresearch.hasSearchVolume), кабинет не меняется.
    --json: {"ok": true, "count": N, "keywords": [{Keyword, RegionIds, AllDevices, MobilePhones,
    Tablets, Desktops}]}; значения YES/NO.

    Example: {cli} keywords check-volume 'купить диван' 'диван недорого' --region 213
    """
    texts = read_lines(phrases, from_file)
    if not texts:
        raise InvalidArguments("Укажите фразы аргументами или через --from-file.")
    items = services.run(services.direct(ctx.obj).keywords_has_search_volume(texts, region_ids=regions or None))
    columns = [
        ("Фраза", "Keyword"),
        ("Все", "AllDevices"),
        ("Телефоны", "MobilePhones"),
        ("Планшеты", "Tablets"),
        ("Компьютеры", "Desktops"),
    ]
    emit_list(ctx, "keywords", items, columns, title="Поисковый спрос")


@app.command("dedup")
@output.guard
def dedup(
    ctx: typer.Context,
    phrases: list[str] = typer.Argument(None, help="Фразы (или --from-file, или --adgroup)."),
    from_file: str = typer.Option(None, "--from-file", help="Файл с фразами, по одной в строке."),
    adgroups: list[int] = typer.Option(
        None, "--adgroup", help="Взять фразы этих групп (с их Id) — проверка дублей в кабинете (повторяемая)."
    ),
    operations: list[DedupOperation] = typer.Option(
        None,
        "--operation",
        help="MERGE_DUPLICATES — склеить дубли, ELIMINATE_OVERLAPPING — минусовать пересечения (по умолчанию обе).",
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Подсказать, какие фразы склеить и какие минус-слова добавить, чтобы фразы не пересекались.

    Только расчёт (keywordsresearch.deduplicate): кабинет не меняется, применять — `keywords
    add/update/delete`. --json: {"ok": true, "result": {Add: [{Keyword}], Update: [{Id, Keyword}],
    Delete: {Ids}, Failure: [...]}}.

    Example: {cli} keywords dedup 'купить диван' 'купить диван недорого' --json
    """
    items: list[dict[str, Any]] = [{"Keyword": text} for text in read_lines(phrases, from_file)]
    if adgroups:
        existing = services.run(
            services.direct(ctx.obj).list_keywords(adgroup_ids=adgroups, field_names=["Id", "Keyword"])
        )
        items += [{"Id": k["Id"], "Keyword": k["Keyword"]} for k in existing if k.get("Keyword")]
    if not items:
        raise InvalidArguments("Укажите фразы аргументами, через --from-file или --adgroup.")
    result = services.run(services.direct(ctx.obj).keywords_deduplicate(items, operations=values(operations)))
    emit_object(ctx, "result", result, title=f"Дубли и пересечения среди {len(items)} фраз")
