"""`yd masters` — Мастер кампаний: у него нет API, всё через веб-интерфейс (браузер).

Сессия, куки Chrome и разбор страниц — `providers.browser` (обёртка над direct-cli);
здесь только аргументы, план для --dry-run и вывод.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import typer

from .. import output
from ..core import services
from ..core.errors import InvalidArguments
from ..providers import browser
from ._common import emit_list, emit_object
from ._web import (
    ChromeDirOption,
    ChromeProfileOption,
    HeadfulOption,
    one_based,
    parse_goal_prices,
    parse_slots,
    web_mutate,
)
from ._web import run as web_run

app = output.group(
    "Мастер кампаний (веб-интерфейс, без API): список, статусы, создание, правка, изображения. "
    "Нужен extra `browser` и сессия Яндекса (`yd browser login` или вход в Chrome)."
)
images_app = output.group("Изображения Мастера кампаний: список, добавить, удалить, заменить набор.")
app.add_typer(images_app, name="images")

# Слоты на странице правки Мастера: заголовков 5, текстов 3; изображений в наборе не больше 5.
HEADLINE_SLOTS = 5
TEXT_SLOTS = 3
IMAGE_SLOTS = 5


class StatusFilter(StrEnum):
    NOT_ARCHIVED = "not-archived"
    ACTIVE = "active"
    STOPPED = "stopped"
    ARCHIVED = "archived"
    ALL = "all"


class PromotionGoal(StrEnum):
    MAX_CONVERSIONS = "max-conversions"
    MAX_CLICKS = "max-clicks"


class Gender(StrEnum):
    ANY = "any"
    MALE = "male"
    FEMALE = "female"


class Device(StrEnum):
    MOBILE = "mobile"
    DESKTOP = "desktop"
    TABLET = "tablet"


AGE_FROM = (0, 18, 25, 35, 45, 55)
AGE_TO = (18, 25, 35, 45, 55)

COLUMNS = [
    ("Id", "CampaignId"),
    ("Название", "Name"),
    ("Статус", "Status"),
    ("Тип", "Type"),
    ("Старт", "StartDate"),
]

CampaignIdArgument = typer.Argument(..., help="Id кампании Мастера (как в интерфейсе Директа).")


@app.command("list")
@output.guard
def list_masters(
    ctx: typer.Context,
    status: StatusFilter = typer.Option(StatusFilter.NOT_ARCHIVED, "--status", help="Фильтр по статусу."),
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Кампании Мастера из общей таблицы кампаний кабинета, в котором вы вошли в браузере.

    Кабинет — тот, что открыт в браузерной сессии: --login здесь не действует.
    --json: {"ok": true, "count": N, "masters": [{CampaignId, Name, Status, Type, StartDate}]}.

    Example: {cli} masters list --status active --json
    """
    items = web_run(
        ctx,
        lambda page: browser.lib().masters.fetch_masters_list(page, status=status.value),
        headful,
        chrome_dir,
        chrome_profile,
    )
    emit_list(ctx, "masters", items, COLUMNS, title="Мастер кампаний")


@app.command("get")
@output.guard
def get_master(
    ctx: typer.Context,
    campaign_id: int = CampaignIdArgument,
    moderation: bool = typer.Option(False, "--moderation", help="Добавить статусы модерации объявлений."),
    tracking: bool = typer.Option(False, "--tracking-params", help="Добавить UTM-метки (параметры ссылки)."),
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Одна кампания Мастера: название, статус, ссылка, плитки статистики (для черновика — поля формы).

    --json: {"ok": true, "master": {CampaignId, Name, Status, LandingUrl, …}}.

    Example: {cli} masters get 72349978 --tracking-params --json
    """

    def operation(page: Any) -> dict:
        masters = browser.lib().masters
        result = masters.fetch_master(page, campaign_id)
        if moderation:
            result.update(masters.fetch_master_moderation_statuses(page, campaign_id))
        if tracking:
            result.update(masters.fetch_master_tracking_params(page, campaign_id))
        return result

    emit_object(
        ctx, "master", web_run(ctx, operation, headful, chrome_dir, chrome_profile), title=f"Мастер {campaign_id}"
    )


def _reader(name: str, key: str, title: str):
    def read(ctx: typer.Context, campaign_id: int, headful: bool, chrome_dir: str | None, chrome_profile: str) -> None:
        fetch = getattr(browser.lib().masters, name)
        value = web_run(ctx, lambda page: fetch(page, campaign_id), headful, chrome_dir, chrome_profile)
        emit_object(ctx, key, value, title=f"{title} {campaign_id}")

    return read


@app.command("audience")
@output.guard
def audience(
    ctx: typer.Context,
    campaign_id: int = CampaignIdArgument,
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Аудитория кампании: пол, возраст, устройства, интересы и поисковые запросы (теги по порядку).

    Позиции тегов для `masters update --remove-audience-tag` считаются с 1 в порядке этого списка.

    Example: {cli} masters audience 72349978 --json
    """
    _reader("fetch_master_audience", "audience", "Аудитория Мастера")(
        ctx, campaign_id, headful, chrome_dir, chrome_profile
    )


@app.command("counters")
@output.guard
def counters(
    ctx: typer.Context,
    campaign_id: int = CampaignIdArgument,
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Счётчики Яндекс Метрики кампании (раздел есть только при цели «максимум конверсий»).

    Example: {cli} masters counters 72349978 --json
    """
    _reader("fetch_master_metrika_counters", "counters", "Счётчики Мастера")(
        ctx, campaign_id, headful, chrome_dir, chrome_profile
    )


@app.command("target-actions")
@output.guard
def target_actions(
    ctx: typer.Context,
    campaign_id: int = CampaignIdArgument,
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Целевые действия (цели Метрики) кампании и цены за них — Id целей для `update`/`add`.

    Example: {cli} masters target-actions 72349978 --json
    """
    _reader("fetch_master_target_actions", "target_actions", "Целевые действия Мастера")(
        ctx, campaign_id, headful, chrome_dir, chrome_profile
    )


def _action(
    ctx: typer.Context,
    function: str,
    verb: str,
    campaign_id: int,
    confirm: bool,
    headful: bool,
    chrome_dir: str | None,
    chrome_profile: str,
    **kwargs: Any,
) -> None:
    web_mutate(
        ctx,
        title=f"{verb} кампанию Мастера {campaign_id}",
        action=function,
        params={"CampaignId": campaign_id, **kwargs},
        operation=lambda page: getattr(browser.lib().masters, function)(page, campaign_id, **kwargs),
        confirm=confirm,
        headful=headful,
        chrome_dir=chrome_dir,
        chrome_profile=chrome_profile,
    )


@app.command("suspend")
@output.guard
def suspend(
    ctx: typer.Context,
    campaign_id: int = CampaignIdArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Остановить кампанию Мастера (статус проверяется после клика).

    Example: {cli} masters suspend 72349978 --dry-run
    """
    _action(ctx, "suspend_master", "Остановить", campaign_id, confirm, headful, chrome_dir, chrome_profile)


@app.command("resume")
@output.guard
def resume(
    ctx: typer.Context,
    campaign_id: int = CampaignIdArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Возобновить остановленную кампанию Мастера.

    Example: {cli} masters resume 72349978 --confirm
    """
    _action(ctx, "resume_master", "Возобновить", campaign_id, confirm, headful, chrome_dir, chrome_profile)


@app.command("archive")
@output.guard
def archive(
    ctx: typer.Context,
    campaign_id: int = CampaignIdArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Архивировать кампанию Мастера (через меню строки в таблице кампаний).

    Example: {cli} masters archive 72349978 --confirm
    """
    _action(ctx, "archive_master", "Архивировать", campaign_id, confirm, headful, chrome_dir, chrome_profile)


@app.command("delete")
@output.guard
def delete(
    ctx: typer.Context,
    campaign_id: int = CampaignIdArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить кампанию Мастера — необратимо; Яндекс даёт удалить только кампании без показов.

    Example: {cli} masters delete 713337891 --dry-run
    """
    _action(ctx, "delete_master", "Удалить", campaign_id, confirm, headful, chrome_dir, chrome_profile)


@app.command("launch")
@output.guard
def launch(
    ctx: typer.Context,
    campaign_id: int = CampaignIdArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Отправить черновик Мастера на модерацию (запуск) — начнутся показы и траты.

    Example: {cli} masters launch 72349978 --dry-run
    """
    _action(ctx, "launch_master", "Запустить", campaign_id, confirm, headful, chrome_dir, chrome_profile)


@app.command("copy")
@output.guard
def copy(
    ctx: typer.Context,
    campaign_id: int = CampaignIdArgument,
    launch_copy: bool = typer.Option(False, "--launch", help="Сразу отправить копию на модерацию (иначе — черновик)."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Скопировать кампанию Мастера; результат содержит Id новой кампании.

    Example: {cli} masters copy 72349978 --dry-run
    """
    _action(
        ctx, "copy_master", "Скопировать", campaign_id, confirm, headful, chrome_dir, chrome_profile, launch=launch_copy
    )


def _regions(ctx: typer.Context, names: list[str] | None, region_ids: list[int] | None) -> list:
    """Регионы для формы: текст как есть или Id → точное название из справочника API (нужен токен)."""
    regions: list = [(name, None) for name in names or []]
    if region_ids:
        result = services.run(
            services.direct(ctx.obj).call(
                "dictionaries",
                "getGeoRegions",
                {"SelectionCriteria": {"RegionIds": region_ids}, "FieldNames": ["GeoRegionId", "GeoRegionName"]},
            )
        )
        found = {int(r["GeoRegionId"]): r["GeoRegionName"] for r in result.get("GeoRegions", [])}
        missing = [rid for rid in region_ids if rid not in found]
        if missing:
            raise InvalidArguments(f"Регионы не найдены в справочнике Директа: {missing}.")
        regions += [(found[rid], rid) for rid in region_ids]
    if not regions:
        raise InvalidArguments("Укажите регион: --region (название) или --region-id.")
    return regions


@app.command("add")
@output.guard
def add(
    ctx: typer.Context,
    url: str = typer.Argument(..., help="Продвигаемый сайт (посадочная страница)."),
    headlines: list[str] = typer.Option(..., "--headline", help="Заголовок (повторяемая, до 5)."),
    texts: list[str] = typer.Option(..., "--text", help="Текст объявления (повторяемая, до 3)."),
    regions: list[str] = typer.Option(None, "--region", help="Регион по названию, как в интерфейсе (повторяемая)."),
    region_ids: list[int] = typer.Option(
        None, "--region-id", help="Регион по Id справочника Директа (повторяемая; нужен токен API)."
    ),
    target_actions: list[str] = typer.Option(
        ..., "--target-action", help='Цель Метрики и цена: "ID_цели=цена" (повторяемая; хотя бы одна).'
    ),
    weekly_budget: int = typer.Option(..., "--weekly-budget", help="Недельный бюджет в валюте кабинета."),
    draft: bool = typer.Option(False, "--draft", help="Сохранить черновиком, не отправляя на модерацию."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать кампанию Мастера («Конверсии и трафик») — экспериментально, заполняет форму в браузере.

    Яндекс не сохранит форму без цели Метрики и недельного бюджета: цели берутся из счётчика,
    найденного по домену сайта (`masters target-actions` у похожей кампании покажет Id).
    Песочницы и отката у Мастера нет — сначала --dry-run.

    Example: {cli} masters add https://example.com/ --headline 'Заголовок' --text 'Текст' --region Москва --target-action 236386933=150 --weekly-budget 5000 --draft --dry-run
    """
    if len(headlines) > HEADLINE_SLOTS or len(texts) > TEXT_SLOTS:
        raise InvalidArguments(f"Не больше {HEADLINE_SLOTS} заголовков и {TEXT_SLOTS} текстов.")
    goals = parse_goal_prices("--target-action", target_actions)
    if not goals:
        raise InvalidArguments('Нужна хотя бы одна цель: --target-action "ID_цели=цена".')
    params: dict[str, Any] = {
        "url": url,
        "headlines": headlines,
        "texts": texts,
        "regions": regions or [],
        "region_ids": region_ids or [],
        "target_actions": goals,
        "weekly_budget": weekly_budget,
        "launch": not draft,
    }

    def operation(page: Any) -> dict:
        return browser.lib().masters.create_master(
            page,
            url,
            headlines=headlines,
            texts=texts,
            regions=resolved,
            target_actions=goals,
            weekly_budget=weekly_budget,
            launch=not draft,
        )

    resolved = [] if output.is_dry_run(ctx) else _regions(ctx, regions, region_ids)
    web_mutate(
        ctx,
        title="Создать кампанию Мастера",
        action="create_master",
        params=params,
        operation=operation,
        confirm=confirm,
        headful=headful,
        chrome_dir=chrome_dir,
        chrome_profile=chrome_profile,
    )


@app.command("update")
@output.guard
def update(
    ctx: typer.Context,
    campaign_id: int = CampaignIdArgument,
    weekly_budget: int = typer.Option(None, "--weekly-budget", help="Недельный бюджет в валюте кабинета."),
    promotion_goal: PromotionGoal = typer.Option(None, "--promotion-goal", help="Цель продвижения."),
    goal_price: float = typer.Option(None, "--goal-price", help="Цена клика (при max-clicks)."),
    target_action_prices: list[str] = typer.Option(
        None, "--target-action-price", help='Новая цена существующей цели: "ID_цели=цена" (повторяемая).'
    ),
    add_target_actions: list[str] = typer.Option(
        None, "--add-target-action", help='Добавить цель: "ID_цели=цена" (повторяемая).'
    ),
    remove_target_actions: list[int] = typer.Option(
        None, "--remove-target-action", help="Убрать цель по Id (повторяемая)."
    ),
    directs_helps: bool = typer.Option(
        None, "--directs-helps/--no-directs-helps", help="Автоприменение рекомендаций Директа."
    ),
    name: str = typer.Option(None, "--name", help="Новое название кампании."),
    landing_url: str = typer.Option(None, "--landing-url", help="Новая посадочная страница."),
    tracking_params: str = typer.Option(None, "--tracking-params", help="UTM-метки (параметры ссылки)."),
    headlines: list[str] = typer.Option(
        None, "--headline", help='Заменить заголовок: "N=текст", N — номер варианта 1–5 (повторяемая).'
    ),
    texts: list[str] = typer.Option(
        None, "--text", help='Заменить текст: "N=текст", N — номер варианта 1–3 (повторяемая).'
    ),
    clear_headlines: list[int] = typer.Option(None, "--clear-headline", help="Удалить заголовок N (повторяемая)."),
    clear_texts: list[int] = typer.Option(None, "--clear-text", help="Удалить текст N (повторяемая)."),
    images: list[str] = typer.Option(
        None, "--image", help='Заменить изображение: "N=путь к PNG/JPEG/GIF" (новое встаёт в конец набора).'
    ),
    add_video: str = typer.Option(None, "--add-video", help="Добавить видео из файла."),
    add_video_url: str = typer.Option(None, "--add-video-url", help="Добавить видео по ссылке."),
    remove_videos: list[str] = typer.Option(None, "--remove-video", help="Убрать видео по его URL (повторяемая)."),
    gender: Gender = typer.Option(None, "--gender", help="Пол аудитории."),
    age_from: int = typer.Option(None, "--age-from", help=f"Возраст от: {', '.join(map(str, AGE_FROM))}."),
    age_to: str = typer.Option(None, "--age-to", help=f"Возраст до: {', '.join(map(str, AGE_TO))} или unlimited."),
    devices: list[Device] = typer.Option(
        None, "--device", help="Устройства (повторяемая): заменяет весь выбор, хотя бы одно."
    ),
    add_audience_tags: list[str] = typer.Option(
        None, "--add-audience-tag", help="Добавить интерес/запрос — точный текст подсказки Яндекса (повторяемая)."
    ),
    remove_audience_tags: list[int] = typer.Option(
        None, "--remove-audience-tag", help="Убрать тег по позиции с 1 из `masters audience` (повторяемая)."
    ),
    add_counters: list[str] = typer.Option(
        None, "--add-metrika-counter", help="Добавить счётчик Метрики по его Id (повторяемая)."
    ),
    remove_counters: list[int] = typer.Option(
        None, "--remove-metrika-counter", help="Убрать счётчик по позиции с 1 из `masters counters` (повторяемая)."
    ),
    add_sitelinks: list[str] = typer.Option(
        None,
        "--add-sitelink",
        help='Быстрая ссылка: "Заголовок|https://…|Описание", описание необязательно (повторяемая, до 5).',
    ),
    remove_sitelinks: list[int] = typer.Option(
        None, "--remove-sitelink", help="Убрать быструю ссылку по позиции с 1 (повторяемая)."
    ),
    launch_after: bool = typer.Option(False, "--launch", help="После сохранения отправить на модерацию."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить кампанию Мастера: бюджет, цели, тексты, изображения, аудиторию, ссылки — экспериментально.

    Меняются только переданные поля; остальные остаются как были. После сохранения значения
    перечитываются со страницы и сверяются. Номера вариантов и позиций — с 1, как в интерфейсе
    и в `masters audience`/`counters`.

    Example: {cli} masters update 72349978 --weekly-budget 9500 --headline '2=Новый заголовок' --dry-run
    """
    kwargs: dict[str, Any] = {
        "weekly_budget": weekly_budget,
        "promotion_goal": promotion_goal.value if promotion_goal else None,
        "goal_price": goal_price,
        "target_action_prices": parse_goal_prices("--target-action-price", target_action_prices) or None,
        "add_target_actions": parse_goal_prices("--add-target-action", add_target_actions) or None,
        "remove_target_action_goal_ids": remove_target_actions or None,
        "directs_helps": directs_helps,
        "name": name,
        "landing_url": landing_url,
        "tracking_params": tracking_params,
        "headlines": parse_slots("--headline", headlines, HEADLINE_SLOTS) or None,
        "texts": parse_slots("--text", texts, TEXT_SLOTS) or None,
        "clear_headlines": one_based("--clear-headline", clear_headlines) or None,
        "clear_texts": one_based("--clear-text", clear_texts) or None,
        "images": _image_slots(images),
        "add_video": add_video,
        "add_video_url": add_video_url,
        "remove_videos": remove_videos or None,
        "gender": gender.value if gender else None,
        "devices": {d.value for d in devices} if devices else None,
        "add_audience_tags": add_audience_tags or None,
        "remove_audience_tags": one_based("--remove-audience-tag", remove_audience_tags) or None,
        "add_metrika_counters": add_counters or None,
        "remove_metrika_counters": one_based("--remove-metrika-counter", remove_counters) or None,
        "add_sitelinks": _sitelinks(add_sitelinks),
        "remove_sitelinks": one_based("--remove-sitelink", remove_sitelinks) or None,
    }
    kwargs = {key: value for key, value in kwargs.items() if value is not None}
    kwargs.update(_ages(age_from, age_to))  # age_to=None — осознанное «без ограничения», не пропуск
    if not kwargs:
        raise InvalidArguments("Нечего менять: передайте хотя бы одно поле (см. --help).")
    kwargs["launch"] = launch_after
    plan = {key: sorted(value) if isinstance(value, set) else value for key, value in kwargs.items()}
    web_mutate(
        ctx,
        title=f"Изменить кампанию Мастера {campaign_id}",
        action="update_master",
        params={"CampaignId": campaign_id, **plan},
        operation=lambda page: browser.lib().masters.update_master(page, campaign_id, **kwargs),
        confirm=confirm,
        headful=headful,
        chrome_dir=chrome_dir,
        chrome_profile=chrome_profile,
    )


def _ages(age_from: int | None, age_to: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if age_from is not None:
        if age_from not in AGE_FROM:
            raise InvalidArguments(f"--age-from: одно из {AGE_FROM}.")
        out.update(age_from=age_from, age_from_requested=True)
    if age_to is not None:
        if age_to == "unlimited":
            value = None
        elif age_to.isdigit() and int(age_to) in AGE_TO:
            value = int(age_to)
        else:
            raise InvalidArguments(f"--age-to: одно из {AGE_TO} или unlimited.")
        out.update(age_to=value, age_to_requested=True)
    return out


def _image_slots(values: list[str] | None) -> dict[int, str] | None:
    slots = parse_slots("--image", values, IMAGE_SLOTS)
    for path in slots.values():
        _check_image(path)
    return slots or None


def _check_image(path: str) -> None:
    file = Path(path)
    if not file.is_file():
        raise InvalidArguments(f"Файл изображения не найден: {path}.")
    if file.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif"):
        raise InvalidArguments(f"Яндекс принимает PNG, JPEG или GIF: {path}.")


def _sitelinks(values: list[str] | None) -> list[dict[str, str]] | None:
    out = []
    for raw in values or []:
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) not in (2, 3) or not parts[0] or not parts[1].startswith(("http://", "https://")):
            raise InvalidArguments(
                f'--add-sitelink {raw!r}: ожидается "Заголовок|https://…|Описание" (описание можно опустить).'
            )
        out.append({"Title": parts[0], "Href": parts[1], "Description": parts[2] if len(parts) == 3 else ""})
    return out or None


# --- изображения ----------------------------------------------------------------------------


@images_app.command("list")
@output.guard
def images_list(
    ctx: typer.Context,
    campaign_id: int = CampaignIdArgument,
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изображения кампании Мастера по порядку: позиции (с 1), content id, миниатюры, модерация.

    Example: {cli} masters images list 72349978 --json
    """
    _reader("fetch_master_images", "images", "Изображения Мастера")(
        ctx, campaign_id, headful, chrome_dir, chrome_profile
    )


def _images_mutation(
    ctx: typer.Context,
    function: str,
    title: str,
    campaign_id: int,
    kwargs: dict,
    confirm: bool,
    headful: bool,
    chrome_dir: str | None,
    chrome_profile: str,
) -> None:
    web_mutate(
        ctx,
        title=title,
        action=function,
        params={"CampaignId": campaign_id, **kwargs},
        operation=lambda page: getattr(browser.lib().masters, function)(page, campaign_id, **kwargs),
        confirm=confirm,
        headful=headful,
        chrome_dir=chrome_dir,
        chrome_profile=chrome_profile,
    )


@images_app.command("add")
@output.guard
def images_add(
    ctx: typer.Context,
    campaign_id: int = CampaignIdArgument,
    files: list[str] = typer.Option(..., "--file", help="PNG/JPEG/GIF (повторяемая); всего в наборе не больше 5."),
    launch_after: bool = typer.Option(False, "--launch", help="После сохранения отправить на модерацию."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Добавить изображения в конец набора кампании Мастера — экспериментально.

    Example: {cli} masters images add 72349978 --file banner.png --dry-run
    """
    for path in files:
        _check_image(path)
    _images_mutation(
        ctx,
        "add_master_images",
        f"Добавить {len(files)} изображений в кампанию Мастера {campaign_id}",
        campaign_id,
        {"paths": files, "launch": launch_after},
        confirm,
        headful,
        chrome_dir,
        chrome_profile,
    )


@images_app.command("delete")
@output.guard
def images_delete(
    ctx: typer.Context,
    campaign_id: int = CampaignIdArgument,
    positions: list[int] = typer.Option(None, "--position", help="Позиция с 1 из `masters images list` (повторяемая)."),
    content_ids: list[str] = typer.Option(None, "--content-id", help="Content id изображения (повторяемая)."),
    all_images: bool = typer.Option(False, "--all", help="Удалить все изображения."),
    launch_after: bool = typer.Option(False, "--launch", help="После сохранения отправить на модерацию."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить изображения кампании Мастера по позиции, content id или все — экспериментально.

    Example: {cli} masters images delete 72349978 --position 2 --dry-run
    """
    if not positions and not content_ids and not all_images:
        raise InvalidArguments("Укажите, что удалить: --position, --content-id или --all.")
    kwargs = {
        "positions": one_based("--position", positions) or None,
        "content_ids": content_ids or None,
        "all_images": all_images,
        "launch": launch_after,
    }
    _images_mutation(
        ctx,
        "delete_master_images",
        f"Удалить изображения кампании Мастера {campaign_id}",
        campaign_id,
        kwargs,
        confirm,
        headful,
        chrome_dir,
        chrome_profile,
    )


@images_app.command("set")
@output.guard
def images_set(
    ctx: typer.Context,
    campaign_id: int = CampaignIdArgument,
    files: list[str] = typer.Option(..., "--file", help="PNG/JPEG/GIF нового набора (повторяемая, до 5)."),
    launch_after: bool = typer.Option(False, "--launch", help="После сохранения отправить на модерацию."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Заменить весь набор изображений кампании Мастера переданными файлами — экспериментально.

    Example: {cli} masters images set 72349978 --file banner.png --dry-run
    """
    if len(files) > IMAGE_SLOTS:
        raise InvalidArguments(f"В наборе не больше {IMAGE_SLOTS} изображений.")
    for path in files:
        _check_image(path)
    _images_mutation(
        ctx,
        "set_master_images",
        f"Заменить набор изображений кампании Мастера {campaign_id}",
        campaign_id,
        {"paths": files, "launch": launch_after},
        confirm,
        headful,
        chrome_dir,
        chrome_profile,
    )
