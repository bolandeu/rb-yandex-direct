"""CLI rb-yandex-direct — Яндекс.Директ API v5.

Голый `rb-yandex-direct` (и любая группа без подкоманды) печатает справку.
Токен — из keychain/переменных окружения через rb-yandex-oauth (см. core/auth.py).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
from loguru import logger
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from yandex_oauth.errors import CliError
from yandex_oauth.oauth import TokenSet, parse_manual_token

from rb_yandex_direct.core import auth as direct_auth
from rb_yandex_direct.core.client import DirectClient
from rb_yandex_direct.core.errors import DirectAPIError
from rb_yandex_direct.core.oauth import OAuthToken, YandexOAuth
from rb_yandex_direct.core.reports import ReportsClient

console = Console()


class _Group(click.Group):
    """Группа: без подкоманды печатает справку (exit 0); CliError → сообщение + action, свой код выхода."""

    group_class = type  # подгруппы `@cli.group()` — тоже _Group

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("invoke_without_command", True)
        super().__init__(*args, **kwargs)

    def invoke(self, ctx: click.Context) -> Any:
        try:
            rv = super().invoke(ctx)
        except CliError as exc:
            click.echo(f"Error: {exc.message}" + (f"\n{exc.action}" if exc.action else ""), err=True)
            ctx.exit(exc.exit_code)
        if ctx.invoked_subcommand is None:
            click.echo(ctx.get_help())
        return rv


def _managed_logins() -> list[str]:
    """Список логинов, к которым есть доступ (представитель/агентство).

    Задаётся через YANDEX_DIRECT_MANAGED_LOGINS=a@yandex.ru,b@yandex.ru.
    API не отдаёт этот список самостоятельно — держим его руками.
    """
    raw = os.getenv("YANDEX_DIRECT_MANAGED_LOGINS", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def _resolve_login(login: str | None) -> str | None:
    """Разрешает неполное имя в полный логин из YANDEX_DIRECT_MANAGED_LOGINS.

    Примеры (при списке ['my-shop@yandex.ru', 'my-blog@yandex.ru']):
      'my-shop@yandex.ru' → 'my-shop@yandex.ru'  (точное совпадение)
      'shop'              → 'my-shop@yandex.ru'  (подстрока, единственный матч)
      'my'                → ClickException       (неоднозначно)
      'xyz'               → ClickException       (нет матчей)
      None                → None
    """
    if not login:
        return None
    managed = _managed_logins()
    if "@" in login or not managed:
        return login
    matches = [m for m in managed if login.lower() in m.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise click.ClickException(f"не найден логин по подстроке {login!r}. YANDEX_DIRECT_MANAGED_LOGINS={managed}")
    raise click.ClickException(f"неоднозначный логин {login!r}, совпало: {matches}. Укажи полностью.")


def _get_client(ctx: click.Context) -> DirectClient:
    token = direct_auth.resolve_token()
    login = _resolve_login(ctx.obj.get("login")) or os.getenv("YANDEX_DIRECT_LOGIN")
    return DirectClient(
        token=token,
        client_login=login,
        sandbox=ctx.obj.get("sandbox") or os.getenv("YANDEX_DIRECT_SANDBOX", "").lower() == "true",
        use_operator_units=os.getenv("YANDEX_DIRECT_USE_OPERATOR_UNITS", "").lower() == "true",
    )


@click.group(cls=_Group)
@click.version_option(package_name=direct_auth.DIST_NAME, message="%(version)s")
@click.option("--login", help="Client-Login (логин рекламодателя для агентского доступа)")
@click.option("--sandbox/--prod", default=None, help="Переключить окружение для этого вызова")
@click.option("-v", "--verbose", is_flag=True, help="Подробные логи")
@click.pass_context
def cli(ctx: click.Context, login: str | None, sandbox: bool | None, verbose: bool) -> None:
    """Яндекс.Директ API v5 — CLI."""
    ctx.ensure_object(dict)
    ctx.obj["login"] = login
    ctx.obj["sandbox"] = sandbox
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if verbose else "WARNING")


# ---------- auth ----------


@cli.group()
def auth() -> None:
    """OAuth-токен Директа: вход, статус, обновление, выход.

    Токен хранится в keychain ОС (yandex-oauth:direct) и обновляется сам по refresh_token.
    Без keychain (сервер, CI) — переменные окружения YANDEX_OAUTH_DIRECT_REFRESH_TOKEN,
    YANDEX_OAUTH_DIRECT_CLIENT_ID, YANDEX_OAUTH_DIRECT_CLIENT_SECRET или готовый токен в
    YANDEX_DIRECT_TOKEN. Файлы .env не читаются.
    """


def _token_set(token: OAuthToken) -> TokenSet:
    expires_in = int((token.expires_at - datetime.now(UTC)).total_seconds()) if token.expires_at else None
    return TokenSet(token.access_token, token.refresh_token, expires_in)


def _print_token(bag: dict) -> None:
    expires = direct_auth.store.expires_at(bag)
    if expires:
        console.print(f"  действует до: {expires.date().isoformat()}")
    refreshable = direct_auth.store.can_refresh(bag)
    console.print(f"  автообновление: {'да' if refreshable else 'нет (токен вставлен вручную)'}")


@auth.command("login")
@click.option("--token", help="готовый OAuth-токен или адрес …verification_code#access_token=… (без автообновления)")
@click.option("--oob", is_flag=True, help="ввести код со страницы подтверждения вручную (ssh, без браузера)")
@click.option("--device", is_flag=True, help="device flow: код подтверждается на другом устройстве")
@click.option("--client-id", help="ID OAuth-приложения (или YANDEX_OAUTH_DIRECT_CLIENT_ID)")
@click.option("--client-secret", help="секрет OAuth-приложения (или YANDEX_OAUTH_DIRECT_CLIENT_SECRET)")
def auth_login(token: str | None, oob: bool, device: bool, client_id: str | None, client_secret: str | None) -> None:
    """Получить OAuth-токен Директа и сохранить в keychain вместе с refresh_token.

    По умолчанию открывает браузер и ловит код на localhost; --oob — код вручную,
    --device — подтверждение на другом устройстве, --token — готовый токен.
    Приложение: --client-id/--client-secret, иначе YANDEX_OAUTH_DIRECT_CLIENT_ID/SECRET
    (прежние YANDEX_DIRECT_CLIENT_ID/SECRET тоже читаются), иначе — с прошлого входа.
    Создать приложение: https://oauth.yandex.ru/?dialog=create-client-entry, права
    direct:api и passport:business; для prod нужна подтверждённая заявка на доступ к API
    (direct.yandex.ru → Настройки API → Мои заявки), иначе API отвечает кодом 58.

    Example: rb-yandex-direct auth login --client-id abc123 --client-secret s3cr3t
    """
    cid, secret = direct_auth.app_credentials(client_id, client_secret)
    if token:
        bag = direct_auth.store.store_token_set(parse_manual_token(token), cid, secret)
    else:
        if not cid or not secret:
            raise click.UsageError(
                "Не задан client_id/client_secret: передай --client-id/--client-secret или задай "
                "YANDEX_OAUTH_DIRECT_CLIENT_ID/YANDEX_OAUTH_DIRECT_CLIENT_SECRET. "
                "Приложение: https://oauth.yandex.ru/?dialog=create-client-entry (direct:api + passport:business)."
            )
        oauth = YandexOAuth(cid, secret)
        if device:
            got = asyncio.run(_auth_device(oauth))
        elif oob:
            got = asyncio.run(_auth_oob(oauth))
        else:
            got = asyncio.run(_auth_interactive(oauth))
        bag = direct_auth.store.store_token_set(_token_set(got), cid, secret)
    console.print("[green]✓[/] Токен сохранён в keychain (yandex-oauth:direct)")
    _print_token(bag)


async def _auth_interactive(oauth: YandexOAuth) -> OAuthToken:
    console.print("[cyan]Открываю браузер для авторизации в Яндексе...[/]")
    return await oauth.authorize_interactive(print_url=lambda u: console.print(f"[dim]{u}[/]"))


async def _auth_oob(oauth: YandexOAuth) -> OAuthToken:
    url = oauth.build_oob_url()
    console.print("\n[cyan]1.[/] Открой в браузере:")
    console.print(f"   [blue underline]{url}[/]\n")
    console.print("[cyan]2.[/] Авторизуйся, скопируй код со страницы подтверждения.")
    code = click.prompt("   Вставь код", type=str).strip()
    return await oauth.authorize_oob(code)


async def _auth_device(oauth: YandexOAuth) -> OAuthToken:
    info = await oauth.device_code_start()
    console.print(f"\n[cyan]1.[/] Открой: [blue underline]{info.get('verification_url')}[/]")
    console.print(f"[cyan]2.[/] Введи код: [bold]{info.get('user_code')}[/]\n")
    console.print("[dim]Жду подтверждения...[/]")
    return await oauth.device_code_poll(info["device_code"], interval=info.get("interval", 5))


@auth.command("refresh")
def auth_refresh() -> None:
    """Принудительно обновить токен по refresh_token (без браузера).

    Обычно не нужно: токен обновляется сам за 30 дней до истечения.
    Без keychain обновлённый токен живёт только в памяти процесса.

    Example: rb-yandex-direct auth refresh
    """
    bag = direct_auth.store.refresh()
    console.print("[green]✓[/] Токен обновлён")
    _print_token(bag)


@auth.command("logout")
def auth_logout() -> None:
    """Удалить токен и данные приложения из keychain (переменные окружения не трогает).

    Example: rb-yandex-direct auth logout
    """
    direct_auth.store.delete()
    console.print("Учётные данные Директа удалены из keychain.")


@auth.command("status")
@click.option("--check", "check", is_flag=True, help="проверить токен запросом clients.get (не дольше 10 с)")
@click.option("--json", "as_json", is_flag=True, help="отчёт JSON по контракту §8 стандарта tools")
@click.pass_context
def auth_status(ctx: click.Context, check: bool, as_json: bool) -> None:
    """Откуда берётся токен и работает ли он. Значений секретов не печатает.

    Без --check — только наличие и срок (unchecked / missing / expired), без сети.
    Код выхода 0 — всё в порядке, 3 — токена нет, он истёк или Директ его не принимает.
    --json: {ok, tool, version, checked_at, credentials[]} — provider, required, fields,
    source, source_ref, status, expires_at, quota (баллы API: остаток и суточный лимит),
    message; при коде 3 — ok: false и error CREDENTIALS_UNHEALTHY рядом с отчётом.

    Example: rb-yandex-direct auth status --check --json
    """
    report, error = direct_auth.status_report(check=check, sandbox=bool(ctx.obj.get("sandbox")))
    if as_json:
        envelope = {"ok": error is None, **({"error": error.to_dict()} if error else {}), **report}
        click.echo(json.dumps(envelope, ensure_ascii=False))
    else:
        for entry in report["credentials"]:
            mark = {"ok": "✓", "unchecked": "·"}.get(entry["status"], "✗")
            expires = f", до {entry['expires_at'][:10]}" if entry["expires_at"] else ""
            quota = entry["quota"]
            units = f", баллы {quota['remaining']}/{quota['limit']}" if quota else ""
            detail = f" — {entry['message']}" if entry["message"] else ""
            line = f"{entry['provider']}: {entry['status']} ({entry['source']}: {entry['source_ref']}){expires}{units}"
            console.print(f"{mark} {escape(line + detail)}")
        if error:
            click.echo(f"Error: {error.message}\n{error.action}", err=True)
    if error:
        ctx.exit(error.exit_code)


# ---------- whoami ----------


@cli.command()
@click.pass_context
def whoami(ctx: click.Context) -> None:
    """Проверить токен и показать клиентов (clients.get). Отказ по учётным данным — exit 3.

    Example: rb-yandex-direct whoami
    """
    client = _get_client(ctx)

    async def run() -> list[dict]:
        return await client.list_clients()

    try:
        clients = asyncio.run(run())
    except DirectAPIError as e:
        raise direct_auth.as_cli_error(e) from e

    t = Table(title="Клиенты")
    t.add_column("Login")
    t.add_column("Валюта")
    t.add_column("Качество")
    for c in clients[:20]:
        t.add_row(
            str(c.get("Login", "")),
            str(c.get("Currency", "")),
            str(c.get("AccountQuality", "")),
        )
    console.print(t)
    console.print(f"[dim]Units: {client.last_units}  RequestId: {client.last_request_id}[/]")


# ---------- clients ----------


@cli.group("client")
def client_cli() -> None:
    """Настройки одного клиента (clients.update / agencyclients.update)."""


@client_cli.command("update")
@click.option(
    "--from-json", type=click.Path(exists=True), required=True, help="JSON-файл c параметрами clients.update (см. доку)"
)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def client_update(ctx, from_json, yes) -> None:
    """Обновить настройки клиента (clients.update).

    Example: rb-yandex-direct client update --from-json client.json
    """
    fields = json.loads(Path(from_json).read_text())
    _confirm(f"clients.update с {len(fields)} полями верхнего уровня", yes)
    data = asyncio.run(_get_client(ctx).update_client(fields))
    console.print_json(data=data)


@client_cli.command("update-agency")
@click.option(
    "--from-json", type=click.Path(exists=True), required=True, help="JSON-файл с параметрами agencyclients.update"
)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def client_update_agency(ctx, from_json, yes) -> None:
    """Обновить агентские настройки (agencyclients.update).

    Example: rb-yandex-direct client update-agency --from-json client.json
    """
    fields = json.loads(Path(from_json).read_text())
    _confirm(f"agencyclients.update с {len(fields)} полями", yes)
    data = asyncio.run(_get_client(ctx).update_agency_client(fields))
    console.print_json(data=data)


@cli.command()
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.option(
    "--managed-only", is_flag=True, help="только логины из YANDEX_DIRECT_MANAGED_LOGINS (не зовёт API под агентским)"
)
@click.pass_context
def accounts(ctx: click.Context, output: str | None, managed_only: bool) -> None:
    """Кабинеты, к которым есть доступ (представитель/агентство).

    Сначала пробует получить список через API (если ты агентство — оно вернёт
    список подопечных). Если не агентство — API вернёт только твой логин,
    поэтому дополняется списком из YANDEX_DIRECT_MANAGED_LOGINS и для каждого
    делается clients.get чтобы показать валюту/баллы/статус. Токен — из auth login
    (keychain) или переменных окружения, как у остальных команд.

    Example: rb-yandex-direct accounts --output accounts.json
    """
    token = direct_auth.resolve_token()

    sandbox = ctx.obj.get("sandbox") or os.getenv("YANDEX_DIRECT_SANDBOX", "").lower() == "true"
    use_op = os.getenv("YANDEX_DIRECT_USE_OPERATOR_UNITS", "").lower() == "true"
    managed = _managed_logins()

    async def gather() -> list[dict]:
        seen: dict[str, dict] = {}

        # 1. Под агентским токеном — список клиентов агентства.
        if not managed_only:
            try:
                agency_client = DirectClient(token=token, sandbox=sandbox, use_operator_units=use_op)
                for c in await agency_client.list_clients():
                    seen[c.get("Login")] = c
            except DirectAPIError:
                # Обычное поведение для представителя — игнорируем.
                pass

        # 2. Дополняем логинами из env, делая clients.get под каждым Client-Login.
        for login in managed:
            if login in seen:
                continue
            c = DirectClient(token=token, client_login=login, sandbox=sandbox, use_operator_units=use_op)
            try:
                items = await c.list_clients()
                seen[login] = items[0] if items else {"Login": login, "_error": "empty"}
            except DirectAPIError as e:
                seen[login] = {"Login": login, "_error": f"[{e.error_code}] {e.error_string}"}

        return list(seen.values())

    data = asyncio.run(gather())

    if output:
        Path(output).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        console.print(f"[green]✓[/] {len(data)} кабинетов → {output}")
        return

    t = Table(title=f"Доступные кабинеты ({len(data)})")
    t.add_column("Login")
    t.add_column("Имя")
    t.add_column("Валюта")
    t.add_column("Качество")
    t.add_column("Ошибка")
    for c in data:
        info = c.get("ClientInfo") or ""
        t.add_row(
            str(c.get("Login", "")),
            str(info)[:40],
            str(c.get("Currency", "") or ""),
            str(c.get("AccountQuality", "") or ""),
            str(c.get("_error", "") or ""),
        )
    console.print(t)
    if not managed and not data:
        console.print(
            "[yellow]Пусто. Задай YANDEX_DIRECT_MANAGED_LOGINS=a@yandex.ru,b@yandex.ru в окружении (Doppler, shell).[/]"
        )


@cli.command()
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def clients(ctx: click.Context, output: str | None) -> None:
    """Список клиентов агентства (или себя для обычного аккаунта).

    Example: rb-yandex-direct clients
    """
    client = _get_client(ctx)
    data = asyncio.run(client.list_clients())
    if output:
        Path(output).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        console.print(f"[green]✓[/] {len(data)} клиентов → {output}")
        return
    t = Table(title=f"Клиенты ({len(data)})")
    t.add_column("Login")
    t.add_column("Currency")
    t.add_column("Quality")
    for c in data:
        t.add_row(str(c.get("Login", "")), str(c.get("Currency", "")), str(c.get("AccountQuality", "")))
    console.print(t)


# ---------- campaigns ----------


@cli.group()
def campaigns() -> None:
    """Управление кампаниями."""


def _confirm(prompt: str, yes: bool) -> None:
    """Унифицированный предохранитель для write-команд."""
    if yes:
        return
    if not click.confirm(f"{prompt} Продолжить?", default=False):
        raise click.Abort()


def _print_result(title: str, data: dict) -> None:
    errors = []
    warnings = []
    for key in (f"{title}Results", "Results"):
        for item in data.get(key, []):
            errors.extend(item.get("Errors") or [])
            warnings.extend(item.get("Warnings") or [])
    ok = sum(1 for item in next((data.get(k) for k in data if k.endswith("Results")), []) if not item.get("Errors"))
    console.print(f"[green]✓[/] {title}: успешно {ok}, ошибок {len(errors)}, предупреждений {len(warnings)}")
    for e in errors[:5]:
        console.print(f"  [red]⨯[/] [{e.get('Code')}] {e.get('Message')}")
    for w in warnings[:3]:
        console.print(f"  [yellow]![/] [{w.get('Code')}] {w.get('Message')}")


@campaigns.command("list")
@click.option(
    "--state",
    type=click.Choice(["ON", "OFF", "SUSPENDED", "ENDED", "CONVERTED", "ARCHIVED"]),
    help="фильтр по состоянию",
)
@click.option("--type", "type_", help="TEXT_CAMPAIGN, MCBANNER_CAMPAIGN, CPM_BANNER_CAMPAIGN, SMART_CAMPAIGN, и т.д.")
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def campaigns_list(ctx: click.Context, state: str | None, type_: str | None, output: str | None) -> None:
    """Список кампаний с фильтром по состоянию и типу.

    Example: rb-yandex-direct campaigns list --state ON
    """
    client = _get_client(ctx)
    criteria: dict[str, Any] = {}
    if state:
        criteria["States"] = [state]
    if type_:
        criteria["Types"] = [type_]
    data = asyncio.run(client.list_campaigns(selection_criteria=criteria))

    if output:
        Path(output).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        console.print(f"[green]✓[/] {len(data)} кампаний → {output}")
        return

    t = Table(title=f"Кампании ({len(data)})")
    t.add_column("Id")
    t.add_column("Name")
    t.add_column("State")
    t.add_column("Status")
    t.add_column("Type")
    for c in data[:100]:
        t.add_row(
            str(c.get("Id", "")),
            str(c.get("Name", ""))[:50],
            str(c.get("State", "")),
            str(c.get("Status", "")),
            str(c.get("Type", "")),
        )
    console.print(t)
    console.print(f"[dim]Units: {client.last_units}[/]")


@campaigns.command("suspend")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def campaigns_suspend(ctx, ids, yes) -> None:
    """Приостановить кампании.

    Example: rb-yandex-direct campaigns suspend 12345 67890
    """
    _confirm(f"Приостановить {len(ids)} кампаний: {list(ids)}", yes)
    data = asyncio.run(_get_client(ctx).suspend_campaigns(list(ids)))
    _print_result("Suspend", data)


@campaigns.command("resume")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def campaigns_resume(ctx, ids, yes) -> None:
    """Возобновить приостановленные кампании.

    Example: rb-yandex-direct campaigns resume 12345
    """
    _confirm(f"Возобновить {len(ids)} кампаний: {list(ids)}", yes)
    data = asyncio.run(_get_client(ctx).resume_campaigns(list(ids)))
    _print_result("Resume", data)


@campaigns.command("archive")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def campaigns_archive(ctx, ids, yes) -> None:
    """Архивировать. Кампания должна быть suspended и без остатка средств.

    Example: rb-yandex-direct campaigns archive 12345
    """
    _confirm(f"Архивировать {len(ids)} кампаний", yes)
    data = asyncio.run(_get_client(ctx).archive_campaigns(list(ids)))
    _print_result("Archive", data)


@campaigns.command("unarchive")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def campaigns_unarchive(ctx, ids, yes) -> None:
    """Вернуть кампании из архива.

    Example: rb-yandex-direct campaigns unarchive 12345
    """
    _confirm(f"Разархивировать {len(ids)} кампаний", yes)
    data = asyncio.run(_get_client(ctx).unarchive_campaigns(list(ids)))
    _print_result("Unarchive", data)


@campaigns.command("set-negative-keywords")
@click.argument("campaign_id", type=int)
@click.option(
    "--type",
    "campaign_type",
    default="TextCampaign",
    type=click.Choice(
        [
            "TextCampaign",
            "DynamicTextCampaign",
            "UnifiedCampaign",
            "SmartCampaign",
            "MobileAppCampaign",
            "McBannerCampaign",
            "CpmBannerCampaign",
            "CpmVideoCampaign",
            "CpmPriceCampaign",
            "ContentPromotionCampaign",
        ]
    ),
    help="тип кампании",
)
@click.option("--words", help="минус-фразы через запятую")
@click.option("--from-file", type=click.Path(exists=True), help="файл с фразами построчно")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def campaigns_set_neg(ctx, campaign_id, campaign_type, words, from_file, yes) -> None:
    """Заменить минус-слова на уровне кампании (полный список заменяет текущий).

    Example: rb-yandex-direct campaigns set-negative-keywords 12345 --words 'бесплатно,скачать'
    """
    kws: list[str] = []
    if from_file:
        kws = [w.strip() for w in Path(from_file).read_text().splitlines() if w.strip()]
    elif words:
        kws = [w.strip() for w in words.split(",") if w.strip()]
    if not kws:
        raise click.ClickException("укажи --words или --from-file")
    _confirm(
        f"Заменить минус-слова кампании {campaign_id} ({campaign_type}) → {len(kws)} фраз",
        yes,
    )
    data = asyncio.run(
        _get_client(ctx).set_campaign_negative_keywords(
            campaign_id,
            kws,
            campaign_type=campaign_type,
        )
    )
    _print_result("Update", data)


@campaigns.command("set-budget")
@click.argument("campaign_id", type=int)
@click.argument("amount_rub", type=float)
@click.option(
    "--mode",
    type=click.Choice(["STANDARD", "DISTRIBUTED"]),
    default="STANDARD",
    help="STANDARD — равномерно, DISTRIBUTED — ускоренно",
)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def campaigns_set_budget(ctx, campaign_id, amount_rub, mode, yes) -> None:
    """Задать дневной бюджет кампании в рублях.

    Example: rb-yandex-direct campaigns set-budget 12345 1500
    """
    _confirm(f"Поставить дневной бюджет {amount_rub}₽ (mode={mode}) на campaign={campaign_id}", yes)
    data = asyncio.run(_get_client(ctx).set_campaign_daily_budget(campaign_id, amount_rub, mode=mode))
    _print_result("Update", data)


@campaigns.command("update")
@click.argument("campaign_id", type=int)
@click.option("--name", help="новое имя кампании")
@click.option("--start-date", help="YYYY-MM-DD")
@click.option("--end-date", help="YYYY-MM-DD (пустая строка чтобы снять)")
@click.option("--daily-budget", type=float, help="дневной бюджет в рублях")
@click.option(
    "--budget-mode", type=click.Choice(["STANDARD", "DISTRIBUTED"]), default="STANDARD", help="режим дневного бюджета"
)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def campaigns_update(ctx, campaign_id, name, start_date, end_date, daily_budget, budget_mode, yes) -> None:
    """Обновить параметры кампании (имя, даты, бюджет).

    Example: rb-yandex-direct campaigns update 12345 --name 'Весна 2026' --daily-budget 2000
    """
    item: dict[str, Any] = {"Id": campaign_id}
    if name:
        item["Name"] = name
    if start_date:
        item["StartDate"] = start_date
    if end_date is not None:
        item["EndDate"] = end_date
    if daily_budget is not None:
        item["DailyBudget"] = {"Amount": int(daily_budget * 1_000_000), "Mode": budget_mode}
    if len(item) == 1:
        raise click.ClickException("нечего обновлять: укажи --name / --start-date / --end-date / --daily-budget")
    _confirm(f"Обновить campaign={campaign_id}: {item}", yes)
    data = asyncio.run(_get_client(ctx).update_campaigns([item]))
    _print_result("Update", data)


# ---------- adgroups ----------


@cli.group()
def adgroups() -> None:
    """Группы объявлений."""


@adgroups.command("list")
@click.option("--campaign", "campaign_ids", type=int, multiple=True, help="фильтр по кампании (можно несколько раз)")
@click.option("--type", "types", multiple=True, help="TEXT_AD_GROUP, DYNAMIC_TEXT_AD_GROUP, ...")
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def adgroups_list(ctx, campaign_ids, types, output) -> None:
    """Список групп объявлений (фильтр по кампаниям и типам).

    Example: rb-yandex-direct adgroups list --campaign 12345
    """
    client = _get_client(ctx)
    data = asyncio.run(
        client.list_adgroups(
            campaign_ids=list(campaign_ids) or None,
            types=list(types) or None,
        )
    )
    _render_or_save(data, output, title=f"Группы ({len(data)})", columns=["Id", "Name", "CampaignId", "Type", "Status"])


@adgroups.command("add")
@click.option("--campaign", "campaign_id", type=int, required=True, help="ID кампании")
@click.option("--name", required=True, help="имя группы")
@click.option(
    "--region", "region_ids", type=int, multiple=True, required=True, help="ID регионов для таргетинга (0 = вся Россия)"
)
@click.option(
    "--negative-keyword", "negative_keywords", multiple=True, help="минус-фразы на уровне группы (повторяй флаг)"
)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def adgroups_add(ctx, campaign_id, name, region_ids, negative_keywords, yes) -> None:
    """Создать текстовую группу объявлений.

    Example: rb-yandex-direct adgroups add --campaign 12345 --name 'Диваны' --region 213
    """
    item: dict[str, Any] = {
        "Name": name,
        "CampaignId": campaign_id,
        "RegionIds": list(region_ids),
    }
    if negative_keywords:
        item["NegativeKeywords"] = {"Items": list(negative_keywords)}
    _confirm(f"Создать группу «{name}» в кампании {campaign_id}", yes)
    data = asyncio.run(_get_client(ctx).add_adgroups([item]))
    _print_result("Add", data)


@adgroups.command("update")
@click.argument("adgroup_id", type=int)
@click.option("--name", help="новое имя группы")
@click.option(
    "--region", "region_ids", type=int, multiple=True, help="ID региона (можно несколько раз; заменяет весь список)"
)
@click.option(
    "--negative-keyword",
    "negative_keywords",
    multiple=True,
    help="минус-фраза группы (можно несколько раз; заменяет весь список)",
)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def adgroups_update(ctx, adgroup_id, name, region_ids, negative_keywords, yes) -> None:
    """Обновить группу объявлений (имя, регионы, минус-фразы группы).

    Example: rb-yandex-direct adgroups update 555 --name 'Диваны Москва'
    """
    item: dict[str, Any] = {"Id": adgroup_id}
    if name:
        item["Name"] = name
    if region_ids:
        item["RegionIds"] = list(region_ids)
    if negative_keywords:
        item["NegativeKeywords"] = {"Items": list(negative_keywords)}
    if len(item) == 1:
        raise click.ClickException("нечего обновлять: укажи --name / --region / --negative-keyword")
    _confirm(f"Обновить группу {adgroup_id}: {item}", yes)
    data = asyncio.run(_get_client(ctx).update_adgroups([item]))
    _print_result("Update", data)


@adgroups.command("delete")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def adgroups_delete(ctx, ids, yes) -> None:
    """Удалить группы объявлений безвозвратно.

    Example: rb-yandex-direct adgroups delete 555
    """
    _confirm(f"[red]УДАЛИТЬ[/] {len(ids)} групп объявлений (необратимо)", yes)
    data = asyncio.run(_get_client(ctx).delete_adgroups(list(ids)))
    _print_result("Delete", data)


@adgroups.command("set-negative-keywords")
@click.argument("adgroup_id", type=int)
@click.option("--words", help="минус-фразы через запятую")
@click.option("--from-file", type=click.Path(exists=True), help="файл с фразами построчно")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def adgroups_set_neg(ctx, adgroup_id, words, from_file, yes) -> None:
    """Заменить минус-слова на уровне группы (полный список заменяет текущий).

    Example: rb-yandex-direct adgroups set-negative-keywords 555 --words 'бу,ремонт'
    """
    kws: list[str] = []
    if from_file:
        kws = [w.strip() for w in Path(from_file).read_text().splitlines() if w.strip()]
    elif words:
        kws = [w.strip() for w in words.split(",") if w.strip()]
    if not kws:
        raise click.ClickException("укажи --words или --from-file")
    _confirm(f"Заменить минус-слова группы {adgroup_id} → {len(kws)} фраз", yes)
    data = asyncio.run(_get_client(ctx).set_adgroup_negative_keywords(adgroup_id, kws))
    _print_result("Update", data)


# ---------- ads ----------


@cli.group()
def ads() -> None:
    """Объявления."""


@ads.command("list")
@click.option("--campaign", "campaign_ids", type=int, multiple=True, help="фильтр по кампании (можно несколько раз)")
@click.option(
    "--adgroup", "adgroup_ids", type=int, multiple=True, help="фильтр по группе объявлений (можно несколько раз)"
)
@click.option(
    "--state",
    "states",
    multiple=True,
    type=click.Choice(["ON", "OFF", "SUSPENDED", "OFF_BY_MONITORING", "ARCHIVED"]),
    help="фильтр по состоянию (можно несколько раз)",
)
@click.option(
    "--status",
    "statuses",
    multiple=True,
    type=click.Choice(["ACCEPTED", "DRAFT", "MODERATION", "PREACCEPTED", "REJECTED", "UNKNOWN"]),
    help="фильтр по статусу модерации (можно несколько раз)",
)
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def ads_list(ctx, campaign_ids, adgroup_ids, states, statuses, output) -> None:
    """Список объявлений (фильтр по кампаниям, группам, состоянию, статусу).

    Example: rb-yandex-direct ads list --campaign 12345 --status REJECTED
    """
    client = _get_client(ctx)
    data = asyncio.run(
        client.list_ads(
            campaign_ids=list(campaign_ids) or None,
            adgroup_ids=list(adgroup_ids) or None,
            states=list(states) or None,
            statuses=list(statuses) or None,
        )
    )
    _render_or_save(
        data,
        output,
        title=f"Объявления ({len(data)})",
        columns=["Id", "AdGroupId", "CampaignId", "Type", "State", "Status"],
    )


@ads.command("moderate")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def ads_moderate(ctx, ids, yes) -> None:
    """Отправить объявления на модерацию (из DRAFT в MODERATION).

    Example: rb-yandex-direct ads moderate 777 778
    """
    _confirm(f"Отправить {len(ids)} объявлений на модерацию", yes)
    data = asyncio.run(_get_client(ctx).moderate_ads(list(ids)))
    _print_result("Moderate", data)


@ads.command("suspend")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def ads_suspend(ctx, ids, yes) -> None:
    """Остановить показы объявлений.

    Example: rb-yandex-direct ads suspend 777
    """
    _confirm(f"Остановить {len(ids)} объявлений", yes)
    data = asyncio.run(_get_client(ctx).suspend_ads(list(ids)))
    _print_result("Suspend", data)


@ads.command("resume")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def ads_resume(ctx, ids, yes) -> None:
    """Возобновить показы остановленных объявлений.

    Example: rb-yandex-direct ads resume 777
    """
    _confirm(f"Включить {len(ids)} объявлений", yes)
    data = asyncio.run(_get_client(ctx).resume_ads(list(ids)))
    _print_result("Resume", data)


@ads.command("archive")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def ads_archive(ctx, ids, yes) -> None:
    """Архивировать объявления.

    Example: rb-yandex-direct ads archive 777
    """
    _confirm(f"Архивировать {len(ids)} объявлений", yes)
    data = asyncio.run(_get_client(ctx).archive_ads(list(ids)))
    _print_result("Archive", data)


@ads.command("unarchive")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def ads_unarchive(ctx, ids, yes) -> None:
    """Вернуть объявления из архива.

    Example: rb-yandex-direct ads unarchive 777
    """
    _confirm(f"Разархивировать {len(ids)} объявлений", yes)
    data = asyncio.run(_get_client(ctx).unarchive_ads(list(ids)))
    _print_result("Unarchive", data)


@ads.command("delete")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def ads_delete(ctx, ids, yes) -> None:
    """Удалить объявления безвозвратно (только черновики и отклонённые).

    Example: rb-yandex-direct ads delete 777
    """
    _confirm(f"[red]УДАЛИТЬ[/] {len(ids)} объявлений (необратимо)", yes)
    data = asyncio.run(_get_client(ctx).delete_ads(list(ids)))
    _print_result("Delete", data)


@ads.command("add-text")
@click.option("--adgroup", "adgroup_id", type=int, required=True, help="ID группы объявлений")
@click.option("--title", required=True, help="первый заголовок (до 56 симв.)")
@click.option("--text", required=True, help="основной текст (до 81 симв.)")
@click.option("--href", required=True, help="URL посадочной страницы")
@click.option("--title2", help="второй заголовок")
@click.option("--display-url-path", help="отображаемый путь URL")
@click.option("--image-hash", help="хэш картинки (привязать ad-image)")
@click.option("--sitelink-set", "sitelink_set_id", type=int, help="ID набора быстрых ссылок")
@click.option("--vcard", "vcard_id", type=int, help="ID визитки")
@click.option("--turbo", "turbo_page_id", type=int, help="ID турбо-страницы")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def ads_add_text(
    ctx,
    adgroup_id,
    title,
    text,
    href,
    title2,
    display_url_path,
    image_hash,
    sitelink_set_id,
    vcard_id,
    turbo_page_id,
    yes,
) -> None:
    """Создать одно текстовое объявление (TextAd).

    Example: rb-yandex-direct ads add-text --adgroup 555 --title 'Диваны от 9990 ₽' --text 'Доставка за день' --href https://example.com
    """
    _confirm(f"Создать текстовое объявление в группе {adgroup_id}", yes)
    data = asyncio.run(
        _get_client(ctx).add_text_ad(
            adgroup_id=adgroup_id,
            title=title,
            text=text,
            href=href,
            title2=title2,
            display_url_path=display_url_path,
            ad_image_hash=image_hash,
            sitelink_set_id=sitelink_set_id,
            vcard_id=vcard_id,
            turbo_page_id=turbo_page_id,
        )
    )
    _print_result("Add", data)


@ads.command("add-json")
@click.option(
    "--from-json",
    type=click.Path(exists=True),
    required=True,
    help="JSON-массив объектов объявлений (для MobileAppAd, DynamicTextAd и прочих)",
)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def ads_add_json(ctx, from_json, yes) -> None:
    """Создать объявления из JSON-файла (любые типы: TextAd, MobileAppAd, ...).

    Example: rb-yandex-direct ads add-json --from-json ads.json
    """
    items = json.loads(Path(from_json).read_text())
    if not isinstance(items, list) or not items:
        raise click.ClickException("JSON должен быть непустым массивом")
    _confirm(f"Создать {len(items)} объявлений", yes)
    data = asyncio.run(_get_client(ctx).add_ads(items))
    _print_result("Add", data)


@ads.command("moderation")
@click.option("--campaign", "campaign_ids", type=int, multiple=True, help="фильтр по кампании (можно несколько раз)")
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def ads_moderation(ctx, campaign_ids, output) -> None:
    """Объявления, ждущие модерации или отклонённые.

    Example: rb-yandex-direct ads moderation --campaign 12345
    """
    client = _get_client(ctx)
    data = asyncio.run(client.list_ads_in_moderation(campaign_ids=list(campaign_ids) or None))
    _render_or_save(
        data,
        output,
        title=f"Объявления в модерации ({len(data)})",
        columns=["Id", "AdGroupId", "State", "Status", "Type"],
    )


# ---------- keywords ----------


@cli.group()
def keywords() -> None:
    """Ключевые фразы."""


@keywords.command("list")
@click.option(
    "--adgroup", "adgroup_ids", type=int, multiple=True, help="фильтр по группе объявлений (можно несколько раз)"
)
@click.option("--campaign", "campaign_ids", type=int, multiple=True, help="фильтр по кампании (можно несколько раз)")
@click.option(
    "--state",
    "states",
    multiple=True,
    type=click.Choice(["ON", "OFF", "SUSPENDED", "UNKNOWN"]),
    help="фильтр по состоянию (можно несколько раз)",
)
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def keywords_list(ctx, adgroup_ids, campaign_ids, states, output) -> None:
    """Список ключевых фраз (фильтр по группам, кампаниям, состоянию).

    Example: rb-yandex-direct keywords list --adgroup 555
    """
    client = _get_client(ctx)
    data = asyncio.run(
        client.list_keywords(
            adgroup_ids=list(adgroup_ids) or None,
            campaign_ids=list(campaign_ids) or None,
            states=list(states) or None,
        )
    )
    _render_or_save(
        data,
        output,
        title=f"Ключи ({len(data)})",
        columns=["Id", "Keyword", "AdGroupId", "CampaignId", "State", "Status"],
    )


@keywords.command("suspend")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def keywords_suspend(ctx, ids, yes) -> None:
    """Остановить показы по ключевым фразам.

    Example: rb-yandex-direct keywords suspend 901 902
    """
    _confirm(f"Остановить {len(ids)} ключей", yes)
    data = asyncio.run(_get_client(ctx).suspend_keywords(list(ids)))
    _print_result("Suspend", data)


@keywords.command("resume")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def keywords_resume(ctx, ids, yes) -> None:
    """Возобновить показы по ключевым фразам.

    Example: rb-yandex-direct keywords resume 901
    """
    _confirm(f"Включить {len(ids)} ключей", yes)
    data = asyncio.run(_get_client(ctx).resume_keywords(list(ids)))
    _print_result("Resume", data)


@keywords.command("check-volume")
@click.argument("phrases", nargs=-1, required=True)
@click.option("--region", "region_ids", type=int, multiple=True, help="регион Яндекса (213=Москва, 2=СПб)")
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def keywords_check_volume(ctx, phrases, region_ids, output) -> None:
    """Проверить, есть ли у фраз поисковый спрос.

    Example: rb-yandex-direct keywords check-volume 'купить диван' 'диван недорого' --region 213
    """
    client = _get_client(ctx)
    data = asyncio.run(
        client.keywords_has_search_volume(
            list(phrases),
            region_ids=list(region_ids) or None,
        )
    )
    _render_or_save(data, output, title=f"Проверка спроса ({len(data)})", columns=["Phrase", "HasSearchVolume"])


@keywords.command("dedup")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def keywords_dedup(ctx, ids, yes) -> None:
    """Найти дубли среди переданных ключей и приостановить копии.

    Example: rb-yandex-direct keywords dedup 901 902 903
    """
    _confirm(f"Дедуплицировать {len(ids)} ключей (приостановит дубли)", yes)
    data = asyncio.run(_get_client(ctx).keywords_deduplicate(list(ids)))
    console.print_json(data=data)


@keywords.command("delete")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def keywords_delete(ctx, ids, yes) -> None:
    """Удалить ключи безвозвратно.

    Example: rb-yandex-direct keywords delete 901
    """
    _confirm(f"[red]УДАЛИТЬ[/] {len(ids)} ключей (необратимо)", yes)
    data = asyncio.run(_get_client(ctx).delete_keywords(list(ids)))
    _print_result("Delete", data)


@keywords.command("add")
@click.option("--adgroup", "adgroup_id", type=int, required=True, help="группа, куда добавлять")
@click.argument("phrases", nargs=-1)
@click.option(
    "--from-file", type=click.Path(exists=True), help="файл с фразами построчно (альтернатива positional args)"
)
@click.option("--search-bid", type=float, help="ставка поиска в рублях для всех добавляемых фраз")
@click.option("--network-bid", type=float, help="ставка сетей в рублях")
@click.option("--priority", type=click.Choice(["HIGH", "NORMAL", "LOW"]), help="StrategyPriority для авто-стратегии")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def keywords_add(ctx, adgroup_id, phrases, from_file, search_bid, network_bid, priority, yes) -> None:
    """Добавить ключевые фразы в группу (до 1000 за вызов).

    Example: rb-yandex-direct keywords add --adgroup 555 'купить диван' 'диван недорого' --search-bid 15
    """
    texts: list[str] = list(phrases)
    if from_file:
        texts += [w.strip() for w in Path(from_file).read_text().splitlines() if w.strip()]
    if not texts:
        raise click.ClickException("укажи фразы позиционно или через --from-file")
    if len(texts) > 1000:
        raise click.ClickException(f"не более 1000 фраз за вызов, получено {len(texts)}")

    items: list[dict] = []
    for text in texts:
        item: dict[str, Any] = {"AdGroupId": adgroup_id, "Keyword": text}
        if search_bid is not None:
            item["Bid"] = int(search_bid * 1_000_000)
        if network_bid is not None:
            item["ContextBid"] = int(network_bid * 1_000_000)
        if priority:
            item["StrategyPriority"] = priority
        items.append(item)

    _confirm(f"Добавить {len(items)} фраз в группу {adgroup_id}", yes)
    data = asyncio.run(_get_client(ctx).add_keywords(items))
    _print_result("Add", data)


@keywords.command("update")
@click.option("--id", "keyword_id", type=int, required=True, help="ID ключевой фразы")
@click.option("--text", help="новый текст фразы")
@click.option("--priority", type=click.Choice(["HIGH", "NORMAL", "LOW"]), help="приоритет для автостратегии")
@click.option("--user-param1", help="значение {param1} для подстановки в ссылку")
@click.option("--user-param2", help="значение {param2} для подстановки в ссылку")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def keywords_update(ctx, keyword_id, text, priority, user_param1, user_param2, yes) -> None:
    """Обновить ключевую фразу.

    Example: rb-yandex-direct keywords update --id 901 --text 'купить угловой диван'
    """
    item: dict[str, Any] = {"Id": keyword_id}
    if text:
        item["Keyword"] = text
    if priority:
        item["StrategyPriority"] = priority
    if user_param1 is not None:
        item["UserParam1"] = user_param1
    if user_param2 is not None:
        item["UserParam2"] = user_param2
    if len(item) == 1:
        raise click.ClickException("нечего обновлять: укажи --text / --priority / --user-param1/2")
    _confirm(f"Обновить keyword={keyword_id}: {item}", yes)
    data = asyncio.run(_get_client(ctx).update_keywords([item]))
    _print_result("Update", data)


# ---------- bids ----------


@cli.group()
def bids() -> None:
    """Ставки по ключевым фразам."""


@bids.command("list")
@click.option(
    "--keyword", "keyword_ids", type=int, multiple=True, help="фильтр по ключевой фразе (можно несколько раз)"
)
@click.option(
    "--adgroup", "adgroup_ids", type=int, multiple=True, help="фильтр по группе объявлений (можно несколько раз)"
)
@click.option("--campaign", "campaign_ids", type=int, multiple=True, help="фильтр по кампании (можно несколько раз)")
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def bids_list(ctx, keyword_ids, adgroup_ids, campaign_ids, output) -> None:
    """Ставки по ключевым фразам (нужен хотя бы один фильтр).

    Example: rb-yandex-direct bids list --campaign 12345
    """
    client = _get_client(ctx)
    if not (keyword_ids or adgroup_ids or campaign_ids):
        raise click.ClickException("укажи хотя бы --keyword, --adgroup или --campaign")
    data = asyncio.run(
        client.get_keyword_bids(
            keyword_ids=list(keyword_ids) or None,
            adgroup_ids=list(adgroup_ids) or None,
            campaign_ids=list(campaign_ids) or None,
        )
    )
    if output:
        Path(output).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        console.print(f"[green]✓[/] {len(data)} ставок → {output}")
        return
    t = Table(title=f"Ставки ({len(data)})")
    for col in ["KeywordId", "AdGroupId", "Search.Bid", "Search.Price", "Network.Bid"]:
        t.add_column(col)
    for b in data[:100]:
        search = b.get("Search") or {}
        network = b.get("Network") or {}
        t.add_row(
            str(b.get("KeywordId", "")),
            str(b.get("AdGroupId", "")),
            str(search.get("Bid", "")),
            str(search.get("Price", "")),
            str(network.get("Bid", "")),
        )
    console.print(t)


@bids.command("set")
@click.option("--keyword", "keyword_id", type=int, required=True, help="ID ключевой фразы")
@click.option("--search-bid", type=float, help="ставка на поиске (в рублях)")
@click.option("--network-bid", type=float, help="ставка в сетях (в рублях)")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def bids_set(ctx, keyword_id, search_bid, network_bid, yes) -> None:
    """Установить ручную ставку по ключу. Ставки задаются в рублях — домножаются на 1e6.

    Example: rb-yandex-direct bids set --keyword 901 --search-bid 12.5
    """
    if search_bid is None and network_bid is None:
        raise click.ClickException("укажи хотя бы одно: --search-bid или --network-bid")
    bid: dict[str, Any] = {"KeywordId": keyword_id}
    if search_bid is not None:
        bid["SearchBid"] = int(search_bid * 1_000_000)
    if network_bid is not None:
        bid["NetworkBid"] = int(network_bid * 1_000_000)
    _confirm(f"Установить ставку keyword={keyword_id}: {bid}", yes)
    data = asyncio.run(_get_client(ctx).set_keyword_bids([bid]))
    _print_result("Set", data)


@bids.command("set-auto")
@click.option("--keyword", "keyword_id", type=int, required=True, help="ID ключевой фразы")
@click.option(
    "--priority", type=click.Choice(["HIGH", "NORMAL", "LOW"]), required=True, help="приоритет для автостратегии"
)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def bids_set_auto(ctx, keyword_id, priority, yes) -> None:
    """Приоритет ключа для авто-стратегии.

    Example: rb-yandex-direct bids set-auto --keyword 901 --priority HIGH
    """
    _confirm(f"StrategyPriority={priority} для keyword={keyword_id}", yes)
    data = asyncio.run(
        _get_client(ctx).set_keyword_bids_auto([{"KeywordId": keyword_id, "StrategyPriority": priority}])
    )
    _print_result("SetAuto", data)


# ---------- bid modifiers ----------


@cli.group("modifiers")
def modifiers() -> None:
    """Корректировки ставок (устройства, регионы, демо, ретаргетинг)."""


@modifiers.command("list")
@click.option("--campaign", "campaign_ids", type=int, multiple=True, help="фильтр по кампании (можно несколько раз)")
@click.option(
    "--adgroup", "adgroup_ids", type=int, multiple=True, help="фильтр по группе объявлений (можно несколько раз)"
)
@click.option(
    "--type",
    "types",
    multiple=True,
    type=click.Choice(
        [
            "MOBILE_ADJUSTMENT",
            "DEMOGRAPHICS_ADJUSTMENT",
            "RETARGETING_ADJUSTMENT",
            "REGIONAL_ADJUSTMENT",
            "VIDEO_ADJUSTMENT",
            "INCOME_GRADE_ADJUSTMENT",
        ]
    ),
    help="фильтр по типу корректировки (можно несколько раз)",
)
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def modifiers_list(ctx, campaign_ids, adgroup_ids, types, output) -> None:
    """Корректировки ставок кампаний и групп.

    Example: rb-yandex-direct modifiers list --campaign 12345
    """
    client = _get_client(ctx)
    data = asyncio.run(
        client.list_bid_modifiers(
            campaign_ids=list(campaign_ids) or None,
            adgroup_ids=list(adgroup_ids) or None,
            types=list(types) or None,
        )
    )
    _render_or_save(
        data, output, title=f"Корректировки ({len(data)})", columns=["Id", "CampaignId", "AdGroupId", "Type", "Level"]
    )


@modifiers.command("add")
@click.option("--campaign", "campaign_id", type=int, help="применить к кампании (исключает --adgroup)")
@click.option("--adgroup", "adgroup_id", type=int, help="применить к группе (исключает --campaign)")
@click.option(
    "--type",
    "mod_type",
    required=True,
    type=click.Choice(["MOBILE", "DESKTOP", "DEMOGRAPHICS", "RETARGETING", "REGIONAL", "VIDEO", "INCOME_GRADE"]),
    help="тип корректировки (шорткат без _ADJUSTMENT)",
)
@click.option(
    "--value",
    "bid_modifier",
    type=int,
    required=True,
    help="процент ставки: 0-1200 (100 = без корректировки, 0 = выключить показы)",
)
@click.option("--gender", type=click.Choice(["GENDER_MALE", "GENDER_FEMALE"]), help="для --type=DEMOGRAPHICS")
@click.option("--age", help="для --type=DEMOGRAPHICS: AGE_0_17, AGE_18_24, AGE_25_34, AGE_35_44, AGE_45_54, AGE_55")
@click.option("--region", "region_id", type=int, help="для --type=REGIONAL")
@click.option("--retargeting", "retargeting_id", type=int, help="для --type=RETARGETING")
@click.option("--grade", help="для --type=INCOME_GRADE: HIGHEST | HIGH | ABOVE_AVERAGE | ...")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def modifiers_add(
    ctx, campaign_id, adgroup_id, mod_type, bid_modifier, gender, age, region_id, retargeting_id, grade, yes
) -> None:
    """Добавить корректировку ставки.

    Примеры:
      rb-yandex-direct modifiers add --campaign 123 --type MOBILE --value 80
      rb-yandex-direct modifiers add --adgroup 456 --type DEMOGRAPHICS --gender GENDER_MALE --age AGE_25_34 --value 120
      rb-yandex-direct modifiers add --campaign 123 --type REGIONAL --region 213 --value 150

    Example: rb-yandex-direct modifiers add --campaign 12345 --type MOBILE --value 50
    """
    if (campaign_id is None) == (adgroup_id is None):
        raise click.ClickException("укажи ровно один из --campaign / --adgroup")
    item: dict[str, Any] = {}
    if campaign_id:
        item["CampaignId"] = campaign_id
    if adgroup_id:
        item["AdGroupId"] = adgroup_id
    block_key = {
        "MOBILE": "MobileAdjustment",
        "DESKTOP": "DesktopAdjustment",
        "DEMOGRAPHICS": "DemographicsAdjustment",
        "RETARGETING": "RetargetingAdjustment",
        "REGIONAL": "RegionalAdjustment",
        "VIDEO": "VideoAdjustment",
        "INCOME_GRADE": "IncomeGradeAdjustment",
    }[mod_type]
    block: dict[str, Any] = {"BidModifier": bid_modifier}
    if mod_type == "DEMOGRAPHICS":
        if not (gender or age):
            raise click.ClickException("для DEMOGRAPHICS нужны --gender и/или --age")
        if gender:
            block["Gender"] = gender
        if age:
            block["Age"] = age
    elif mod_type == "REGIONAL":
        if region_id is None:
            raise click.ClickException("для REGIONAL нужен --region")
        block["RegionId"] = region_id
    elif mod_type == "RETARGETING":
        if retargeting_id is None:
            raise click.ClickException("для RETARGETING нужен --retargeting")
        block["RetargetingConditionId"] = retargeting_id
    elif mod_type == "INCOME_GRADE":
        if not grade:
            raise click.ClickException("для INCOME_GRADE нужен --grade")
        block["Grade"] = grade
    item[block_key] = block

    _confirm(f"Добавить корректировку {mod_type}={bid_modifier}% ({item})", yes)
    data = asyncio.run(_get_client(ctx).add_bid_modifiers([item]))
    _print_result("Add", data)


@modifiers.command("set")
@click.option("--id", "modifier_id", type=int, required=True, help="ID корректировки")
@click.option("--value", "bid_modifier", type=int, required=True, help="0-1200")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def modifiers_set(ctx, modifier_id, bid_modifier, yes) -> None:
    """Изменить значение существующей корректировки.

    Example: rb-yandex-direct modifiers set --id 3001 --value 120
    """
    _confirm(f"Поставить BidModifier={bid_modifier}% на id={modifier_id}", yes)
    data = asyncio.run(_get_client(ctx).set_bid_modifiers([{"Id": modifier_id, "BidModifier": bid_modifier}]))
    _print_result("Set", data)


@modifiers.command("delete")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def modifiers_delete(ctx, ids, yes) -> None:
    """Удалить корректировки ставок.

    Example: rb-yandex-direct modifiers delete 3001
    """
    _confirm(f"Удалить {len(ids)} корректировок", yes)
    data = asyncio.run(_get_client(ctx).delete_bid_modifiers(list(ids)))
    _print_result("Delete", data)


@modifiers.command("toggle")
@click.option("--campaign", "campaign_id", type=int, help="ID кампании")
@click.option("--adgroup", "adgroup_id", type=int, help="ID группы объявлений")
@click.option(
    "--type",
    "mod_type",
    required=True,
    type=click.Choice(
        [
            "DEMOGRAPHICS_ADJUSTMENT",
            "RETARGETING_ADJUSTMENT",
            "REGIONAL_ADJUSTMENT",
            "SERP_LAYOUT_ADJUSTMENT",
            "INCOME_GRADE_ADJUSTMENT",
        ]
    ),
    help="тип корректировки",
)
@click.option("--enabled", type=click.Choice(["YES", "NO"]), required=True, help="YES — включить, NO — выключить")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def modifiers_toggle(ctx, campaign_id, adgroup_id, mod_type, enabled, yes) -> None:
    """Включить/выключить корректировки группы/кампании по типу.

    Example: rb-yandex-direct modifiers toggle --campaign 12345 --type DEMOGRAPHICS_ADJUSTMENT --enabled NO
    """
    if (campaign_id is None) == (adgroup_id is None):
        raise click.ClickException("укажи ровно один из --campaign / --adgroup")
    item: dict[str, Any] = {"Type": mod_type, "Enabled": enabled}
    if campaign_id:
        item["CampaignId"] = campaign_id
    if adgroup_id:
        item["AdGroupId"] = adgroup_id
    _confirm(f"Toggle {mod_type} → Enabled={enabled} на {item}", yes)
    data = asyncio.run(_get_client(ctx).toggle_bid_modifiers([item]))
    _print_result("Toggle", data)


# ---------- retargeting lists ----------


@cli.group("retargeting")
def retargeting() -> None:
    """Списки ретаргетинга (цели/аудитории Метрики)."""


@retargeting.command("list")
@click.option(
    "--type",
    "types",
    multiple=True,
    type=click.Choice(["RETARGETING", "AUDIENCE", "SHARED_AUDIENCE", "YANDEX_PROVIDER"]),
    help="фильтр по типу списка (можно несколько раз)",
)
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def retargeting_list(ctx, types, output) -> None:
    """Списки ретаргетинга и аудиторий.

    Example: rb-yandex-direct retargeting list --type AUDIENCE
    """
    client = _get_client(ctx)
    data = asyncio.run(client.list_retargeting_lists(types=list(types) or None))
    _render_or_save(
        data, output, title=f"Списки ретаргетинга ({len(data)})", columns=["Id", "Name", "Type", "IsAvailable"]
    )


@retargeting.command("add")
@click.option("--name", required=True, help="имя списка (до 250 симв.)")
@click.option("--description", help="описание (до 4096 симв.)")
@click.option(
    "--type", "list_type", type=click.Choice(["RETARGETING", "AUDIENCE"]), default="RETARGETING", help="тип списка"
)
@click.option(
    "--goal",
    "goal_ids",
    type=int,
    multiple=True,
    required=True,
    help="ID целей/сегментов Метрики (повторяй флаг для нескольких)",
)
@click.option("--days", type=int, default=30, help="MembershipLifeSpan — срок проверки цели, 1-540 дней (default 30)")
@click.option(
    "--operator",
    type=click.Choice(["ALL", "ANY", "NONE"]),
    default="ANY",
    help="как сочетать цели: ALL — все, ANY — любая, NONE — ни одной",
)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def retargeting_add(ctx, name, description, list_type, goal_ids, days, operator, yes) -> None:
    """Создать список ретаргетинга из одного набора целей.

    Для сложных правил (несколько блоков Operator) используй Python API.

    Example: rb-yandex-direct retargeting add --name 'Корзина' --goal 123456 --days 30
    """
    args = [{"ExternalId": gid, "MembershipLifeSpan": days} for gid in goal_ids]
    item: dict[str, Any] = {
        "Name": name,
        "Type": list_type,
        "Rules": [{"Operator": operator, "Arguments": args}],
    }
    if description:
        item["Description"] = description
    _confirm(f"Создать список «{name}» ({len(goal_ids)} целей, operator={operator})", yes)
    data = asyncio.run(_get_client(ctx).add_retargeting_lists([item]))
    _print_result("Add", data)


@retargeting.command("update")
@click.argument("list_id", type=int)
@click.option("--name", help="новое имя списка")
@click.option("--description", help="новое описание списка")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def retargeting_update(ctx, list_id, name, description, yes) -> None:
    """Обновить имя/описание списка ретаргетинга.

    Для изменения Rules используй Python API: это многомерная структура.

    Example: rb-yandex-direct retargeting update 4001 --name 'Корзина 30 дней'
    """
    item: dict[str, Any] = {"Id": list_id}
    if name:
        item["Name"] = name
    if description is not None:
        item["Description"] = description
    if len(item) == 1:
        raise click.ClickException("укажи --name или --description")
    _confirm(f"Обновить список {list_id}: {item}", yes)
    data = asyncio.run(_get_client(ctx).update_retargeting_lists([item]))
    _print_result("Update", data)


@retargeting.command("delete")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def retargeting_delete(ctx, ids, yes) -> None:
    """Удалить списки ретаргетинга.

    Example: rb-yandex-direct retargeting delete 4001
    """
    _confirm(f"[red]УДАЛИТЬ[/] {len(ids)} списков ретаргетинга", yes)
    data = asyncio.run(_get_client(ctx).delete_retargeting_lists(list(ids)))
    _print_result("Delete", data)


# ---------- audience targets ----------


@cli.group("audiences")
def audiences() -> None:
    """Привязки аудиторий к группам объявлений."""


@audiences.command("list")
@click.option(
    "--adgroup", "adgroup_ids", type=int, multiple=True, help="фильтр по группе объявлений (можно несколько раз)"
)
@click.option("--campaign", "campaign_ids", type=int, multiple=True, help="фильтр по кампании (можно несколько раз)")
@click.option(
    "--state",
    "states",
    multiple=True,
    type=click.Choice(["ON", "OFF", "SUSPENDED", "UNKNOWN"]),
    help="фильтр по состоянию (можно несколько раз)",
)
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def audiences_list(ctx, adgroup_ids, campaign_ids, states, output) -> None:
    """Привязки аудиторий к группам объявлений.

    Example: rb-yandex-direct audiences list --campaign 12345
    """
    client = _get_client(ctx)
    data = asyncio.run(
        client.list_audience_targets(
            adgroup_ids=list(adgroup_ids) or None,
            campaign_ids=list(campaign_ids) or None,
            states=list(states) or None,
        )
    )
    _render_or_save(
        data,
        output,
        title=f"Аудитории в группах ({len(data)})",
        columns=["Id", "AdGroupId", "RetargetingListId", "InterestId", "State", "ContextBid"],
    )


@audiences.command("add")
@click.option("--adgroup", "adgroup_id", type=int, required=True, help="ID группы объявлений")
@click.option(
    "--retargeting", "retargeting_list_id", type=int, help="ID списка ретаргетинга (или используй --interest)"
)
@click.option("--interest", "interest_id", type=int, help="ID интереса (только для MOBILE_APP_AD_GROUP)")
@click.option("--context-bid", type=float, help="ставка в сетях в рублях (ручная стратегия)")
@click.option("--priority", type=click.Choice(["LOW", "NORMAL", "HIGH"]), help="StrategyPriority для авто-стратегий")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def audiences_add(ctx, adgroup_id, retargeting_list_id, interest_id, context_bid, priority, yes) -> None:
    """Привязать аудиторию к группе объявлений.

    Example: rb-yandex-direct audiences add --adgroup 555 --retargeting 4001
    """
    if (retargeting_list_id is None) == (interest_id is None):
        raise click.ClickException("укажи ровно один из --retargeting / --interest")
    item: dict[str, Any] = {"AdGroupId": adgroup_id}
    if retargeting_list_id:
        item["RetargetingListId"] = retargeting_list_id
    if interest_id:
        item["InterestId"] = interest_id
    if context_bid is not None:
        item["ContextBid"] = int(context_bid * 1_000_000)
    if priority:
        item["StrategyPriority"] = priority
    _confirm(f"Привязать аудиторию к группе {adgroup_id}: {item}", yes)
    data = asyncio.run(_get_client(ctx).add_audience_targets([item]))
    _print_result("Add", data)


@audiences.command("suspend")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def audiences_suspend(ctx, ids, yes) -> None:
    """Остановить привязки аудиторий.

    Example: rb-yandex-direct audiences suspend 5001
    """
    _confirm(f"Остановить {len(ids)} привязок аудиторий", yes)
    data = asyncio.run(_get_client(ctx).suspend_audience_targets(list(ids)))
    _print_result("Suspend", data)


@audiences.command("resume")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def audiences_resume(ctx, ids, yes) -> None:
    """Возобновить привязки аудиторий.

    Example: rb-yandex-direct audiences resume 5001
    """
    _confirm(f"Включить {len(ids)} привязок аудиторий", yes)
    data = asyncio.run(_get_client(ctx).resume_audience_targets(list(ids)))
    _print_result("Resume", data)


@audiences.command("delete")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def audiences_delete(ctx, ids, yes) -> None:
    """Удалить привязки аудиторий.

    Example: rb-yandex-direct audiences delete 5001
    """
    _confirm(f"[red]УДАЛИТЬ[/] {len(ids)} привязок аудиторий", yes)
    data = asyncio.run(_get_client(ctx).delete_audience_targets(list(ids)))
    _print_result("Delete", data)


@audiences.command("set-bid")
@click.option("--id", "target_id", type=int, help="ID конкретной привязки (или --adgroup/--campaign)")
@click.option("--adgroup", "adgroup_id", type=int, help="ID группы — ставка для всех её привязок")
@click.option("--campaign", "campaign_id", type=int, help="ID кампании — ставка для всех привязок в кампании")
@click.option("--context-bid", type=float, help="ставка в сетях, рубли (ручная стратегия)")
@click.option("--priority", type=click.Choice(["LOW", "NORMAL", "HIGH"]), help="приоритет для авто-стратегий")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def audiences_set_bid(ctx, target_id, adgroup_id, campaign_id, context_bid, priority, yes) -> None:
    """Установить ставку/приоритет на привязках аудиторий.

    Ровно один из --id / --adgroup / --campaign.

    Example: rb-yandex-direct audiences set-bid --id 5001 --context-bid 8
    """
    scope = [x for x in (target_id, adgroup_id, campaign_id) if x is not None]
    if len(scope) != 1:
        raise click.ClickException("укажи ровно один из --id / --adgroup / --campaign")
    if context_bid is None and priority is None:
        raise click.ClickException("укажи хотя бы --context-bid или --priority")
    item: dict[str, Any] = {}
    if target_id is not None:
        item["Id"] = target_id
    elif adgroup_id is not None:
        item["AdGroupId"] = adgroup_id
    else:
        item["CampaignId"] = campaign_id
    if context_bid is not None:
        item["ContextBid"] = int(context_bid * 1_000_000)
    if priority:
        item["StrategyPriority"] = priority
    _confirm(f"audiencetargets.setBids: {item}", yes)
    data = asyncio.run(_get_client(ctx).set_audience_target_bids([item]))
    _print_result("SetBids", data)


# ---------- minus-sets ----------


@cli.group("minus-sets")
def minus_sets() -> None:
    """Общие наборы минус-слов."""


@minus_sets.command("list")
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def minus_sets_list(ctx, output) -> None:
    """Наборы общих минус-слов.

    Example: rb-yandex-direct minus-sets list
    """
    client = _get_client(ctx)
    data = asyncio.run(client.list_negative_keyword_shared_sets())
    if output:
        Path(output).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        console.print(f"[green]✓[/] {len(data)} наборов → {output}")
        return
    t = Table(title=f"Наборы минус-слов ({len(data)})")
    t.add_column("Id")
    t.add_column("Name")
    t.add_column("Кол-во фраз")
    for s in data:
        nks = s.get("NegativeKeywords") or {}
        items = nks.get("Items") or []
        t.add_row(str(s.get("Id", "")), str(s.get("Name", "")), str(len(items)))
    console.print(t)


@minus_sets.command("add")
@click.option("--name", required=True, help="имя набора")
@click.option("--words", help="список минус-фраз через запятую")
@click.option("--from-file", type=click.Path(exists=True), help="файл с фразами построчно")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def minus_sets_add(ctx, name, words, from_file, yes) -> None:
    """Создать набор общих минус-слов.

    Example: rb-yandex-direct minus-sets add --name 'Общие' --words 'бесплатно,скачать'
    """
    kws: list[str] = []
    if from_file:
        kws = [w.strip() for w in Path(from_file).read_text().splitlines() if w.strip()]
    elif words:
        kws = [w.strip() for w in words.split(",") if w.strip()]
    if not kws:
        raise click.ClickException("укажи --words или --from-file")
    _confirm(f"Создать набор «{name}» ({len(kws)} фраз)", yes)
    data = asyncio.run(_get_client(ctx).add_negative_keyword_shared_sets([{"Name": name, "NegativeKeywords": kws}]))
    _print_result("Add", data)


@minus_sets.command("delete")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def minus_sets_delete(ctx, ids, yes) -> None:
    """Удалить наборы минус-слов.

    Example: rb-yandex-direct minus-sets delete 6001
    """
    _confirm(f"[red]УДАЛИТЬ[/] {len(ids)} наборов минус-слов", yes)
    data = asyncio.run(_get_client(ctx).delete_negative_keyword_shared_sets(list(ids)))
    _print_result("Delete", data)


@minus_sets.command("update")
@click.argument("set_id", type=int)
@click.option("--name", help="новое имя набора")
@click.option("--words", help="полный список минус-фраз через запятую (заменяет текущие)")
@click.option("--from-file", type=click.Path(exists=True), help="файл с фразами по строкам")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def minus_sets_update(ctx, set_id, name, words, from_file, yes) -> None:
    """Обновить набор минус-слов (целиком заменяет фразы).

    Example: rb-yandex-direct minus-sets update 6001 --from-file minus.txt
    """
    kws: list[str] | None = None
    if from_file:
        kws = [w.strip() for w in Path(from_file).read_text().splitlines() if w.strip()]
    elif words:
        kws = [w.strip() for w in words.split(",") if w.strip()]
    if name is None and kws is None:
        raise click.ClickException("укажи --name, --words или --from-file")
    _confirm(
        f"Обновить набор {set_id}" + (f" ({len(kws)} фраз)" if kws else "") + (f", имя={name!r}" if name else ""),
        yes,
    )
    data = asyncio.run(
        _get_client(ctx).update_negative_keyword_shared_set(
            set_id=set_id,
            name=name,
            negative_keywords=kws,
        )
    )
    _print_result("Update", data)


# ---------- changes ----------


@cli.group()
def changes() -> None:
    """Синхронизация изменений (changes.* API)."""


@changes.command("check")
@click.argument("timestamp")
@click.option("--campaign", "campaign_ids", type=int, multiple=True, help="фильтр по кампании (можно несколько раз)")
@click.pass_context
def changes_check(ctx, timestamp: str, campaign_ids) -> None:
    """Что изменилось с указанного timestamp (ISO 8601, UTC).

    Example: rb-yandex-direct changes check 2026-09-01T00:00:00Z --campaign 12345
    """
    client = _get_client(ctx)
    data = asyncio.run(
        client.check_campaign_changes(
            timestamp=timestamp,
            campaign_ids=list(campaign_ids) or None,
        )
    )
    console.print_json(data=data)


@changes.command("dictionaries")
@click.argument("timestamp")
@click.pass_context
def changes_dict(ctx, timestamp: str) -> None:
    """Актуальность справочников.

    Example: rb-yandex-direct changes dictionaries 2026-09-01T00:00:00Z
    """
    client = _get_client(ctx)
    data = asyncio.run(client.check_dictionaries(timestamp))
    console.print_json(data=data)


# ---------- P3: campaigns.add/delete ----------


@campaigns.command("add-json")
@click.option(
    "--from-json",
    type=click.Path(exists=True),
    required=True,
    help="JSON-массив объектов кампаний с TextCampaign/SmartCampaign/... блоками",
)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def campaigns_add(ctx, from_json, yes) -> None:
    """Создать кампании из JSON-файла (сложная структура — смотри доку campaigns.add).

    Example: rb-yandex-direct campaigns add-json --from-json campaigns.json
    """
    items = json.loads(Path(from_json).read_text())
    if not isinstance(items, list) or not items:
        raise click.ClickException("JSON должен быть непустым массивом")
    _confirm(f"Создать {len(items)} кампаний", yes)
    data = asyncio.run(_get_client(ctx).add_campaigns(items))
    _print_result("Add", data)


@campaigns.command("delete")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def campaigns_delete(ctx, ids, yes) -> None:
    """Удалить кампании безвозвратно (должны быть archived).

    Example: rb-yandex-direct campaigns delete 12345
    """
    _confirm(f"[red]УДАЛИТЬ[/] {len(ids)} кампаний (необратимо, требуют archived)", yes)
    data = asyncio.run(_get_client(ctx).delete_campaigns(list(ids)))
    _print_result("Delete", data)


# ---------- P3: feeds / businesses / leads ----------


@cli.group()
def feeds() -> None:
    """Товарные фиды."""


@feeds.command("list")
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def feeds_list(ctx, output) -> None:
    """Товарные фиды.

    Example: rb-yandex-direct feeds list
    """
    client = _get_client(ctx)
    data = asyncio.run(client.list_feeds())
    _render_or_save(
        data,
        output,
        title=f"Фиды ({len(data)})",
        columns=["Id", "Name", "BusinessType", "SourceType", "FilterQuantity"],
    )


@feeds.command("add-json")
@click.option(
    "--from-json",
    type=click.Path(exists=True),
    required=True,
    help="JSON-файл со структурой для API (формат — как в документации метода)",
)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def feeds_add(ctx, from_json, yes) -> None:
    """Создать фиды из JSON-файла (структура — как в feeds.add).

    Example: rb-yandex-direct feeds add-json --from-json feeds.json
    """
    items = json.loads(Path(from_json).read_text())
    if not isinstance(items, list) or not items:
        raise click.ClickException("JSON должен быть непустым массивом")
    _confirm(f"Создать {len(items)} фидов", yes)
    data = asyncio.run(_get_client(ctx).add_feeds(items))
    _print_result("Add", data)


@feeds.command("delete")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def feeds_delete(ctx, ids, yes) -> None:
    """Удалить фиды.

    Example: rb-yandex-direct feeds delete 7001
    """
    _confirm(f"[red]УДАЛИТЬ[/] {len(ids)} фидов", yes)
    data = asyncio.run(_get_client(ctx).delete_feeds(list(ids)))
    _print_result("Delete", data)


@feeds.command("update-json")
@click.option("--from-json", type=click.Path(exists=True), required=True, help="JSON-массив объектов фидов с полем Id")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def feeds_update(ctx, from_json, yes) -> None:
    """Обновить фиды из JSON-файла.

    Example: rb-yandex-direct feeds update-json --from-json feeds.json
    """
    items = json.loads(Path(from_json).read_text())
    if not isinstance(items, list) or not items:
        raise click.ClickException("JSON должен быть непустым массивом")
    _confirm(f"Обновить {len(items)} фидов", yes)
    data = asyncio.run(_get_client(ctx).update_feeds(items))
    _print_result("Update", data)


@cli.command("businesses")
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def businesses_list(ctx, output) -> None:
    """Список бизнес-данных (Яндекс.Бизнес).

    Example: rb-yandex-direct businesses
    """
    client = _get_client(ctx)
    data = asyncio.run(client.list_businesses())
    _render_or_save(data, output, title=f"Бизнес-данные ({len(data)})", columns=["Id", "Name", "ChainId", "Status"])


@cli.command("leads")
@click.option("--campaign", "campaign_ids", type=int, multiple=True, help="фильтр по кампании (можно несколько раз)")
@click.option("--date-from", help="YYYY-MM-DD UTC")
@click.option("--date-to", help="YYYY-MM-DD UTC")
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def leads_list(ctx, campaign_ids, date_from, date_to, output) -> None:
    """Лиды с lead-форм и Турбо-страниц.

    Example: rb-yandex-direct leads --campaign 12345 --date-from 2026-09-01 --date-to 2026-09-27
    """
    client = _get_client(ctx)
    data = asyncio.run(
        client.list_leads(
            campaign_ids=list(campaign_ids) or None,
            date_from=date_from,
            date_to=date_to,
        )
    )
    _render_or_save(
        data, output, title=f"Лиды ({len(data)})", columns=["Id", "CampaignId", "AdGroupId", "AdId", "SubmitDateTime"]
    )


# ---------- P3: dynamic / smart ad targets ----------


@cli.group("dynamic-targets")
def dynamic_targets() -> None:
    """Условия таргетинга для динамических объявлений."""


@dynamic_targets.command("list")
@click.option(
    "--adgroup", "adgroup_ids", type=int, multiple=True, help="фильтр по группе объявлений (можно несколько раз)"
)
@click.option("--campaign", "campaign_ids", type=int, multiple=True, help="фильтр по кампании (можно несколько раз)")
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def dynamic_targets_list(ctx, adgroup_ids, campaign_ids, output) -> None:
    """Условия таргетинга динамических объявлений.

    Example: rb-yandex-direct dynamic-targets list --campaign 12345
    """
    client = _get_client(ctx)
    data = asyncio.run(
        client.list_dynamic_text_ad_targets(
            adgroup_ids=list(adgroup_ids) or None,
            campaign_ids=list(campaign_ids) or None,
        )
    )
    _render_or_save(
        data, output, title=f"Dynamic targets ({len(data)})", columns=["Id", "AdGroupId", "Name", "State", "Bid"]
    )


@dynamic_targets.command("suspend")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def dynamic_targets_suspend(ctx, ids, yes) -> None:
    """Остановить условия таргетинга динамических объявлений.

    Example: rb-yandex-direct dynamic-targets suspend 8001
    """
    _confirm(f"Остановить {len(ids)} dynamic-targets", yes)
    data = asyncio.run(_get_client(ctx).suspend_dynamic_text_ad_targets(list(ids)))
    _print_result("Suspend", data)


@dynamic_targets.command("resume")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def dynamic_targets_resume(ctx, ids, yes) -> None:
    """Возобновить условия таргетинга динамических объявлений.

    Example: rb-yandex-direct dynamic-targets resume 8001
    """
    _confirm(f"Включить {len(ids)} dynamic-targets", yes)
    data = asyncio.run(_get_client(ctx).resume_dynamic_text_ad_targets(list(ids)))
    _print_result("Resume", data)


@dynamic_targets.command("delete")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def dynamic_targets_delete(ctx, ids, yes) -> None:
    """Удалить условия таргетинга динамических объявлений.

    Example: rb-yandex-direct dynamic-targets delete 8001
    """
    _confirm(f"[red]УДАЛИТЬ[/] {len(ids)} dynamic-targets", yes)
    data = asyncio.run(_get_client(ctx).delete_dynamic_text_ad_targets(list(ids)))
    _print_result("Delete", data)


@dynamic_targets.command("add-json")
@click.option(
    "--from-json",
    type=click.Path(exists=True),
    required=True,
    help="JSON-массив объектов Webpage с AdGroupId и Condition",
)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def dynamic_targets_add(ctx, from_json, yes) -> None:
    """Создать условия таргетинга динамических объявлений из JSON-файла (dynamictextadtargets.add).

    Example: rb-yandex-direct dynamic-targets add-json --from-json targets.json
    """
    items = json.loads(Path(from_json).read_text())
    if not isinstance(items, list) or not items:
        raise click.ClickException("JSON должен быть непустым массивом")
    _confirm(f"Добавить {len(items)} dynamic-targets", yes)
    data = asyncio.run(_get_client(ctx).add_dynamic_text_ad_targets(items))
    _print_result("Add", data)


@dynamic_targets.command("set-bid")
@click.option("--id", "target_id", type=int, required=True, help="ID условия таргетинга")
@click.option("--bid", type=float, help="ставка поиск, рубли")
@click.option("--context-bid", type=float, help="ставка в сетях, рубли")
@click.option("--priority", type=click.Choice(["LOW", "NORMAL", "HIGH"]), help="приоритет для автостратегии")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def dynamic_targets_set_bid(ctx, target_id, bid, context_bid, priority, yes) -> None:
    """Установить ставки на условии таргетинга DynamicTextAd.

    Example: rb-yandex-direct dynamic-targets set-bid --id 8001 --bid 10
    """
    if bid is None and context_bid is None and priority is None:
        raise click.ClickException("укажи хотя бы --bid / --context-bid / --priority")
    item: dict[str, Any] = {"Id": target_id}
    if bid is not None:
        item["Bid"] = int(bid * 1_000_000)
    if context_bid is not None:
        item["ContextBid"] = int(context_bid * 1_000_000)
    if priority:
        item["StrategyPriority"] = priority
    _confirm(f"dynamictextadtargets.setBids: {item}", yes)
    data = asyncio.run(_get_client(ctx).set_dynamic_text_ad_target_bids([item]))
    _print_result("SetBids", data)


@cli.group("smart-targets")
def smart_targets() -> None:
    """Условия таргетинга для смарт-баннеров."""


@smart_targets.command("list")
@click.option(
    "--adgroup", "adgroup_ids", type=int, multiple=True, help="фильтр по группе объявлений (можно несколько раз)"
)
@click.option("--campaign", "campaign_ids", type=int, multiple=True, help="фильтр по кампании (можно несколько раз)")
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def smart_targets_list(ctx, adgroup_ids, campaign_ids, output) -> None:
    """Условия таргетинга смарт-баннеров.

    Example: rb-yandex-direct smart-targets list --campaign 12345
    """
    client = _get_client(ctx)
    data = asyncio.run(
        client.list_smart_ad_targets(
            adgroup_ids=list(adgroup_ids) or None,
            campaign_ids=list(campaign_ids) or None,
        )
    )
    _render_or_save(
        data, output, title=f"Smart targets ({len(data)})", columns=["Id", "AdGroupId", "Name", "State", "Bid"]
    )


@smart_targets.command("suspend")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def smart_targets_suspend(ctx, ids, yes) -> None:
    """Остановить условия таргетинга смарт-баннеров.

    Example: rb-yandex-direct smart-targets suspend 9001
    """
    _confirm(f"Остановить {len(ids)} smart-targets", yes)
    data = asyncio.run(_get_client(ctx).suspend_smart_ad_targets(list(ids)))
    _print_result("Suspend", data)


@smart_targets.command("resume")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def smart_targets_resume(ctx, ids, yes) -> None:
    """Возобновить условия таргетинга смарт-баннеров.

    Example: rb-yandex-direct smart-targets resume 9001
    """
    _confirm(f"Включить {len(ids)} smart-targets", yes)
    data = asyncio.run(_get_client(ctx).resume_smart_ad_targets(list(ids)))
    _print_result("Resume", data)


@smart_targets.command("delete")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def smart_targets_delete(ctx, ids, yes) -> None:
    """Удалить условия таргетинга смарт-баннеров.

    Example: rb-yandex-direct smart-targets delete 9001
    """
    _confirm(f"[red]УДАЛИТЬ[/] {len(ids)} smart-targets", yes)
    data = asyncio.run(_get_client(ctx).delete_smart_ad_targets(list(ids)))
    _print_result("Delete", data)


@smart_targets.command("add-json")
@click.option(
    "--from-json",
    type=click.Path(exists=True),
    required=True,
    help="JSON-массив объектов Filter с AdGroupId и Conditions",
)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def smart_targets_add(ctx, from_json, yes) -> None:
    """Создать условия таргетинга смарт-баннеров из JSON-файла (smartadtargets.add).

    Example: rb-yandex-direct smart-targets add-json --from-json targets.json
    """
    items = json.loads(Path(from_json).read_text())
    if not isinstance(items, list) or not items:
        raise click.ClickException("JSON должен быть непустым массивом")
    _confirm(f"Добавить {len(items)} smart-targets", yes)
    data = asyncio.run(_get_client(ctx).add_smart_ad_targets(items))
    _print_result("Add", data)


@smart_targets.command("set-bid")
@click.option("--id", "target_id", type=int, required=True, help="ID условия таргетинга")
@click.option("--bid", type=float, help="ставка в рублях")
@click.option("--priority", type=click.Choice(["LOW", "NORMAL", "HIGH"]), help="приоритет для автостратегии")
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def smart_targets_set_bid(ctx, target_id, bid, priority, yes) -> None:
    """Установить ставку на условии таргетинга Smart-баннера.

    Example: rb-yandex-direct smart-targets set-bid --id 9001 --bid 10
    """
    if bid is None and priority is None:
        raise click.ClickException("укажи хотя бы --bid или --priority")
    item: dict[str, Any] = {"Id": target_id}
    if bid is not None:
        item["Bid"] = int(bid * 1_000_000)
    if priority:
        item["StrategyPriority"] = priority
    _confirm(f"smartadtargets.setBids: {item}", yes)
    data = asyncio.run(_get_client(ctx).set_smart_ad_target_bids([item]))
    _print_result("SetBids", data)


# ---------- sitelinks ----------


@cli.group("sitelinks")
def sitelinks_cli() -> None:
    """Наборы быстрых ссылок."""


@sitelinks_cli.command("list")
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def sitelinks_list(ctx, output) -> None:
    """Наборы быстрых ссылок.

    Example: rb-yandex-direct sitelinks list
    """
    client = _get_client(ctx)
    data = asyncio.run(client.list_sitelinks())
    if output:
        Path(output).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        console.print(f"[green]✓[/] {len(data)} наборов → {output}")
        return
    t = Table(title=f"Наборы быстрых ссылок ({len(data)})")
    t.add_column("Id")
    t.add_column("Кол-во ссылок")
    t.add_column("Первый Title")
    for s in data:
        links = s.get("Sitelinks") or []
        t.add_row(str(s.get("Id", "")), str(len(links)), str((links[0] if links else {}).get("Title", ""))[:40])
    console.print(t)


@sitelinks_cli.command("add")
@click.option(
    "--from-json",
    type=click.Path(exists=True),
    required=True,
    help="JSON-файл с массивом [{Title, Href, Description?}, ...] (1-8 шт.)",
)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def sitelinks_add(ctx, from_json, yes) -> None:
    """Создать набор быстрых ссылок из JSON-файла.

    Example: rb-yandex-direct sitelinks add --from-json sitelinks.json
    """
    links = json.loads(Path(from_json).read_text())
    if not isinstance(links, list) or not (1 <= len(links) <= 8):
        raise click.ClickException("JSON должен быть массивом из 1-8 объектов")
    _confirm(f"Создать набор из {len(links)} ссылок", yes)
    data = asyncio.run(_get_client(ctx).add_sitelinks([{"Sitelinks": links}]))
    _print_result("Add", data)


@sitelinks_cli.command("delete")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def sitelinks_delete(ctx, ids, yes) -> None:
    """Удалить наборы быстрых ссылок.

    Example: rb-yandex-direct sitelinks delete 1101
    """
    _confirm(f"[red]УДАЛИТЬ[/] {len(ids)} наборов быстрых ссылок", yes)
    data = asyncio.run(_get_client(ctx).delete_sitelinks(list(ids)))
    _print_result("Delete", data)


# ---------- vcards ----------


@cli.group("vcards")
def vcards_cli() -> None:
    """Визитки (контактная информация)."""


@vcards_cli.command("list")
@click.option("--campaign", "campaign_ids", type=int, multiple=True, help="фильтр по кампании (можно несколько раз)")
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def vcards_list(ctx, campaign_ids, output) -> None:
    """Визитки (контактная информация).

    Example: rb-yandex-direct vcards list --campaign 12345
    """
    client = _get_client(ctx)
    data = asyncio.run(client.list_vcards(campaign_ids=list(campaign_ids) or None))
    _render_or_save(
        data,
        output,
        title=f"Визитки ({len(data)})",
        columns=["Id", "CampaignId", "CompanyName", "City", "ContactEmail"],
    )


@vcards_cli.command("add")
@click.option(
    "--from-json",
    type=click.Path(exists=True),
    required=True,
    help="JSON-файл с массивом vcard-объектов (см. client.add_vcards)",
)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def vcards_add(ctx, from_json, yes) -> None:
    """Создать визитки из JSON-файла.

    Example: rb-yandex-direct vcards add --from-json vcards.json
    """
    items = json.loads(Path(from_json).read_text())
    if not isinstance(items, list) or not items:
        raise click.ClickException("JSON должен быть непустым массивом")
    _confirm(f"Создать {len(items)} визиток", yes)
    data = asyncio.run(_get_client(ctx).add_vcards(items))
    _print_result("Add", data)


@vcards_cli.command("delete")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def vcards_delete(ctx, ids, yes) -> None:
    """Удалить визитки.

    Example: rb-yandex-direct vcards delete 1201
    """
    _confirm(f"[red]УДАЛИТЬ[/] {len(ids)} визиток", yes)
    data = asyncio.run(_get_client(ctx).delete_vcards(list(ids)))
    _print_result("Delete", data)


# ---------- adextensions ----------


@cli.group("extensions")
def extensions_cli() -> None:
    """Уточнения объявлений (callouts)."""


@extensions_cli.command("list")
@click.option(
    "--state",
    "states",
    multiple=True,
    type=click.Choice(["ON", "OFF", "SUSPENDED", "UNKNOWN"]),
    help="фильтр по состоянию (можно несколько раз)",
)
@click.option(
    "--status",
    "statuses",
    multiple=True,
    type=click.Choice(["ACCEPTED", "DRAFT", "MODERATION", "REJECTED", "UNKNOWN"]),
    help="фильтр по статусу модерации (можно несколько раз)",
)
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def extensions_list(ctx, states, statuses, output) -> None:
    """Уточнения объявлений (callouts).

    Example: rb-yandex-direct extensions list --status REJECTED
    """
    client = _get_client(ctx)
    data = asyncio.run(
        client.list_ad_extensions(
            states=list(states) or None,
            statuses=list(statuses) or None,
        )
    )
    _render_or_save(data, output, title=f"Уточнения ({len(data)})", columns=["Id", "Type", "State", "Status"])


@extensions_cli.command("add")
@click.argument("texts", nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def extensions_add(ctx, texts, yes) -> None:
    """Создать уточнения (callouts). Каждое ≤ 25 символов.

    Example: rb-yandex-direct extensions add 'Доставка за день' 'Гарантия 2 года'
    """
    items = [{"Callout": {"CalloutText": t}} for t in texts]
    _confirm(f"Создать {len(items)} уточнений", yes)
    data = asyncio.run(_get_client(ctx).add_ad_extensions(items))
    _print_result("Add", data)


@extensions_cli.command("moderate")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def extensions_moderate(ctx, ids, yes) -> None:
    """Отправить уточнения на модерацию.

    Example: rb-yandex-direct extensions moderate 1301
    """
    _confirm(f"Отправить {len(ids)} уточнений на модерацию", yes)
    data = asyncio.run(_get_client(ctx).moderate_ad_extensions(list(ids)))
    _print_result("Moderate", data)


@extensions_cli.command("delete")
@click.argument("ids", type=int, nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def extensions_delete(ctx, ids, yes) -> None:
    """Удалить уточнения.

    Example: rb-yandex-direct extensions delete 1301
    """
    _confirm(f"[red]УДАЛИТЬ[/] {len(ids)} уточнений", yes)
    data = asyncio.run(_get_client(ctx).delete_ad_extensions(list(ids)))
    _print_result("Delete", data)


# ---------- creatives: images / videos / turbo ----------


@cli.group("images")
def images_cli() -> None:
    """Изображения для объявлений (adimages)."""


@images_cli.command("list")
@click.option("--associated", type=click.Choice(["YES", "NO"]), help="YES — привязанные к объявлениям, NO — свободные")
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def images_list(ctx, associated, output) -> None:
    """Изображения, загруженные в кабинет.

    Example: rb-yandex-direct images list --output images.json
    """
    client = _get_client(ctx)
    data = asyncio.run(client.list_ad_images(associated=associated))
    _render_or_save(
        data,
        output,
        title=f"Изображения ({len(data)})",
        columns=["AdImageHash", "Name", "Type", "Associated", "PreviewUrl"],
    )


@images_cli.command("add")
@click.argument("paths", type=click.Path(exists=True), nargs=-1, required=True)
@click.option(
    "--type",
    "image_type",
    type=click.Choice(["REGULAR", "WIDE", "FIXED_IMAGE", "AUTO"]),
    default="AUTO",
    help="тип изображения (AUTO — по размеру файла)",
)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def images_add(ctx, paths, image_type, yes) -> None:
    """Загрузить изображения из файлов (до 100, рекомендуется ≤3).

    Example: rb-yandex-direct images add banner.png
    """
    import base64

    if len(paths) > 100:
        raise click.ClickException(f"не более 100 файлов за вызов, получено {len(paths)}")
    items = []
    for p in paths:
        path = Path(p)
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        items.append({"ImageData": data, "Name": path.name, "Type": image_type})
    _confirm(f"Загрузить {len(items)} изображений (type={image_type})", yes)
    result = asyncio.run(_get_client(ctx).add_ad_images(items))
    for r in result.get("AddResults", []):
        if r.get("AdImageHash"):
            console.print(f"[green]✓[/] {r['AdImageHash']}")
        for e in r.get("Errors") or []:
            console.print(f"  [red]⨯[/] [{e.get('Code')}] {e.get('Message')}")


@images_cli.command("delete")
@click.argument("hashes", nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def images_delete(ctx, hashes, yes) -> None:
    """Удалить изображения по хэшам.

    Example: rb-yandex-direct images delete abc123hash
    """
    _confirm(f"[red]УДАЛИТЬ[/] {len(hashes)} изображений", yes)
    data = asyncio.run(_get_client(ctx).delete_ad_images(list(hashes)))
    _print_result("Delete", data)


@cli.group("creatives")
def creatives_cli() -> None:
    """Креативы (HTML5/видео/смарт-баннеры) — только чтение."""


@creatives_cli.command("list")
@click.option(
    "--type",
    "types",
    multiple=True,
    type=click.Choice(
        [
            "IMAGE_CREATIVE",
            "HTML5_CREATIVE",
            "VIDEO_EXTENSION_CREATIVE",
            "CPC_VIDEO_CREATIVE",
            "CPM_VIDEO_CREATIVE",
            "SMART_CREATIVE",
        ]
    ),
    help="фильтр по типу креатива (можно несколько раз)",
)
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def creatives_list(ctx, types, output) -> None:
    """Креативы (HTML5, видео, смарт-баннеры).

    Example: rb-yandex-direct creatives list --type VIDEO_EXTENSION_CREATIVE
    """
    client = _get_client(ctx)
    data = asyncio.run(client.list_creatives(types=list(types) or None))
    _render_or_save(
        data, output, title=f"Креативы ({len(data)})", columns=["Id", "Type", "Name", "Width", "Height", "Associated"]
    )


@creatives_cli.command("add-video-extension")
@click.argument("video_ids", nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="без подтверждения")
@click.pass_context
def creatives_add_video_ext(ctx, video_ids, yes) -> None:
    """Создать VideoExtensionCreative из VideoId (получи через AdVideos до 10 за вызов).

    Example: rb-yandex-direct creatives add-video-extension 5f1a2b3c
    """
    items = [{"VideoExtensionCreative": {"VideoId": v}} for v in video_ids]
    _confirm(f"Создать {len(items)} VideoExtensionCreative", yes)
    data = asyncio.run(_get_client(ctx).add_creatives(items))
    _print_result("Add", data)


@cli.group("turbo")
def turbo_cli() -> None:
    """Турбо-страницы."""


@turbo_cli.command("list")
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def turbo_list(ctx, output) -> None:
    """Турбо-страницы клиента.

    Example: rb-yandex-direct turbo list
    """
    client = _get_client(ctx)
    data = asyncio.run(client.list_turbopages())
    _render_or_save(
        data,
        output,
        title=f"Турбо-страницы ({len(data)})",
        columns=["Id", "Name", "Href", "ModerationStatus", "CampaignType"],
    )


# ---------- dictionaries ----------

VALID_DICT_NAMES = [
    "Currencies",
    "TimeZones",
    "GeoRegions",
    "AdCategories",
    "OperationSystemVersions",
    "ProductivityIndicators",
    "SupplyChainStages",
    "AutoBusinesses",
    "Constants",
    "LegalPersonDocumentTypes",
    "SubjectSchema",
]


@cli.group("dict")
def dict_() -> None:
    """Справочники: регионы, валюты, таймзоны, категории."""


@dict_.command("get")
@click.argument("names", nargs=-1, required=True, type=click.Choice(VALID_DICT_NAMES))
@click.option("--output", type=click.Path(), help="сохранить JSON в файл")
@click.pass_context
def dict_get(ctx, names, output) -> None:
    """Получить один или несколько справочников.

    Example: rb-yandex-direct dict get Currencies GeoRegions --output dict.json
    """
    data = asyncio.run(_get_client(ctx).get_dictionaries(list(names)))
    if output:
        Path(output).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        console.print(f"[green]✓[/] {list(names)} → {output}")
        return
    console.print_json(data=data)


# ---------- report ----------


@cli.group()
def report() -> None:
    """Отчёты v5 (TSV, polling)."""


def _run_report(ctx: click.Context, coro, output: str | None) -> None:
    with console.status("[cyan]Генерирую отчёт..."):
        rep = asyncio.run(coro)
    if output:
        Path(output).write_text(rep.tsv)
        console.print(f"[green]✓[/] TSV → {output} (RequestId={rep.request_id})")
    else:
        console.print(rep.tsv)


def _reports_client(ctx: click.Context) -> ReportsClient:
    return ReportsClient(
        token=direct_auth.resolve_token(),
        client_login=ctx.obj.get("login") or os.getenv("YANDEX_DIRECT_LOGIN"),
        sandbox=bool(ctx.obj.get("sandbox")) or os.getenv("YANDEX_DIRECT_SANDBOX", "").lower() == "true",
    )


@report.command("campaigns")
@click.option("--date-from", required=True, help="начало периода, YYYY-MM-DD")
@click.option("--date-to", required=True, help="конец периода, YYYY-MM-DD")
@click.option("--output", "-o", type=click.Path(), help="сохранить строки отчёта в JSON-файл")
@click.pass_context
def report_campaigns(ctx, date_from, date_to, output) -> None:
    """CAMPAIGN_PERFORMANCE_REPORT: эффективность кампаний.

    Example: rb-yandex-direct report campaigns --date-from 2026-09-01 --date-to 2026-09-27
    """
    rc = _reports_client(ctx)
    _run_report(ctx, rc.campaign_performance(date_from, date_to), output)


@report.command("ads")
@click.option("--date-from", required=True, help="начало периода, YYYY-MM-DD")
@click.option("--date-to", required=True, help="конец периода, YYYY-MM-DD")
@click.option("--output", "-o", type=click.Path(), help="сохранить строки отчёта в JSON-файл")
@click.pass_context
def report_ads(ctx, date_from, date_to, output) -> None:
    """AD_PERFORMANCE_REPORT: эффективность объявлений.

    Example: rb-yandex-direct report ads --date-from 2026-09-01 --date-to 2026-09-27 -o ads.json
    """
    rc = _reports_client(ctx)
    _run_report(ctx, rc.ad_performance(date_from, date_to), output)


@report.command("queries")
@click.option("--date-from", required=True, help="начало периода, YYYY-MM-DD")
@click.option("--date-to", required=True, help="конец периода, YYYY-MM-DD")
@click.option("--campaign", "campaign_ids", type=int, multiple=True, help="фильтр по кампании (можно несколько раз)")
@click.option("--output", "-o", type=click.Path(), help="сохранить строки отчёта в JSON-файл")
@click.pass_context
def report_queries(ctx, date_from, date_to, campaign_ids, output) -> None:
    """SEARCH_QUERY_PERFORMANCE_REPORT: реальные поисковые запросы пользователей.

    Example: rb-yandex-direct report queries --date-from 2026-09-01 --date-to 2026-09-27 --campaign 12345
    """
    rc = _reports_client(ctx)
    _run_report(ctx, rc.search_query_performance(date_from, date_to, list(campaign_ids) or None), output)


@report.command("account")
@click.option("--date-from", required=True, help="начало периода, YYYY-MM-DD")
@click.option("--date-to", required=True, help="конец периода, YYYY-MM-DD")
@click.option("--output", "-o", type=click.Path(), help="сохранить строки отчёта в JSON-файл")
@click.pass_context
def report_account(ctx, date_from, date_to, output) -> None:
    """ACCOUNT_PERFORMANCE_REPORT: итог по аккаунту.

    Example: rb-yandex-direct report account --date-from 2026-09-01 --date-to 2026-09-27
    """
    rc = _reports_client(ctx)
    _run_report(ctx, rc.account_performance(date_from, date_to), output)


@report.command("custom")
@click.option("--type", "report_type", required=True, help="CAMPAIGN_PERFORMANCE_REPORT | AD_PERFORMANCE_REPORT | ...")
@click.option("--date-from", required=True, help="начало периода, YYYY-MM-DD")
@click.option("--date-to", required=True, help="конец периода, YYYY-MM-DD")
@click.option("--fields", default="Date,CampaignId,Impressions,Clicks,Cost", help="поля отчёта через запятую")
@click.option("--output", "-o", type=click.Path(), help="сохранить строки отчёта в JSON-файл")
@click.pass_context
def report_custom(ctx, report_type, date_from, date_to, fields, output) -> None:
    """Произвольный отчёт с указанием полей.

    Example: rb-yandex-direct report custom --type CUSTOM_REPORT --date-from 2026-09-01 --date-to 2026-09-27 --fields Date,Clicks,Cost
    """
    rc = _reports_client(ctx)
    _run_report(
        ctx,
        rc.run(
            report_type=report_type,
            field_names=[f.strip() for f in fields.split(",")],
            date_from=date_from,
            date_to=date_to,
        ),
        output,
    )


# ---------- helpers ----------


def _render_or_save(data: list[dict], output: str | None, *, title: str, columns: list[str]) -> None:
    if output:
        Path(output).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        console.print(f"[green]✓[/] {len(data)} записей → {output}")
        return
    t = Table(title=title)
    for col in columns:
        t.add_column(col)
    for row in data[:100]:
        t.add_row(*[str(row.get(col, ""))[:60] for col in columns])
    console.print(t)


# ---------- mcp ----------


@cli.command()
def mcp() -> None:
    """Запустить MCP-сервер (stdio).

    Example: rb-yandex-direct mcp
    """
    from rb_yandex_direct.mcp_server import serve

    serve()


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
