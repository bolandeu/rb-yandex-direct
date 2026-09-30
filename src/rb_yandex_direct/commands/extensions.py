"""Дополнения к объявлениям и связанные данные: `yd sitelinks`, `yd vcards`, `yd extensions`,
`yd turbo`, `yd businesses`, `yd leads`."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import typer

from .. import output
from ..core import services
from ..core.ads import compact, items_from_json
from ..core.errors import InvalidArguments
from ._common import FromJsonOption, IdsArgument, emit_list, mutate, read_json

sitelinks_app = output.group("Наборы быстрых ссылок: список, создание, удаление (сервис Sitelinks).")
vcards_app = output.group("Визитки — контактная информация объявлений (сервис VCards).")
extensions_app = output.group("Уточнения объявлений (callouts): список, создание, удаление (сервис AdExtensions).")
turbo_app = output.group("Турбо-страницы кабинета (сервис TurboPages).")


class ExtensionState(StrEnum):
    ON = "ON"
    DELETED = "DELETED"


class ExtensionStatus(StrEnum):
    DRAFT = "DRAFT"
    MODERATION = "MODERATION"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


def _delete(ctx: typer.Context, service: str, what: str, ids: list[int], confirm: bool) -> None:
    mutate(
        ctx,
        title=f"Удалить {what} {', '.join(map(str, ids))}",
        service=service,
        method="delete",
        params={"SelectionCriteria": {"Ids": ids}},
        confirm=confirm,
    )


# --- sitelinks ----------------------------------------------------------------------------------


def _sitelinks_columns() -> list:
    def links(s: dict) -> str:
        return " · ".join(link.get("Title", "") for link in s.get("Sitelinks") or [])

    return [("Id", "Id"), ("Ссылок", lambda s: len(s.get("Sitelinks") or [])), ("Заголовки", links)]


@sitelinks_app.command("list")
@output.guard
def sitelinks_list(
    ctx: typer.Context,
    ids: list[int] = typer.Option(None, "--id", help="Только эти наборы (повторяемая)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Наборы быстрых ссылок кабинета.

    --json: {"ok": true, "count": N, "sitelinks_sets": [{Id, Sitelinks: [{Title, Href, Description, TurboPageId}]}]}.

    Example: {cli} sitelinks list --json
    """
    items = services.run(services.direct(ctx.obj).list_sitelinks(ids=ids or None))
    emit_list(ctx, "sitelinks_sets", items, _sitelinks_columns(), title="Наборы быстрых ссылок")


def _parse_link(raw: str) -> dict[str, Any]:
    title, _, rest = raw.partition("|")
    href, _, description = rest.partition("|")
    if not title.strip() or not href.strip():
        raise InvalidArguments(f"--link ожидает 'Заголовок|https://…[|Описание]', получено {raw!r}.")
    return compact({"Title": title.strip(), "Href": href.strip(), "Description": description.strip() or None})


def _add_sitelinks_set(ctx: typer.Context, links: list[dict], confirm: bool) -> None:
    if not 1 <= len(links) <= 8:
        raise InvalidArguments(f"В наборе от 1 до 8 ссылок, передано {len(links)}.")
    mutate(
        ctx,
        title=f"Создать набор из {len(links)} быстрых ссылок",
        service="sitelinks",
        method="add",
        params={"SitelinksSets": [{"Sitelinks": links}]},
        confirm=confirm,
    )


@sitelinks_app.command("add")
@output.guard
def sitelinks_add(
    ctx: typer.Context,
    links: list[str] = typer.Option(
        ..., "--link", help="Ссылка 'Заголовок|https://…[|Описание]' (повторяемая, 1–8 шт.)."
    ),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать набор быстрых ссылок; Id набора из ответа — для `ads add-text --sitelink-set`.

    Наборы не редактируются: для правки создайте новый и привяжите к объявлениям.

    Example: {cli} sitelinks add --link 'Доставка|https://example.com/d' --link 'Оплата|https://example.com/p|Картой и наличными' --dry-run
    """
    _add_sitelinks_set(ctx, [_parse_link(link) for link in links], confirm)


@sitelinks_app.command("add-json")
@output.guard
def sitelinks_add_json(
    ctx: typer.Context,
    from_json: str = FromJsonOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать набор быстрых ссылок из JSON: список [{Title, Href?, Description?, TurboPageId?}] (1–8 шт.).

    Example: {cli} sitelinks add-json --from-json sitelinks.json --dry-run
    """
    _add_sitelinks_set(ctx, items_from_json(read_json(from_json), "Sitelinks"), confirm)


@sitelinks_app.command("delete")
@output.guard
def sitelinks_delete(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить наборы быстрых ссылок (привязанные к объявлениям API не удалит).

    Example: {cli} sitelinks delete 1101 --dry-run
    """
    _delete(ctx, "sitelinks", "наборы быстрых ссылок", ids, confirm)


# --- vcards -------------------------------------------------------------------------------------


@vcards_app.command("list")
@output.guard
def vcards_list(
    ctx: typer.Context,
    ids: list[int] = typer.Option(None, "--id", help="Только эти визитки (повторяемая)."),
    campaigns: list[int] = typer.Option(
        None,
        "--campaign",
        help="Визитки этих кампаний (повторяемая; отбор после ответа API — API фильтрует только по Id).",
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Визитки кабинета: адрес, телефон, время работы.

    --json: {"ok": true, "count": N, "vcards": [{Id, CampaignId, Country, City, CompanyName, WorkTime, Phone, …}]}.

    Example: {cli} vcards list --campaign 12345
    """
    items = services.run(services.direct(ctx.obj).list_vcards(ids=ids or None, campaign_ids=campaigns or None))
    columns = [("Id", "Id"), ("Кампания", "CampaignId"), ("Компания", "CompanyName"), ("Город", "City")]
    emit_list(ctx, "vcards", items, columns, title="Визитки")


def _add_vcards(ctx: typer.Context, items: list[dict], confirm: bool) -> None:
    for i, v in enumerate(items):
        missing = [k for k in ("CampaignId", "Country", "City", "CompanyName", "WorkTime", "Phone") if k not in v]
        if missing:
            raise InvalidArguments(f"vcards[{i}]: нет {', '.join(missing)}.")
    mutate(
        ctx,
        title=f"Создать визитки: {len(items)} шт.",
        service="vcards",
        method="add",
        params={"VCards": items},
        confirm=confirm,
    )


@vcards_app.command("add")
@output.guard
def vcards_add(
    ctx: typer.Context,
    campaign_id: int = typer.Option(..., "--campaign", help="Id кампании."),
    country: str = typer.Option(..., "--country", help="Страна."),
    city: str = typer.Option(..., "--city", help="Город."),
    company: str = typer.Option(..., "--company", help="Название организации."),
    work_time: str = typer.Option(
        ...,
        "--work-time",
        help="Время работы в формате API: 'день_с#день_по#час#мин#час#мин', например 0#4#9#00#18#00.",
    ),
    phone_country: str = typer.Option(..., "--phone-country-code", help="Код страны, например +7."),
    phone_city: str = typer.Option(..., "--phone-city-code", help="Код города или оператора, например 495."),
    phone_number: str = typer.Option(..., "--phone-number", help="Номер телефона."),
    phone_ext: str = typer.Option(None, "--phone-extension", help="Добавочный номер."),
    street: str = typer.Option(None, "--street", help="Улица."),
    house: str = typer.Option(None, "--house", help="Дом."),
    building: str = typer.Option(None, "--building", help="Корпус или строение."),
    apartment: str = typer.Option(None, "--apartment", help="Офис или квартира."),
    contact_person: str = typer.Option(None, "--contact-person", help="Контактное лицо."),
    email: str = typer.Option(None, "--email", help="Email."),
    extra: str = typer.Option(None, "--extra-message", help="Подробнее о товаре или услуге."),
    ogrn: str = typer.Option(None, "--ogrn", help="ОГРН организации."),
    metro: int = typer.Option(None, "--metro", help="Id станции метро (справочник регионов)."),
    messenger: str = typer.Option(None, "--messenger", help="Мессенджер 'клиент|логин', например 'telegram|shop'."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать визитку; Id из ответа — для `ads add-text --vcard`.

    Example: {cli} vcards add --campaign 12345 --country Россия --city Москва --company Ромашка --work-time '0#4#9#00#18#00' --phone-country-code +7 --phone-city-code 495 --phone-number 1234567 --dry-run
    """
    im = None
    if messenger:
        client_name, _, login = messenger.partition("|")
        if not login:
            raise InvalidArguments("--messenger ожидает 'клиент|логин'.")
        im = {"MessengerClient": client_name, "MessengerLogin": login}
    item = compact(
        {
            "CampaignId": campaign_id,
            "Country": country,
            "City": city,
            "CompanyName": company,
            "WorkTime": work_time,
            "Phone": compact(
                {
                    "CountryCode": phone_country,
                    "CityCode": phone_city,
                    "PhoneNumber": phone_number,
                    "Extension": phone_ext,
                }
            ),
            "Street": street,
            "House": house,
            "Building": building,
            "Apartment": apartment,
            "ContactPerson": contact_person,
            "ContactEmail": email,
            "ExtraMessage": extra,
            "Ogrn": ogrn,
            "MetroStationId": metro,
            "InstantMessenger": im,
        }
    )
    _add_vcards(ctx, [item], confirm)


@vcards_app.command("add-json")
@output.guard
def vcards_add_json(
    ctx: typer.Context,
    from_json: str = FromJsonOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать визитки из JSON: список VCardAddItem или {"VCards": [...]}.

    Обязательны CampaignId, Country, City, CompanyName, WorkTime, Phone {CountryCode, CityCode, PhoneNumber}.

    Example: {cli} vcards add-json --from-json vcards.json --dry-run
    """
    _add_vcards(ctx, items_from_json(read_json(from_json), "VCards"), confirm)


@vcards_app.command("delete")
@output.guard
def vcards_delete(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить визитки (привязанные к объявлениям API не удалит).

    Example: {cli} vcards delete 1201 --dry-run
    """
    _delete(ctx, "vcards", "визитки", ids, confirm)


# --- extensions (callouts) ----------------------------------------------------------------------


@extensions_app.command("list")
@output.guard
def extensions_list(
    ctx: typer.Context,
    ids: list[int] = typer.Option(None, "--id", help="Только эти уточнения (повторяемая)."),
    states: list[ExtensionState] = typer.Option(None, "--state", help="ON — действующие, DELETED — удалённые."),
    statuses: list[ExtensionStatus] = typer.Option(None, "--status", help="Фильтр по статусу модерации (повторяемая)."),
    modified_since: str = typer.Option(
        None, "--modified-since", help="Изменённые после момента, YYYY-MM-DDThh:mm:ssZ."
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Уточнения (callouts) кабинета.

    --json: {"ok": true, "count": N, "extensions": [{Id, Type, State, Status, StatusClarification, Associated, Callout}]}.

    Example: {cli} extensions list --status REJECTED
    """
    items = services.run(
        services.direct(ctx.obj).list_ad_extensions(
            ids=ids or None,
            states=[s.value for s in states or []] or None,
            statuses=[s.value for s in statuses or []] or None,
            modified_since=modified_since,
        )
    )
    columns = [("Id", "Id"), ("Текст", "Callout.CalloutText"), ("Состояние", "State"), ("Статус", "Status")]
    emit_list(ctx, "extensions", items, columns, title="Уточнения")


@extensions_app.command("add")
@output.guard
def extensions_add(
    ctx: typer.Context,
    texts: list[str] = typer.Argument(..., help="Тексты уточнений, каждый до 25 символов."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать уточнения; Id из ответа — для `ads add-text --callout` и `ads update --callout-add`.

    Example: {cli} extensions add 'Доставка за день' 'Гарантия 2 года' --dry-run
    """
    too_long = [t for t in texts if len(t) > 25]
    if too_long:
        raise InvalidArguments(f"Уточнение длиннее 25 символов: {too_long[0]!r}.")
    mutate(
        ctx,
        title=f"Создать уточнения: {len(texts)} шт.",
        service="adextensions",
        method="add",
        params={"AdExtensions": [{"Callout": {"CalloutText": t}} for t in texts]},
        confirm=confirm,
    )


@extensions_app.command("delete")
@output.guard
def extensions_delete(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить уточнения.

    Example: {cli} extensions delete 1301 --dry-run
    """
    _delete(ctx, "adextensions", "уточнения", ids, confirm)


# --- turbo, businesses, leads -------------------------------------------------------------------


@turbo_app.command("list")
@output.guard
def turbo_list(
    ctx: typer.Context,
    ids: list[int] = typer.Option(None, "--id", help="Только эти турбо-страницы (повторяемая)."),
    hrefs: list[str] = typer.Option(None, "--bound-with-href", help="Привязанные к этому адресу сайта (повторяемая)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Турбо-страницы кабинета.

    --json: {"ok": true, "count": N, "turbo_pages": [{Id, Name, Href, PreviewHref, TurboSiteHref, BoundWithHref}]}.

    Example: {cli} turbo list
    """
    items = services.run(services.direct(ctx.obj).list_turbopages(ids=ids or None, bound_with_hrefs=hrefs or None))
    columns = [("Id", "Id"), ("Название", "Name"), ("Адрес", "Href"), ("Привязана к", "BoundWithHref")]
    emit_list(ctx, "turbo_pages", items, columns, title="Турбо-страницы")


@output.guard
def businesses(
    ctx: typer.Context,
    ids: list[int] = typer.Option(None, "--id", help="Только эти организации (повторяемая)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Организации из Яндекс Бизнеса, доступные кабинету; Id — для `ads add-text --business`.

    --json: {"ok": true, "count": N, "businesses": [{Id, Name, Address, Phone, ProfileUrl, IsPublished}]}.

    Example: {cli} businesses --json
    """
    items = services.run(services.direct(ctx.obj).list_businesses(ids=ids or None))
    columns = [("Id", "Id"), ("Название", "Name"), ("Адрес", "Address"), ("Опубликована", "IsPublished")]
    emit_list(ctx, "businesses", items, columns, title="Организации")


@output.guard
def leads(
    ctx: typer.Context,
    turbo_pages: list[int] = typer.Option(..., "--turbo-page", help="Id турбо-страницы с формой (повторяемая)."),
    date_from: str = typer.Option(None, "--date-from", help="С момента (UTC): YYYY-MM-DD или YYYY-MM-DDThh:mm:ssZ."),
    date_to: str = typer.Option(None, "--date-to", help="По момент (UTC): YYYY-MM-DD или YYYY-MM-DDThh:mm:ssZ."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Заявки (лиды) с форм турбо-страниц.

    Id турбо-страниц — `turbo list`. --json: {"ok": true, "count": N, "leads": [{Id, SubmittedAt,
    TurboPageId, TurboPageName, Data: [{Name, Value}]}]}.

    Example: {cli} leads --turbo-page 3001 --date-from 2026-09-01 --date-to 2026-09-27
    """
    items = services.run(
        services.direct(ctx.obj).list_leads(
            turbo_pages, date_from=_moment(date_from), date_to=_moment(date_to, end=True)
        )
    )
    columns = [("Id", "Id"), ("Когда", "SubmittedAt"), ("Турбо-страница", "TurboPageName"), ("Данные", "Data")]
    emit_list(ctx, "leads", items, columns, title="Лиды")


def _moment(value: str | None, *, end: bool = False) -> str | None:
    """YYYY-MM-DD → начало (или конец) суток в формате API; полный момент — как есть."""
    if value and len(value) == 10:
        return f"{value}T23:59:59Z" if end else f"{value}T00:00:00Z"
    return value
