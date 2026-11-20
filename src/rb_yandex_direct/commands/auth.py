"""`yd auth` — токен Директа: вход, статус (§8 стандарта tools), обновление, выход.

Хранилище и обновление токена — rb-yandex-oauth (`core.auth.store`). Вход — свой:
у Директа отдельное OAuth-приложение с подтверждённой заявкой на API, поэтому его
client_id берётся из YANDEX_OAUTH_DIRECT_CLIENT_ID, а не из общего YANDEX_CLIENT_ID ym/ywm;
и есть потоки, которых нет в общей команде: localhost-callback и device flow.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime

import typer
from rb_yandex_oauth import status
from rb_yandex_oauth.oauth import TokenSet, parse_manual_token

from .. import output
from ..constants import PROFILE
from ..core import services
from ..core.auth import store
from ..core.errors import CliError, CredentialsUnhealthy, InvalidArguments
from ..core.version import DEV_VERSION, installed_version
from ..providers.direct import DirectProvider
from ..providers.oauth import OAuthToken, YandexOAuth

app = output.group(
    "OAuth-токен Директа: вход, статус, обновление, выход. Токен — в keychain ОС (yandex-oauth:direct) "
    "и обновляется сам; без keychain — YANDEX_OAUTH_DIRECT_REFRESH_TOKEN/CLIENT_ID/CLIENT_SECRET "
    "или готовый YANDEX_DIRECT_TOKEN. Файлы .env не читаются."
)

# Прежние имена переменных OAuth-приложения Директа (до перехода на rb-yandex-oauth).
LEGACY_CLIENT_ID_ENV = "YANDEX_DIRECT_CLIENT_ID"
LEGACY_CLIENT_SECRET_ENV = "YANDEX_DIRECT_CLIENT_SECRET"  # noqa: S105 — имя переменной, не секрет


def app_credentials(client_id: str | None = None, client_secret: str | None = None) -> tuple[str | None, str | None]:
    """OAuth-приложение Директа: аргумент → YANDEX_OAUTH_DIRECT_CLIENT_* → YANDEX_DIRECT_CLIENT_* → keychain."""
    stored = store.stored()
    cid = client_id or os.getenv(store.env_var("client_id")) or os.getenv(LEGACY_CLIENT_ID_ENV)
    secret = client_secret or os.getenv(store.env_var("client_secret")) or os.getenv(LEGACY_CLIENT_SECRET_ENV)
    return cid or stored.get("client_id"), secret or stored.get("client_secret")


def _token_set(token: OAuthToken) -> TokenSet:
    expires_in = int((token.expires_at - datetime.now(UTC)).total_seconds()) if token.expires_at else None
    return TokenSet(token.access_token, token.refresh_token, expires_in)


def _describe(bag: dict) -> dict:
    exp = store.expires_at(bag)
    return {"expires_at": exp.isoformat() if exp else None, "refreshable": store.can_refresh(bag)}


def _render_token(title: str) -> Callable[[dict], None]:
    def render(data: dict) -> None:
        output.human.echo_markup(f"[green]✓[/green] {title}")
        if data["expires_at"]:
            output.human.echo(f"  действует до: {data['expires_at'][:10]}")
        output.human.echo(f"  автообновление: {'да' if data['refreshable'] else 'нет (токен вставлен вручную)'}")

    return render


@app.command("login")
@output.guard
def login(
    ctx: typer.Context,
    token: str = typer.Option(
        None, "--token", help="Готовый OAuth-токен или адрес …verification_code#access_token=… (без автообновления)."
    ),
    oob: bool = typer.Option(False, "--oob", help="Ввести код со страницы подтверждения вручную (ssh, без браузера)."),
    device: bool = typer.Option(False, "--device", help="Device flow: код подтверждается на другом устройстве."),
    client_id: str = typer.Option(None, "--client-id", help="ID OAuth-приложения (или YANDEX_OAUTH_DIRECT_CLIENT_ID)."),
    client_secret: str = typer.Option(
        None, "--client-secret", help="Секрет OAuth-приложения (или YANDEX_OAUTH_DIRECT_CLIENT_SECRET)."
    ),
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Получить OAuth-токен Директа и сохранить в keychain вместе с refresh_token.

    По умолчанию открывает браузер и ловит код на localhost; --oob — код вручную,
    --device — подтверждение на другом устройстве, --token — готовый токен.
    Приложение: --client-id/--client-secret, иначе YANDEX_OAUTH_DIRECT_CLIENT_ID/SECRET
    (прежние YANDEX_DIRECT_CLIENT_ID/SECRET тоже читаются), иначе — с прошлого входа.
    С --non-interactive работает только --token. Создать приложение:
    https://oauth.yandex.ru/?dialog=create-client-entry, права direct:api и passport:business;
    для prod нужна подтверждённая заявка на доступ к API (direct.yandex.ru → Настройки API →
    Мои заявки), иначе API отвечает кодом 58.

    Example: {cli} auth login --client-id abc123 --client-secret s3cr3t
    """
    cid, secret = app_credentials(client_id, client_secret)
    if token:
        bag = store.store_token_set(parse_manual_token(token), cid, secret)
    else:
        if ctx.obj.get("non_interactive"):
            raise InvalidArguments("Вход через браузер недоступен с --non-interactive: передайте --token.")
        if not cid or not secret:
            raise InvalidArguments(
                "Не задан client_id/client_secret: передайте --client-id/--client-secret или задайте "
                "YANDEX_OAUTH_DIRECT_CLIENT_ID/YANDEX_OAUTH_DIRECT_CLIENT_SECRET. "
                "Приложение: https://oauth.yandex.ru/?dialog=create-client-entry (direct:api + passport:business)."
            )
        flow = YandexOAuth(cid, secret)
        if device:
            got = services.run(_device(flow))
        elif oob:
            got = services.run(_oob(flow))
        else:
            output.human.err_console.print("Открываю браузер для входа в Яндекс…")
            got = services.run(flow.authorize_interactive(print_url=lambda u: output.human.err_console.print(u)))
        bag = store.store_token_set(_token_set(got), cid, secret)
    output.emit_success(ctx, _describe(bag), _render_token("Токен сохранён в keychain (yandex-oauth:direct)"))


async def _oob(flow: YandexOAuth) -> OAuthToken:
    err = output.human.err_console
    err.print(f"1. Откройте в браузере:\n   {flow.build_oob_url()}")
    err.print("2. Войдите и скопируйте код со страницы подтверждения.")
    code = typer.prompt("   Код", err=True).strip()
    return await flow.authorize_oob(code)


async def _device(flow: YandexOAuth) -> OAuthToken:
    info = await flow.device_code_start()
    err = output.human.err_console
    err.print(f"1. Откройте: {info.get('verification_url')}")
    err.print(f"2. Введите код: {info.get('user_code')}")
    err.print("Жду подтверждения…")
    return await flow.device_code_poll(info["device_code"], interval=info.get("interval", 5))


@app.command("refresh")
@output.guard
def refresh(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Принудительно обновить токен по refresh_token (без браузера).

    Обычно не нужно: токен обновляется сам за 30 дней до истечения.
    Без keychain обновлённый токен живёт только в памяти процесса.

    Example: {cli} auth refresh
    """
    output.emit_success(ctx, _describe(store.refresh()), _render_token("Токен обновлён"))


@app.command("logout")
@output.guard
def logout(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить токен и данные приложения из keychain (переменные окружения не трогает).

    Example: {cli} auth logout
    """
    store.delete()
    output.emit_success(ctx, {"deleted": True}, lambda _: output.human.echo("Токен Директа удалён из keychain."))


def status_report(*, check: bool) -> tuple[dict, CliError | None]:
    """Отчёт §8 и ошибка CREDENTIALS_UNHEALTHY, если код выхода должен быть 3."""
    quota: list = []

    def probe() -> None:
        health = DirectProvider().health_check()
        quota.append(health.quota)

    entry = status.credential_status(store, live=check, check=probe)
    if entry["status"] == "ok" and quota and quota[0] is not None:
        q = quota[0]
        entry["quota"] = {"remaining": q.remaining, "limit": q.limit, "unit": q.unit}
    report = status.status_report(PROFILE.cli_name, installed_version() or DEV_VERSION, [entry])
    problems = status.status_problems(report)
    return report, (CredentialsUnhealthy(PROFILE, problems) if problems else None)


def _render_status(report: dict) -> None:
    for entry in report["credentials"]:
        mark = {"ok": "✓", "unchecked": "·"}.get(entry["status"], "✗")
        expires = f", до {entry['expires_at'][:10]}" if entry["expires_at"] else ""
        quota = entry["quota"]
        units = f", баллы {quota['remaining']}/{quota['limit']}" if quota else ""
        detail = f" — {entry['message']}" if entry["message"] else ""
        line = f"{entry['provider']}: {entry['status']} ({entry['source']}: {entry['source_ref']}){expires}{units}"
        output.human.echo(f"{mark} {line}{detail}")


@app.command("status")
@output.guard
def auth_status(
    ctx: typer.Context,
    check: bool = typer.Option(False, "--check", help="Проверить токен запросом clients.get (не дольше 10 с)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Откуда берётся токен и работает ли он. Значений секретов не печатает.

    Без --check — только наличие и срок (unchecked / missing / expired), без сети.
    Код выхода 0 — всё в порядке, 3 — токена нет, он истёк или Директ его не принимает.
    --json: {ok, tool, version, checked_at, credentials[]} — provider, required, fields,
    source, source_ref, status, expires_at, quota (баллы API: остаток и суточный лимит),
    message; при коде 3 — ok: false и error CREDENTIALS_UNHEALTHY рядом с отчётом.

    Example: {cli} auth status --check --json
    """
    report, problem = status_report(check=check)
    output.emit_report(ctx, report, _render_status, problem)
