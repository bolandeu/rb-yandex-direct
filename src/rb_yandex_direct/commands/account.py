"""Кто я и к каким кабинетам есть доступ: `yd whoami`, `yd accounts`, `yd clients`."""

from __future__ import annotations

import typer

from .. import output
from ..core import services
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
