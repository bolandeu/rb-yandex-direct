"""`yd ads` — объявления (сервис Ads)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import typer

from .. import output
from ..core import services
from ..core.ads import (
    callout_setting,
    compact,
    items_from_json,
    mobile_app_features,
    price_extension,
    validate_ads,
)
from ..core.errors import InvalidArguments
from ._common import FromJsonOption, IdsArgument, emit_list, emit_object, mutate, read_json

app = output.group("Объявления: список, создание по типам, изменение, модерация, статусы, удаление.")


class State(StrEnum):
    ON = "ON"
    OFF = "OFF"
    SUSPENDED = "SUSPENDED"
    OFF_BY_MONITORING = "OFF_BY_MONITORING"
    ARCHIVED = "ARCHIVED"


class Status(StrEnum):
    DRAFT = "DRAFT"
    MODERATION = "MODERATION"
    PREACCEPTED = "PREACCEPTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AdType(StrEnum):
    TEXT_AD = "TEXT_AD"
    MOBILE_APP_AD = "MOBILE_APP_AD"
    DYNAMIC_TEXT_AD = "DYNAMIC_TEXT_AD"
    IMAGE_AD = "IMAGE_AD"
    CPC_VIDEO_AD = "CPC_VIDEO_AD"
    CPM_BANNER_AD = "CPM_BANNER_AD"
    CPM_VIDEO_AD = "CPM_VIDEO_AD"
    SMART_AD = "SMART_AD"
    SHOPPING_AD = "SHOPPING_AD"
    LISTING_AD = "LISTING_AD"


class YesNo(StrEnum):
    YES = "YES"
    NO = "NO"


class PriceQualifier(StrEnum):
    NONE = "NONE"
    FROM = "FROM"
    UP_TO = "UP_TO"


class Action(StrEnum):
    DOWNLOAD = "DOWNLOAD"
    GET = "GET"
    INSTALL = "INSTALL"
    MORE = "MORE"
    OPEN = "OPEN"
    UPDATE = "UPDATE"
    PLAY = "PLAY"
    BUY_AUTODETECT = "BUY_AUTODETECT"


COLUMNS = [
    ("Id", "Id"),
    ("Группа", "AdGroupId"),
    ("Кампания", "CampaignId"),
    ("Тип", "Type"),
    ("Состояние", "State"),
    ("Статус", "Status"),
    ("Заголовок", lambda a: (a.get("TextAd") or {}).get("Title")),
]

# Общие опции изменяющих команд.
_CONFIRM = output.ConfirmOption
_DRY = output.DryRunOption
_NI = output.NonInteractiveOption


@app.command("list")
@output.guard
def list_ads(
    ctx: typer.Context,
    ids: list[int] = typer.Option(None, "--id", help="Только эти объявления (повторяемая)."),
    campaigns: list[int] = typer.Option(None, "--campaign", help="Объявления этих кампаний (повторяемая)."),
    adgroups: list[int] = typer.Option(None, "--adgroup", help="Объявления этих групп (повторяемая)."),
    states: list[State] = typer.Option(None, "--state", help="Фильтр по состоянию (повторяемая)."),
    statuses: list[Status] = typer.Option(None, "--status", help="Фильтр по статусу модерации (повторяемая)."),
    types: list[AdType] = typer.Option(None, "--type", help="Фильтр по типу объявления (повторяемая)."),
    mobile: YesNo = typer.Option(None, "--mobile", help="Только мобильные (YES) или только обычные (NO)."),
    vcards: list[int] = typer.Option(None, "--vcard", help="С этой визиткой (повторяемая)."),
    sitelink_sets: list[int] = typer.Option(
        None, "--sitelink-set", help="С этим набором быстрых ссылок (повторяемая)."
    ),
    image_hashes: list[str] = typer.Option(None, "--image-hash", help="С этим изображением (повторяемая)."),
    extensions: list[int] = typer.Option(None, "--extension", help="С этим уточнением (повторяемая)."),
    fields: list[str] = typer.Option(None, "--field", help="Поле FieldNames вместо набора по умолчанию (повторяемая)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Список объявлений с фильтрами; поля TextAd (заголовок, текст, ссылка) — по умолчанию.

    API требует хотя бы один из фильтров --id, --campaign, --adgroup.
    --json: {"ok": true, "count": N, "ads": [{Id, AdGroupId, CampaignId, Type, State, Status, TextAd, …}]}.

    Example: {cli} ads list --campaign 12345 --status REJECTED
    """
    if not (ids or campaigns or adgroups):
        raise InvalidArguments("Укажите --campaign, --adgroup или --id: API не отдаёт объявления без них.")
    extra = compact(
        {
            "Mobile": mobile.value if mobile else None,
            "VCardIds": vcards,
            "SitelinkSetIds": sitelink_sets,
            "AdImageHashes": image_hashes,
            "AdExtensionIds": extensions,
        }
    )
    items = services.run(
        services.direct(ctx.obj).list_ads(
            ad_ids=ids or None,
            campaign_ids=campaigns or None,
            adgroup_ids=adgroups or None,
            states=[s.value for s in states or []] or None,
            statuses=[s.value for s in statuses or []] or None,
            types=[t.value for t in types or []] or None,
            field_names=fields or None,
            extra_criteria=extra or None,
        )
    )
    emit_list(ctx, "ads", items, COLUMNS, title="Объявления")


@app.command("get")
@output.guard
def get_ad(
    ctx: typer.Context,
    ad_id: int = typer.Argument(..., help="Id объявления."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Одно объявление со всеми полями его типа (TextAd, ResponsiveAd, MobileAppAd…).

    --json: {"ok": true, "ad": {...}}; нет такого объявления — INVALID_ARGUMENTS.

    Example: {cli} ads get 777 --json
    """
    ad = services.run(services.direct(ctx.obj).get_ad(ad_id))
    if ad is None:
        raise InvalidArguments(f"Объявление {ad_id} не найдено (или нет доступа в этом кабинете).")
    emit_object(ctx, "ad", ad, title=f"Объявление {ad_id}")


@app.command("moderation")
@output.guard
def moderation(
    ctx: typer.Context,
    campaigns: list[int] = typer.Option(..., "--campaign", help="Кампания (повторяемая)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Объявления, не прошедшие модерацию до конца: черновики, на модерации и отклонённые.

    --json: {"ok": true, "count": N, "ads": [...]}; причина отказа — в StatusClarification.

    Example: {cli} ads moderation --campaign 12345
    """
    items = services.run(
        services.direct(ctx.obj).list_ads(
            campaign_ids=campaigns,
            statuses=["DRAFT", "MODERATION", "PREACCEPTED", "REJECTED"],
            field_names=["Id", "AdGroupId", "CampaignId", "Type", "State", "Status", "StatusClarification"],
        )
    )
    columns = [*COLUMNS[:6], ("Причина", "StatusClarification")]
    emit_list(ctx, "ads", items, columns, title="Объявления на модерации и отклонённые")


def _ids_mutation(ctx: typer.Context, method: str, verb: str, ids: list[int], confirm: bool) -> None:
    mutate(
        ctx,
        title=f"{verb} объявления {', '.join(map(str, ids))}",
        service="ads",
        method=method,
        params={"SelectionCriteria": {"Ids": ids}},
        confirm=confirm,
    )


@app.command("moderate")
@output.guard
def moderate(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = _CONFIRM,
    dry_run: bool = _DRY,
    non_interactive: bool = _NI,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Отправить черновики объявлений на модерацию.

    Example: {cli} ads moderate 777 778 --confirm
    """
    _ids_mutation(ctx, "moderate", "На модерацию:", ids, confirm)


@app.command("suspend")
@output.guard
def suspend(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = _CONFIRM,
    dry_run: bool = _DRY,
    non_interactive: bool = _NI,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Остановить показы объявлений.

    Example: {cli} ads suspend 777 --confirm
    """
    _ids_mutation(ctx, "suspend", "Остановить", ids, confirm)


@app.command("resume")
@output.guard
def resume(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = _CONFIRM,
    dry_run: bool = _DRY,
    non_interactive: bool = _NI,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Возобновить показы остановленных объявлений.

    Example: {cli} ads resume 777 --confirm
    """
    _ids_mutation(ctx, "resume", "Возобновить", ids, confirm)


@app.command("archive")
@output.guard
def archive(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = _CONFIRM,
    dry_run: bool = _DRY,
    non_interactive: bool = _NI,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Архивировать объявления.

    Example: {cli} ads archive 777 --confirm
    """
    _ids_mutation(ctx, "archive", "Архивировать", ids, confirm)


@app.command("unarchive")
@output.guard
def unarchive(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = _CONFIRM,
    dry_run: bool = _DRY,
    non_interactive: bool = _NI,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Вернуть объявления из архива.

    Example: {cli} ads unarchive 777 --confirm
    """
    _ids_mutation(ctx, "unarchive", "Разархивировать", ids, confirm)


@app.command("delete")
@output.guard
def delete(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = _CONFIRM,
    dry_run: bool = _DRY,
    non_interactive: bool = _NI,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить объявления — необратимо; удаляются только черновики и объявления без показов.

    Example: {cli} ads delete 777 --dry-run
    """
    _ids_mutation(ctx, "delete", "Удалить", ids, confirm)


def _add(ctx: typer.Context, adgroup_id: int, block: str, body: dict[str, Any], confirm: bool) -> None:
    item = {"AdGroupId": adgroup_id, block: compact(body)}
    validate_ads([item])
    mutate(
        ctx,
        title=f"Создать объявление {block} в группе {adgroup_id}",
        service="ads",
        method="add",
        params={"Ads": [item]},
        confirm=confirm,
    )


@app.command("add-text")
@output.guard
def add_text(
    ctx: typer.Context,
    adgroup_id: int = typer.Option(..., "--adgroup", help="Id группы объявлений."),
    title: str = typer.Option(..., "--title", help="Заголовок (до 56 символов)."),
    text: str = typer.Option(..., "--text", help="Текст (до 81 символа)."),
    href: str = typer.Option(None, "--href", help="Ссылка на сайт (нужна она или --turbo)."),
    title2: str = typer.Option(None, "--title2", help="Второй заголовок (до 30 символов)."),
    display_url_path: str = typer.Option(None, "--display-url-path", help="Отображаемый путь ссылки (до 20 символов)."),
    final_url: str = typer.Option(None, "--final-url", help="Конечный адрес после редиректов трекера."),
    mobile: YesNo = typer.Option(YesNo.NO, "--mobile", help="Мобильное объявление."),
    image_hash: str = typer.Option(None, "--image-hash", help="Хэш изображения (`images add`)."),
    sitelink_set: int = typer.Option(None, "--sitelink-set", help="Id набора быстрых ссылок."),
    vcard: int = typer.Option(None, "--vcard", help="Id визитки."),
    turbo: int = typer.Option(None, "--turbo", help="Id турбо-страницы."),
    business: int = typer.Option(None, "--business", help="Id организации из Яндекс Бизнеса."),
    callouts: list[int] = typer.Option(None, "--callout", help="Id уточнения (повторяемая)."),
    video: int = typer.Option(None, "--video-extension", help="Id креатива-видеодополнения."),
    price: float = typer.Option(None, "--price", help="Цена в прайс-дополнении, в валюте кабинета."),
    old_price: float = typer.Option(None, "--old-price", help="Старая цена в прайс-дополнении."),
    price_qualifier: PriceQualifier = typer.Option(
        None, "--price-qualifier", help="Уточнение цены: NONE, FROM, UP_TO."
    ),
    currency: str = typer.Option("RUB", "--price-currency", help="Валюта прайс-дополнения."),
    erir: str = typer.Option(None, "--erir-description", help="Описание объекта рекламы для ЕРИР (маркировка)."),
    confirm: bool = _CONFIRM,
    dry_run: bool = _DRY,
    non_interactive: bool = _NI,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать текстово-графическое объявление (TextAd).

    Example: {cli} ads add-text --adgroup 555 --title 'Диваны от 9990 ₽' --text 'Доставка за день' --href https://example.com --dry-run
    """
    if not (href or turbo):
        raise InvalidArguments("Нужна ссылка: --href или --turbo.")
    body = {
        "Title": title,
        "Title2": title2,
        "Text": text,
        "Href": href,
        "FinalUrl": final_url,
        "DisplayUrlPath": display_url_path,
        "Mobile": mobile.value,
        "AdImageHash": image_hash,
        "SitelinkSetId": sitelink_set,
        "VCardId": vcard,
        "TurboPageId": turbo,
        "BusinessId": business,
        "AdExtensionIds": callouts,
        "VideoExtension": {"CreativeId": video} if video else None,
        "PriceExtension": price_extension(
            services.micros(price),
            services.micros(old_price),
            price_qualifier.value if price_qualifier else None,
            currency,
        ),
        "ErirAdDescription": erir,
    }
    _add(ctx, adgroup_id, "TextAd", body, confirm)


@app.command("add-responsive")
@output.guard
def add_responsive(
    ctx: typer.Context,
    adgroup_id: int = typer.Option(..., "--adgroup", help="Id группы объявлений."),
    titles: list[str] = typer.Option(..., "--title", help="Вариант заголовка (повторяемая)."),
    texts: list[str] = typer.Option(..., "--text", help="Вариант текста (повторяемая)."),
    href: str = typer.Option(None, "--href", help="Ссылка на сайт."),
    image_hashes: list[str] = typer.Option(None, "--image-hash", help="Хэш изображения (повторяемая)."),
    videos: list[int] = typer.Option(None, "--video-extension", help="Id видеодополнения (повторяемая)."),
    display_url_path: str = typer.Option(None, "--display-url-path", help="Отображаемый путь ссылки."),
    sitelink_set: int = typer.Option(None, "--sitelink-set", help="Id набора быстрых ссылок."),
    callouts: list[int] = typer.Option(None, "--callout", help="Id уточнения (повторяемая)."),
    business: int = typer.Option(None, "--business", help="Id организации из Яндекс Бизнеса."),
    age_label: str = typer.Option(None, "--age-label", help="Возрастная метка: AGE_0…AGE_18 или MONTHS_0…MONTHS_12."),
    erir: str = typer.Option(None, "--erir-description", help="Описание объекта рекламы для ЕРИР."),
    confirm: bool = _CONFIRM,
    dry_run: bool = _DRY,
    non_interactive: bool = _NI,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать адаптивное объявление (ResponsiveAd): Директ сам комбинирует заголовки, тексты и картинки.

    Example: {cli} ads add-responsive --adgroup 555 --title 'Диваны' --title 'Диваны от 9990 ₽' --text 'Доставка за день' --href https://example.com --dry-run
    """
    body = {
        "Titles": titles,
        "Texts": texts,
        "Href": href,
        "AdImageHashes": image_hashes,
        "VideoExtensionIds": videos,
        "DisplayUrlPath": display_url_path,
        "SitelinkSetId": sitelink_set,
        "AdExtensionIds": callouts,
        "BusinessId": business,
        "AgeLabel": age_label,
        "ErirAdDescription": erir,
    }
    _add(ctx, adgroup_id, "ResponsiveAd", body, confirm)


@app.command("add-mobile-app")
@output.guard
def add_mobile_app(
    ctx: typer.Context,
    adgroup_id: int = typer.Option(..., "--adgroup", help="Id группы (тип MOBILE_APP_AD_GROUP)."),
    title: str = typer.Option(..., "--title", help="Заголовок."),
    text: str = typer.Option(..., "--text", help="Текст."),
    action: Action = typer.Option(Action.INSTALL, "--action", help="Надпись на кнопке."),
    tracking_url: str = typer.Option(None, "--tracking-url", help="Трекинговая ссылка (AppMetrica, AppsFlyer…)."),
    image_hash: str = typer.Option(None, "--image-hash", help="Хэш изображения."),
    features: list[str] = typer.Option(
        None, "--feature", help="Показ данных из магазина: PRICE|ICON|CUSTOMER_RATING|RATINGS=YES|NO (повторяемая)."
    ),
    age_label: str = typer.Option(None, "--age-label", help="Возрастная метка: AGE_0, AGE_6, AGE_12, AGE_16, AGE_18."),
    erir: str = typer.Option(None, "--erir-description", help="Описание объекта рекламы для ЕРИР."),
    confirm: bool = _CONFIRM,
    dry_run: bool = _DRY,
    non_interactive: bool = _NI,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать объявление мобильного приложения (MobileAppAd).

    Example: {cli} ads add-mobile-app --adgroup 555 --title 'Игра' --text 'Скачай бесплатно' --feature ICON=YES --dry-run
    """
    body = {
        "Title": title,
        "Text": text,
        "Action": action.value,
        "TrackingUrl": tracking_url,
        "AdImageHash": image_hash,
        "Features": mobile_app_features(features or []),
        "AgeLabel": age_label,
        "ErirAdDescription": erir,
    }
    _add(ctx, adgroup_id, "MobileAppAd", body, confirm)


@app.command("add-image")
@output.guard
def add_image(
    ctx: typer.Context,
    adgroup_id: int = typer.Option(..., "--adgroup", help="Id группы объявлений."),
    image_hash: str = typer.Option(..., "--image-hash", help="Хэш изображения-баннера (`images add`)."),
    href: str = typer.Option(None, "--href", help="Ссылка на сайт (нужна она или --turbo)."),
    turbo: int = typer.Option(None, "--turbo", help="Id турбо-страницы."),
    erir: str = typer.Option(None, "--erir-description", help="Описание объекта рекламы для ЕРИР."),
    confirm: bool = _CONFIRM,
    dry_run: bool = _DRY,
    non_interactive: bool = _NI,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать графическое объявление из изображения (TextImageAd).

    Example: {cli} ads add-image --adgroup 555 --image-hash abc123hash --href https://example.com --dry-run
    """
    if not (href or turbo):
        raise InvalidArguments("Нужна ссылка: --href или --turbo.")
    body = {"AdImageHash": image_hash, "Href": href, "TurboPageId": turbo, "ErirAdDescription": erir}
    _add(ctx, adgroup_id, "TextImageAd", body, confirm)


@app.command("add-builder")
@output.guard
def add_builder(
    ctx: typer.Context,
    adgroup_id: int = typer.Option(..., "--adgroup", help="Id группы объявлений."),
    creative: int = typer.Option(..., "--creative", help="Id креатива из конструктора (`creatives list`)."),
    href: str = typer.Option(None, "--href", help="Ссылка на сайт (нужна она или --turbo)."),
    turbo: int = typer.Option(None, "--turbo", help="Id турбо-страницы."),
    erir: str = typer.Option(None, "--erir-description", help="Описание объекта рекламы для ЕРИР."),
    confirm: bool = _CONFIRM,
    dry_run: bool = _DRY,
    non_interactive: bool = _NI,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать графическое объявление из креатива конструктора (TextAdBuilderAd).

    Example: {cli} ads add-builder --adgroup 555 --creative 9001 --href https://example.com --dry-run
    """
    if not (href or turbo):
        raise InvalidArguments("Нужна ссылка: --href или --turbo.")
    body = {"Creative": {"CreativeId": creative}, "Href": href, "TurboPageId": turbo, "ErirAdDescription": erir}
    _add(ctx, adgroup_id, "TextAdBuilderAd", body, confirm)


@app.command("add-shopping")
@output.guard
def add_shopping(
    ctx: typer.Context,
    adgroup_id: int = typer.Option(..., "--adgroup", help="Id группы объявлений."),
    feed: int = typer.Option(..., "--feed", help="Id фида товаров."),
    default_texts: list[str] = typer.Option(..., "--default-text", help="Текст по умолчанию (повторяемая)."),
    title_sources: list[str] = typer.Option(None, "--title-source", help="Поле фида для заголовка (повторяемая)."),
    text_sources: list[str] = typer.Option(None, "--text-source", help="Поле фида для текста (повторяемая)."),
    sitelink_set: int = typer.Option(None, "--sitelink-set", help="Id набора быстрых ссылок."),
    callouts: list[int] = typer.Option(None, "--callout", help="Id уточнения (повторяемая)."),
    business: int = typer.Option(None, "--business", help="Id организации из Яндекс Бизнеса."),
    listing: bool = typer.Option(False, "--listing", help="Создать ListingAd (каталог) вместо ShoppingAd."),
    confirm: bool = _CONFIRM,
    dry_run: bool = _DRY,
    non_interactive: bool = _NI,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать товарное объявление по фиду (ShoppingAd, с --listing — ListingAd).

    Фильтры товаров (FeedFilterConditions) — через `ads add-json`.

    Example: {cli} ads add-shopping --adgroup 555 --feed 7001 --default-text 'Диваны со скидкой' --dry-run
    """
    body = {
        "FeedId": feed,
        "DefaultTexts": default_texts,
        "TitleSources": title_sources,
        "TextSources": text_sources,
        "SitelinkSetId": sitelink_set,
        "AdExtensionIds": callouts,
        "BusinessId": business,
    }
    _add(ctx, adgroup_id, "ListingAd" if listing else "ShoppingAd", body, confirm)


@app.command("update")
@output.guard
def update(
    ctx: typer.Context,
    ad_id: int = typer.Argument(..., help="Id текстового объявления."),
    title: str = typer.Option(None, "--title", help="Новый заголовок."),
    title2: str = typer.Option(None, "--title2", help="Новый второй заголовок."),
    text: str = typer.Option(None, "--text", help="Новый текст."),
    href: str = typer.Option(None, "--href", help="Новая ссылка."),
    display_url_path: str = typer.Option(None, "--display-url-path", help="Новый отображаемый путь."),
    image_hash: str = typer.Option(None, "--image-hash", help="Новое изображение; пустая строка — убрать."),
    sitelink_set: int = typer.Option(None, "--sitelink-set", help="Id набора быстрых ссылок."),
    vcard: int = typer.Option(None, "--vcard", help="Id визитки."),
    turbo: int = typer.Option(None, "--turbo", help="Id турбо-страницы."),
    callout_add: list[int] = typer.Option(None, "--callout-add", help="Добавить уточнение (повторяемая)."),
    callout_remove: list[int] = typer.Option(None, "--callout-remove", help="Убрать уточнение (повторяемая)."),
    callout_set: list[int] = typer.Option(None, "--callout-set", help="Заменить уточнения этими (повторяемая)."),
    erir: str = typer.Option(None, "--erir-description", help="Описание объекта рекламы для ЕРИР."),
    confirm: bool = _CONFIRM,
    dry_run: bool = _DRY,
    non_interactive: bool = _NI,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить текстовое объявление (TextAd); после изменения оно снова уходит на модерацию.

    Другие типы объявлений — `ads update-json`.

    Example: {cli} ads update 777 --title 'Диваны от 8990 ₽' --callout-add 1301 --dry-run
    """
    body = compact(
        {
            "Title": title,
            "Title2": title2,
            "Text": text,
            "Href": href,
            "DisplayUrlPath": display_url_path,
            "SitelinkSetId": sitelink_set,
            "VCardId": vcard,
            "TurboPageId": turbo,
            "CalloutSetting": callout_setting(callout_add or [], callout_remove or [], callout_set or []),
            "ErirAdDescription": erir,
        }
    )
    if image_hash is not None:
        body["AdImageHash"] = image_hash or None
    if not body:
        raise InvalidArguments("Нечего менять: укажите хотя бы одну опцию.")
    item = {"Id": ad_id, "TextAd": body}
    mutate(
        ctx,
        title=f"Изменить объявление {ad_id}",
        service="ads",
        method="update",
        params={"Ads": [item]},
        confirm=confirm,
    )


@app.command("add-json")
@output.guard
def add_json(
    ctx: typer.Context,
    from_json: str = FromJsonOption,
    confirm: bool = _CONFIRM,
    dry_run: bool = _DRY,
    non_interactive: bool = _NI,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать объявления из JSON: список AdAddItem или {"Ads": [...]} — любой тип, до 1000 за вызов.

    У каждого — AdGroupId и ровно один блок типа (TextAd, ResponsiveAd, MobileAppAd, SmartAdBuilderAd…).

    Example: {cli} ads add-json --from-json ads.json --dry-run
    """
    items = items_from_json(read_json(from_json), "Ads")
    validate_ads(items)
    mutate(
        ctx,
        title=f"Создать объявления: {len(items)} шт.",
        service="ads",
        method="add",
        params={"Ads": items},
        confirm=confirm,
    )


@app.command("update-json")
@output.guard
def update_json(
    ctx: typer.Context,
    from_json: str = FromJsonOption,
    confirm: bool = _CONFIRM,
    dry_run: bool = _DRY,
    non_interactive: bool = _NI,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить объявления из JSON: список AdUpdateItem (Id + один блок типа) или {"Ads": [...]}.

    Example: {cli} ads update-json --from-json ads-update.json --dry-run
    """
    items = items_from_json(read_json(from_json), "Ads")
    validate_ads(items, update=True)
    mutate(
        ctx,
        title=f"Изменить объявления: {len(items)} шт.",
        service="ads",
        method="update",
        params={"Ads": items},
        confirm=confirm,
    )
