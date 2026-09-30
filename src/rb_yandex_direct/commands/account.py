"""Кто я и к каким кабинетам есть доступ: `yd whoami`, `yd accounts`, `yd clients`."""

from __future__ import annotations

import typer

from .. import output
from ..core import services
from ..core.client_payloads import client_update_fields
from ..core.errors import InvalidArguments
from ._common import FromJsonOption, emit_list, mutate, read_json

CLIENT_COLUMNS = [
    ("Логин", "Login"),
    ("Имя", "ClientInfo"),
    ("Валюта", "Currency"),
    ("Качество", "AccountQuality"),
]


@output.guard
def whoami(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Проверить токен и показать, чей это кабинет (или клиентов агентства).

    Отказ по учётным данным — AUTH_REQUIRED, exit 3.
    --json: {"ok": true, "count": N, "clients": [{Login, ClientInfo, Currency, AccountQuality}]}.

    Example: {cli} whoami --json
    """
    items = services.run(services.direct(ctx.obj).list_clients())
    emit_list(ctx, "clients", items, CLIENT_COLUMNS, title="Кабинет")


@output.guard
def accounts(
    ctx: typer.Context,
    managed_only: bool = typer.Option(
        False, "--managed-only", help="Только логины из YANDEX_DIRECT_MANAGED_LOGINS, без agencyclients.get."
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Кабинеты, доступные токену: клиенты агентства и кабинеты, где вы представитель.

    Список представительств API не отдаёт — он в YANDEX_DIRECT_MANAGED_LOGINS
    (через запятую). Для каждого логина — clients.get под его Client-Login;
    нет доступа — запись с полем `_error`, а не сбой команды.
    --json: {"ok": true, "count": N, "accounts": [{Login, Currency, AccountQuality, _error?}]}.

    Example: {cli} accounts --json
    """
    items = services.run(services.gather_accounts(ctx.obj, managed_only=managed_only))
    columns = [*CLIENT_COLUMNS, ("Ошибка", "_error")]
    emit_list(ctx, "accounts", items, columns, title="Доступные кабинеты")


clients_app = output.group("Кабинет рекламодателя: параметры и настройки (сервис Clients).")


@clients_app.command("list")
@output.guard
def clients_list(
    ctx: typer.Context,
    fields: list[str] = typer.Option(None, "--field", help="Поле FieldNames вместо набора по умолчанию (повторяемая)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Параметры кабинета (clients.get): для агентства — его клиенты.

    Example: {cli} clients list --field Login --field Currency --json
    """
    items = services.run(services.direct(ctx.obj).list_clients(field_names=fields or None))
    emit_list(ctx, "clients", items, CLIENT_COLUMNS, title="Клиенты")


@clients_app.command("update-json")
@output.guard
def clients_update_json(
    ctx: typer.Context,
    from_json: str = FromJsonOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить настройки кабинета (clients.update) из JSON: ClientUpdateItem или {"Clients": [...]}.

    Example: {cli} clients update-json --from-json client.json --dry-run
    """
    data = read_json(from_json)
    items = data.get("Clients") if isinstance(data, dict) and "Clients" in data else [data]
    mutate(
        ctx,
        title="Изменить настройки кабинета",
        service="clients",
        method="update",
        params={"Clients": items},
        confirm=confirm,
    )


@clients_app.command("update")
@output.guard
def clients_update(
    ctx: typer.Context,
    client_info: str = typer.Option(None, "--client-info", help="Имя/описание кабинета."),
    phone: str = typer.Option(None, "--phone", help="Телефон."),
    email: str = typer.Option(None, "--email", help="Email для уведомлений."),
    lang: str = typer.Option(None, "--lang", help="Язык уведомлений: RU, UK, EN, TR."),
    subscriptions: list[str] = typer.Option(
        None,
        "--subscription",
        help="Подписка ИМЯ=YES|NO: RECEIVE_RECOMMENDATIONS, TRACK_MANAGED_CAMPAIGNS, TRACK_POSITION_CHANGES.",
    ),
    settings: list[str] = typer.Option(
        None, "--setting", help="Настройка ИМЯ=YES|NO: CORRECT_TYPOS_AUTOMATICALLY, DISPLAY_STORE_RATING."
    ),
    tin_type: str = typer.Option(None, "--tin-type", help="Тип ИНН: PHYSICAL, LEGAL, INDIVIDUAL, FOREIGN_*."),
    tin: str = typer.Option(None, "--tin", help="ИНН."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить настройки кабинета (clients.update): имя, контакты, уведомления, ИНН.

    Передаются только заданные поля; данные ЕРИР и прочее — `clients update-json`.

    Example: {cli} clients update --email ads@romashka.ru --subscription TRACK_POSITION_CHANGES=NO --dry-run
    """
    item = client_update_fields(
        client_info=client_info,
        phone=phone,
        email=email,
        lang=lang,
        subscriptions=subscriptions,
        settings=settings,
        tin_type=tin_type,
        tin=tin,
    )
    if not item:
        raise InvalidArguments("Нечего менять: укажите хотя бы одно поле.")
    mutate(
        ctx,
        title="Изменить настройки кабинета",
        service="clients",
        method="update",
        params={"Clients": [item]},
        confirm=confirm,
    )
