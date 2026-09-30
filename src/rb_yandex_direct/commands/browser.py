"""`yd browser` — сессия Яндекса для команд веб-интерфейса (`masters`, `history`).

Три источника, по порядку: свой профиль Chromium (`login`), снимок кук из Chrome
(`login --from-chrome`), иначе — свежая расшифровка кук Chrome на каждый вызов.
Всё хранится в папке данных yd (`status` показывает пути); Chrome пользователя не меняется.
"""

from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..providers import browser
from ._web import ChromeDirOption, ChromeProfileOption

app = output.group("Сессия Яндекса для команд веб-интерфейса (masters, history): вход, состояние, диагностика, выход.")


@app.command("login")
@output.guard
def login(
    ctx: typer.Context,
    from_chrome: bool = typer.Option(
        False, "--from-chrome", help="Не открывать окно: сохранить куки Яндекса из вашего Chrome."
    ),
    no_verify: bool = typer.Option(
        False, "--no-verify", help="С --from-chrome: не проверять куки открытием Директа (сеть с капчей)."
    ),
    timeout: int = typer.Option(300, "--timeout", help="Сколько секунд ждать ручного входа в окне."),
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Сохранить сессию Яндекса для `masters` и `history`.

    По умолчанию открывает окно Chromium со своим профилем — войдите в Яндекс руками один раз,
    дальше куки живут в профиле (работает на macOS, Linux и Windows, без keychain).
    --from-chrome — без окна: расшифровать куки Яндекса из вашего Chrome (на macOS один раз
    спросит доступ к keychain) и сохранить снимок. С --non-interactive доступен только --from-chrome.

    Example: {cli} browser login --from-chrome
    """
    from ..core.errors import InvalidArguments

    if ctx.obj.get("non_interactive") and not from_chrome:
        raise InvalidArguments("Ручной вход в окне невозможен с --non-interactive: используйте --from-chrome.")
    if not from_chrome:
        output.human.err_console.print("Откроется окно Chromium: войдите в Яндекс и дождитесь его закрытия.")
    result = browser.login(
        from_chrome=from_chrome,
        timeout_s=timeout,
        chrome_dir=Path(chrome_dir) if chrome_dir else None,
        chrome_profile=chrome_profile,
        verify=not no_verify,
    )
    output.emit_success(
        ctx,
        result,
        lambda d: output.human.echo_markup(f"[green]✓[/green] Сессия сохранена ({d['source']}): {d['path']}"),
    )


@app.command("status")
@output.guard
def status(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Какую сессию возьмут `masters`/`history` и что о ней известно — без сети и браузера.

    `active`: profile (свой Chromium после `browser login`), saved (снимок кук после
    `browser login --from-chrome`; с датой истечения) или chrome (свежие куки Chrome каждый раз).
    --json: {"ok": true, "active", "profile": {path, usable}, "saved": {path, exists, expired, …}}.

    Example: {cli} browser status --json
    """
    data = browser.status()

    def render(d: dict) -> None:
        output.human.key_values(
            "Браузерная сессия",
            {
                "используется": d["active"],
                "профиль": f"{d['profile']['path']} ({'есть' if d['profile']['usable'] else 'нет'})",
                "снимок кук": f"{d['saved']['path']} ({'есть' if d['saved'].get('exists') else 'нет'})",
            },
        )

    output.emit_success(ctx, data, render)


@app.command("doctor")
@output.guard
def doctor(
    ctx: typer.Context,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Готовность веб-интерфейса: playwright и Chromium, доступ к кукам Chrome, сохранённая сессия.

    Всегда код 0 — результат в самом отчёте; `ok: null` — проверка неприменима.
    --json: {"ok": true, "healthy": bool, "checks": [{name, ok, detail, hint}]}.

    Example: {cli} browser doctor --json
    """
    checks = browser.diagnostics(chrome_dir=Path(chrome_dir) if chrome_dir else None, chrome_profile=chrome_profile)
    healthy = all(check["ok"] is not False for check in checks)

    def render(d: dict) -> None:
        output.human.render_doctor(
            [{"name": c["name"], "ok": c["ok"] is not False, "detail": c["hint"] or c["detail"]} for c in d["checks"]]
        )

    output.emit_success(ctx, {"healthy": healthy, "checks": checks}, render)


@app.command("logout")
@output.guard
def logout(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить свой профиль Chromium и снимок кук yd (ваш Chrome не трогается).

    Example: {cli} browser logout
    """
    result = browser.logout()
    output.emit_success(
        ctx,
        result,
        lambda d: output.human.echo(f"Удалено: {', '.join(d['removed'])}" if d["removed"] else "Нечего удалять."),
    )
