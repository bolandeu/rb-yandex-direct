"""`yd agency` — клиенты агентства (сервис AgencyClients): список, создание, доступы, настройки."""

from __future__ import annotations

from typing import Any

import typer

from .. import output
from ..core import services
from ..core.client_payloads import (
    AGENCY_CLIENT_FIELDS,
    CURRENCIES,
    PRIVILEGES,
    ROLES,
    SETTINGS_ADD,
    choice,
    client_update_fields,
    notification_add,
    option_items,
)
from ..core.errors import InvalidArguments
from ._common import FromJsonOption, emit_list, mutate, read_json

app = output.group("Клиенты агентства: список, создание, приглашение сотрудников, доступы и настройки.")

COLUMNS = [
    ("ClientId", "ClientId"),
    ("Логин", "Login"),
    ("Имя", "ClientInfo"),
    ("Валюта", "Currency"),
    ("Архив", "Archived"),
    ("Качество", "AccountQuality"),
]

EmailOption = typer.Option(..., "--email", help="Email для уведомлений.")
LangOption = typer.Option("RU", "--lang", help="Язык уведомлений: RU, UK, EN, TR.")
SubscriptionOption = typer.Option(
    None,
    "--subscription",
    help="Подписка ИМЯ=YES|NO: RECEIVE_RECOMMENDATIONS, TRACK_MANAGED_CAMPAIGNS, TRACK_POSITION_CHANGES.",
)
SettingAddOption = typer.Option(
    None,
    "--setting",
    help="Настройка ИМЯ=YES|NO: CORRECT_TYPOS_AUTOMATICALLY, DISPLAY_STORE_RATING, SHARED_ACCOUNT_ENABLED.",
)
GrantOption = typer.Option(None, "--grant", help="Право ИМЯ=YES|NO: EDIT_CAMPAIGNS, IMPORT_XLS, TRANSFER_MONEY.")


@app.command("list")
@output.guard
def list_clients(
    ctx: typer.Context,
    logins: list[str] = typer.Option(None, "--client-login", help="Только эти логины клиентов (повторяемая)."),
    archived: bool = typer.Option(
        None, "--archived/--active", help="Только архивные или только действующие (по умолчанию — все)."
    ),
    fields: list[str] = typer.Option(None, "--field", help="Поле FieldNames вместо всех (повторяемая)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Клиенты агентства со всеми параметрами (agencyclients.get; только агентский токен).

    --json: {"ok": true, "count": N, "clients": [{ClientId, Login, ClientInfo, Currency, Archived,
    Grants, Representatives, Restrictions, Settings, …}]}.

    Example: {cli} agency list --active --json
    """
    criteria: dict[str, Any] = {}
    if logins:
        criteria["Logins"] = logins
    if archived is not None:
        criteria["Archived"] = "YES" if archived else "NO"
    params = {"SelectionCriteria": criteria, "FieldNames": fields or AGENCY_CLIENT_FIELDS}
    items = services.run(services.direct(ctx.obj, login="").list_agency_clients(params))
    emit_list(ctx, "clients", items, COLUMNS, title="Клиенты агентства")


@app.command("add-organization")
@output.guard
def add_organization(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Название организации клиента."),
    currency: str = typer.Option("RUB", "--currency", help="Валюта кабинета: RUB, BYN, KZT, USD, EUR…"),
    email: str = EmailOption,
    lang: str = LangOption,
    subscriptions: list[str] = SubscriptionOption,
    settings: list[str] = SettingAddOption,
    grants: list[str] = GrantOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать клиента агентства как организацию Яндекс ID (agencyclients.addPassportOrganization).

    Замена устаревшего agencyclients.add (новых клиентов-логинов API больше не создаёт, код 3500).
    Сотрудников в организацию приглашает `agency add-member`.
    --json: `result` — {Login, ClientId} созданного клиента.

    Example: {cli} agency add-organization --name 'ООО Ромашка' --email ads@romashka.ru --dry-run
    """
    params: dict[str, Any] = {
        "Name": name,
        "Currency": choice(currency, CURRENCIES, "--currency"),
        "Notification": notification_add(email, lang, subscriptions),
    }
    if settings:
        params["Settings"] = option_items(settings, SETTINGS_ADD, "--setting")
    if grants:
        params["Grants"] = option_items(grants, PRIVILEGES, "--grant", key="Privilege")
    mutate(
        ctx,
        title=f"Создать клиента-организацию «{name}»",
        service="agencyclients",
        method="addPassportOrganization",
        params=params,
        confirm=confirm,
    )


@app.command("add-member")
@output.guard
def add_member(
    ctx: typer.Context,
    organization_login: str = typer.Argument(..., help="Логин организации клиента (из add-organization)."),
    role: str = typer.Option("USER", "--role", help="Роль в организации: ADMIN или USER."),
    invite_email: str = typer.Option(None, "--invite-email", help="Куда отправить приглашение: email."),
    invite_phone: str = typer.Option(None, "--invite-phone", help="Куда отправить приглашение: телефон."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Пригласить сотрудника в организацию клиента (agencyclients.addPassportOrganizationMember).

    Нужен --invite-email и/или --invite-phone.

    Example: {cli} agency add-member romashka-org --role ADMIN --invite-email boss@romashka.ru --dry-run
    """
    invite = {k: v for k, v in (("Email", invite_email), ("Phone", invite_phone)) if v}
    if not invite:
        raise InvalidArguments("Укажите --invite-email и/или --invite-phone.")
    mutate(
        ctx,
        title=f"Пригласить в организацию {organization_login}",
        service="agencyclients",
        method="addPassportOrganizationMember",
        params={
            "PassportOrganizationLogin": organization_login,
            "Role": choice(role, ROLES, "--role"),
            "SendInviteTo": invite,
        },
        confirm=confirm,
    )


@app.command("update")
@output.guard
def update(
    ctx: typer.Context,
    client_id: int = typer.Argument(..., help="ClientId клиента агентства (см. `agency list`)."),
    client_info: str = typer.Option(None, "--client-info", help="Имя/описание клиента."),
    phone: str = typer.Option(None, "--phone", help="Телефон клиента."),
    email: str = typer.Option(None, "--email", help="Email для уведомлений."),
    lang: str = typer.Option(None, "--lang", help="Язык уведомлений: RU, UK, EN, TR."),
    subscriptions: list[str] = SubscriptionOption,
    settings: list[str] = typer.Option(
        None, "--setting", help="Настройка ИМЯ=YES|NO: CORRECT_TYPOS_AUTOMATICALLY, DISPLAY_STORE_RATING."
    ),
    tin_type: str = typer.Option(None, "--tin-type", help="Тип ИНН: PHYSICAL, LEGAL, INDIVIDUAL, FOREIGN_*."),
    tin: str = typer.Option(None, "--tin", help="ИНН клиента."),
    grants: list[str] = GrantOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить клиента агентства: имя, контакты, уведомления, настройки, ИНН, права клиента.

    Передаются только заданные поля. Права (--grant) — что клиент может делать сам
    в своём кабинете. Всё прочее (данные ЕРИР) — `agency update-json`.

    Example: {cli} agency update 777 --grant EDIT_CAMPAIGNS=NO --dry-run
    """
    item: dict[str, Any] = {
        "ClientId": client_id,
        **client_update_fields(
            client_info=client_info,
            phone=phone,
            email=email,
            lang=lang,
            subscriptions=subscriptions,
            settings=settings,
            tin_type=tin_type,
            tin=tin,
        ),
    }
    if grants:
        item["Grants"] = option_items(grants, PRIVILEGES, "--grant", key="Privilege")
    if len(item) == 1:
        raise InvalidArguments("Нечего менять: укажите хотя бы одно поле.")
    mutate(
        ctx,
        title=f"Изменить клиента агентства {client_id}",
        service="agencyclients",
        method="update",
        params={"Clients": [item]},
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
    """Изменить клиентов агентства из JSON: AgencyClientUpdateItem (с ClientId) или {"Clients": [...]}.

    Example: {cli} agency update-json --from-json client.json --dry-run
    """
    data = read_json(from_json)
    items = data.get("Clients") if isinstance(data, dict) and "Clients" in data else data
    items = items if isinstance(items, list) else [items]
    mutate(
        ctx,
        title=f"Изменить клиентов агентства: {len(items)} шт.",
        service="agencyclients",
        method="update",
        params={"Clients": items},
        confirm=confirm,
    )
