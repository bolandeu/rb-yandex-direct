"""`yd adgroups` — группы объявлений (сервис AdGroups)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import typer

from .. import output
from ..core import services
from ..core.ads import compact, items_from_json, validate_adgroups
from ..core.errors import InvalidArguments
from ..providers.direct import DEFAULT_ADGROUP_FIELDS
from ._common import FromJsonOption, IdsArgument, emit_list, emit_object, mutate, read_json, read_lines

app = output.group("Группы объявлений: список, создание по типам, изменение, минус-фразы, удаление.")


class GroupType(StrEnum):
    TEXT_AD_GROUP = "TEXT_AD_GROUP"
    MOBILE_APP_AD_GROUP = "MOBILE_APP_AD_GROUP"
    DYNAMIC_TEXT_AD_GROUP = "DYNAMIC_TEXT_AD_GROUP"
    CPM_BANNER_AD_GROUP = "CPM_BANNER_AD_GROUP"
    CPM_VIDEO_AD_GROUP = "CPM_VIDEO_AD_GROUP"
    UNIFIED_AD_GROUP = "UNIFIED_AD_GROUP"


class Status(StrEnum):
    ACCEPTED = "ACCEPTED"
    DRAFT = "DRAFT"
    MODERATION = "MODERATION"
    PREACCEPTED = "PREACCEPTED"
    REJECTED = "REJECTED"


class ServingStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    RARELY_SERVED = "RARELY_SERVED"


class Kind(StrEnum):
    """Какой блок типа добавить при создании группы (у текстовой — никакого)."""

    text = "text"
    dynamic = "dynamic"
    dynamic_feed = "dynamic-feed"
    mobile_app = "mobile-app"
    smart = "smart"
    unified = "unified"


class Device(StrEnum):
    DEVICE_TYPE_MOBILE = "DEVICE_TYPE_MOBILE"
    DEVICE_TYPE_TABLET = "DEVICE_TYPE_TABLET"


class Carrier(StrEnum):
    WI_FI_ONLY = "WI_FI_ONLY"
    WI_FI_AND_CELLULAR = "WI_FI_AND_CELLULAR"


class YesNo(StrEnum):
    YES = "YES"
    NO = "NO"


_FIELDS_HELP = f"Поле FieldNames вместо набора по умолчанию ({', '.join(DEFAULT_ADGROUP_FIELDS)}); повторяемая."

COLUMNS = [
    ("Id", "Id"),
    ("Название", "Name"),
    ("Кампания", "CampaignId"),
    ("Тип", "Type"),
    ("Статус", "Status"),
    ("Регионы", "RegionIds"),
]


@app.command("list")
@output.guard
def list_adgroups(
    ctx: typer.Context,
    ids: list[int] = typer.Option(None, "--id", help="Только эти группы (повторяемая)."),
    campaigns: list[int] = typer.Option(None, "--campaign", help="Группы этих кампаний (повторяемая)."),
    types: list[GroupType] = typer.Option(None, "--type", help="Фильтр по типу группы (повторяемая)."),
    statuses: list[Status] = typer.Option(None, "--status", help="Фильтр по статусу модерации (повторяемая)."),
    serving: list[ServingStatus] = typer.Option(
        None, "--serving-status", help="ELIGIBLE — показывается, RARELY_SERVED — мало показов (повторяемая)."
    ),
    tags: list[str] = typer.Option(None, "--tag", help="Фильтр по метке группы (повторяемая)."),
    fields: list[str] = typer.Option(None, "--field", help=_FIELDS_HELP),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Список групп объявлений с фильтрами по Id, кампании, типу и статусам.

    API требует хотя бы один из фильтров --id или --campaign.
    --json: {"ok": true, "count": N, "adgroups": [{Id, Name, CampaignId, Type, Status, RegionIds, …}]}.

    Example: {cli} adgroups list --campaign 12345
    """
    if not ids and not campaigns:
        raise InvalidArguments("Укажите --campaign или --id: API не отдаёт группы без фильтра по ним.")
    items = services.run(
        services.direct(ctx.obj).list_adgroups(
            campaign_ids=campaigns or None,
            adgroup_ids=ids or None,
            types=[t.value for t in types or []] or None,
            statuses=[s.value for s in statuses or []] or None,
            serving_statuses=[s.value for s in serving or []] or None,
            tags=tags or None,
            field_names=fields or None,
        )
    )
    emit_list(ctx, "adgroups", items, COLUMNS, title="Группы объявлений")


@app.command("get")
@output.guard
def get_adgroup(
    ctx: typer.Context,
    adgroup_id: int = typer.Argument(..., help="Id группы."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Одна группа со всеми полями, включая блок её типа (мобильное приложение, фид, домен…).

    --json: {"ok": true, "adgroup": {...}}; нет такой группы — INVALID_ARGUMENTS.

    Example: {cli} adgroups get 555 --json
    """
    group = services.run(services.direct(ctx.obj).get_adgroup(adgroup_id))
    if group is None:
        raise InvalidArguments(f"Группа {adgroup_id} не найдена (или нет доступа в этом кабинете).")
    emit_object(ctx, "adgroup", group, title=f"Группа {adgroup_id}")


def _type_block(
    kind: Kind,
    *,
    domain_url: str | None,
    feed_id: int | None,
    feed_categories: list[int] | None,
    store_url: str | None,
    devices: list[Device] | None,
    carrier: Carrier | None,
    os_version: str | None,
    title_source: str | None,
    body_source: str | None,
    offer_retargeting: YesNo | None,
) -> dict[str, Any]:
    """Блок типа для adgroups.add по --type и его опциям."""
    if kind is Kind.text:
        if not feed_id:
            return {}
        return {"TextAdGroupFeedParams": compact({"FeedId": feed_id, "FeedCategoryIds": _items(feed_categories)})}
    if kind is Kind.dynamic:
        _need(domain_url, "--domain-url", kind)
        return {"DynamicTextAdGroup": {"DomainUrl": domain_url}}
    if kind is Kind.dynamic_feed:
        _need(feed_id, "--feed-id", kind)
        return {"DynamicTextFeedAdGroup": {"FeedId": feed_id}}
    if kind is Kind.mobile_app:
        _need(store_url, "--store-url", kind)
        return {
            "MobileAppAdGroup": {
                "StoreUrl": store_url,
                "TargetDeviceType": [d.value for d in devices or list(Device)],
                "TargetCarrier": (carrier or Carrier.WI_FI_AND_CELLULAR).value,
                "TargetOperatingSystemVersion": os_version or "1.0",
            }
        }
    if kind is Kind.smart:
        _need(feed_id, "--feed-id", kind)
        return {
            "SmartAdGroup": compact({"FeedId": feed_id, "AdTitleSource": title_source, "AdBodySource": body_source})
        }
    return {"UnifiedAdGroup": {"OfferRetargeting": (offer_retargeting or YesNo.NO).value}}


def _need(value: object, flag: str, kind: Kind) -> None:
    if not value:
        raise InvalidArguments(f"Для группы типа {kind.value} нужен {flag}.")


def _items(values: list | None) -> dict | None:
    """ArrayOfString/ArrayOfLong API: {"Items": [...]}; пусто — не передавать."""
    return {"Items": values} if values else None


@app.command("add")
@output.guard
def add(
    ctx: typer.Context,
    campaign_id: int = typer.Option(..., "--campaign", help="Id кампании."),
    name: str = typer.Option(..., "--name", help="Название группы."),
    regions: list[int] = typer.Option(..., "--region", help="Id региона показа (повторяемая; 0 — все регионы)."),
    kind: Kind = typer.Option(Kind.text, "--type", help="Тип группы: определяет блок типа в запросе."),
    negative: list[str] = typer.Option(None, "--negative-keyword", help="Минус-фраза группы (повторяемая)."),
    minus_sets: list[int] = typer.Option(None, "--minus-set", help="Id набора общих минус-фраз (повторяемая)."),
    tracking: str = typer.Option(None, "--tracking-params", help="UTM и другие параметры к ссылкам группы."),
    domain_url: str = typer.Option(None, "--domain-url", help="dynamic: домен сайта для динамических объявлений."),
    feed_id: int = typer.Option(None, "--feed-id", help="dynamic-feed, smart, text: Id фида."),
    feed_categories: list[int] = typer.Option(None, "--feed-category", help="text: Id категории фида (повторяемая)."),
    store_url: str = typer.Option(None, "--store-url", help="mobile-app: ссылка на приложение в магазине."),
    devices: list[Device] = typer.Option(
        None, "--device", help="mobile-app: тип устройства (повторяемая; по умолчанию все)."
    ),
    carrier: Carrier = typer.Option(None, "--carrier", help="mobile-app: тип связи (по умолчанию WI_FI_AND_CELLULAR)."),
    os_version: str = typer.Option(None, "--os-version", help="mobile-app: минимальная версия ОС (по умолчанию 1.0)."),
    title_source: str = typer.Option(None, "--ad-title-source", help="smart: поле фида для заголовка."),
    body_source: str = typer.Option(None, "--ad-body-source", help="smart: поле фида для текста."),
    offer_retargeting: YesNo = typer.Option(None, "--offer-retargeting", help="unified: офферный ретаргетинг."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать группу объявлений; --type задаёт тип и нужные ему опции.

    text — обычная (фид необязателен), dynamic — по домену (--domain-url), dynamic-feed и
    smart — по фиду (--feed-id), mobile-app — приложение (--store-url), unified — ЕПК.
    Автотаргетинг и прочие тонкие настройки — через `adgroups add-json`.

    Example: {cli} adgroups add --campaign 12345 --name 'Диваны' --region 213 --dry-run
    """
    item: dict[str, Any] = compact(
        {
            "Name": name,
            "CampaignId": campaign_id,
            "RegionIds": regions,
            "NegativeKeywords": _items(negative),
            "NegativeKeywordSharedSetIds": _items(minus_sets),
            "TrackingParams": tracking,
        }
    )
    item.update(
        _type_block(
            kind,
            domain_url=domain_url,
            feed_id=feed_id,
            feed_categories=feed_categories,
            store_url=store_url,
            devices=devices,
            carrier=carrier,
            os_version=os_version,
            title_source=title_source,
            body_source=body_source,
            offer_retargeting=offer_retargeting,
        )
    )
    validate_adgroups([item])
    mutate(
        ctx,
        title=f"Создать группу «{name}» в кампании {campaign_id}",
        service="adgroups",
        method="add",
        params={"AdGroups": [item]},
        confirm=confirm,
    )


@app.command("update")
@output.guard
def update(
    ctx: typer.Context,
    adgroup_id: int = typer.Argument(..., help="Id группы."),
    name: str = typer.Option(None, "--name", help="Новое название."),
    regions: list[int] = typer.Option(None, "--region", help="Id региона (повторяемая; заменяет весь список)."),
    negative: list[str] = typer.Option(
        None, "--negative-keyword", help="Минус-фраза (повторяемая; заменяет весь список)."
    ),
    minus_sets: list[int] = typer.Option(
        None, "--minus-set", help="Id набора общих минус-фраз (повторяемая; заменяет список)."
    ),
    tracking: str = typer.Option(None, "--tracking-params", help="Параметры к ссылкам; пустая строка — убрать."),
    domain_url: str = typer.Option(None, "--domain-url", help="Динамическая группа: новый домен."),
    offer_retargeting: YesNo = typer.Option(None, "--offer-retargeting", help="Группа ЕПК: офферный ретаргетинг."),
    title_source: str = typer.Option(None, "--ad-title-source", help="Смарт-группа: поле фида для заголовка."),
    body_source: str = typer.Option(None, "--ad-body-source", help="Смарт-группа: поле фида для текста."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить группу: название, регионы, минус-фразы, параметры ссылок и поля её типа.

    Списки (регионы, минус-фразы, наборы) заменяются целиком. Остальное — `adgroups update-json`.

    Example: {cli} adgroups update 555 --name 'Диваны Москва' --region 213 --dry-run
    """
    item: dict[str, Any] = compact(
        {
            "Id": adgroup_id,
            "Name": name,
            "RegionIds": regions,
            "NegativeKeywords": _items(negative),
            "NegativeKeywordSharedSetIds": _items(minus_sets),
        }
    )
    if tracking is not None:
        item["TrackingParams"] = tracking
    blocks = {
        "DynamicTextAdGroup": compact({"DomainUrl": domain_url}),
        "UnifiedAdGroup": compact({"OfferRetargeting": offer_retargeting.value if offer_retargeting else None}),
        "SmartAdGroup": compact({"AdTitleSource": title_source, "AdBodySource": body_source}),
    }
    item.update({key: block for key, block in blocks.items() if block})
    if len(item) == 1:
        raise InvalidArguments("Нечего менять: укажите хотя бы одну опцию.")
    validate_adgroups([item], update=True)
    mutate(
        ctx,
        title=f"Изменить группу {adgroup_id}",
        service="adgroups",
        method="update",
        params={"AdGroups": [item]},
        confirm=confirm,
    )


@app.command("set-negative-keywords")
@output.guard
def set_negative_keywords(
    ctx: typer.Context,
    adgroup_id: int = typer.Argument(..., help="Id группы."),
    words: list[str] = typer.Option(None, "--word", "-w", help="Минус-фраза (повторяемая)."),
    from_file: str = typer.Option(None, "--from-file", help="Файл с минус-фразами, по одной в строке."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Заменить минус-фразы группы: переданный список целиком заменяет текущий.

    Example: {cli} adgroups set-negative-keywords 555 -w бу -w ремонт --dry-run
    """
    phrases = read_lines(words, from_file)
    if not phrases:
        raise InvalidArguments("Укажите минус-фразы: --word или --from-file.")
    mutate(
        ctx,
        title=f"Минус-фразы группы {adgroup_id}: {len(phrases)} шт.",
        service="adgroups",
        method="update",
        params={"AdGroups": [{"Id": adgroup_id, "NegativeKeywords": {"Items": phrases}}]},
        confirm=confirm,
    )


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
    """Удалить группы объявлений — необратимо; удаляются только группы без показов.

    Example: {cli} adgroups delete 555 --dry-run
    """
    mutate(
        ctx,
        title=f"Удалить группы {', '.join(map(str, ids))}",
        service="adgroups",
        method="delete",
        params={"SelectionCriteria": {"Ids": ids}},
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
    """Создать группы из JSON: список AdGroupAddItem или {"AdGroups": [...]}.

    Так задаются автотаргетинг (AutotargetingSettings), CPM-группы и всё, чего нет в `adgroups add`.

    Example: {cli} adgroups add-json --from-json adgroups.json --dry-run
    """
    items = items_from_json(read_json(from_json), "AdGroups")
    validate_adgroups(items)
    mutate(
        ctx,
        title=f"Создать группы: {len(items)} шт.",
        service="adgroups",
        method="add",
        params={"AdGroups": items},
        confirm=confirm,
    )


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
    """Изменить группы из JSON: список AdGroupUpdateItem (с Id) или {"AdGroups": [...]}.

    Example: {cli} adgroups update-json --from-json adgroups-update.json --dry-run
    """
    items = items_from_json(read_json(from_json), "AdGroups")
    validate_adgroups(items, update=True)
    mutate(
        ctx,
        title=f"Изменить группы: {len(items)} шт.",
        service="adgroups",
        method="update",
        params={"AdGroups": items},
        confirm=confirm,
    )
