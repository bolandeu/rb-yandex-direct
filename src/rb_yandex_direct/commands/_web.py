"""Общее для команд веб-интерфейса (`masters`, `history`, `browser`): опции сессии и изменения.

Изменения в Мастере кампаний идут через браузер, а не через API, поэтому `_common.mutate`
здесь не подходит; семантика та же: --dry-run показывает, что будет сделано, иначе —
подтверждение (или --confirm) и действие.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from .. import output
from ..core.errors import InvalidArguments
from ..providers import browser

HeadfulOption = typer.Option(False, "--headful", help="Показать окно браузера (отладка, капча).")
ChromeDirOption = typer.Option(
    None,
    "--chrome-dir",
    help="Папка профилей Chrome (user-data-dir): всегда свежие куки оттуда, без сохранённой сессии.",
)
ChromeProfileOption = typer.Option("Default", "--chrome-profile", help="Профиль Chrome внутри --chrome-dir.")


def run(
    ctx: typer.Context, operation: Callable[[Any], Any], headful: bool, chrome_dir: str | None, chrome_profile: str
) -> Any:
    output.vecho(ctx, "Открываю браузерную сессию Директа…")
    return browser.run(
        operation, headful=headful, chrome_dir=Path(chrome_dir) if chrome_dir else None, chrome_profile=chrome_profile
    )


def web_mutate(
    ctx: typer.Context,
    *,
    title: str,
    action: str,
    params: dict,
    operation: Callable[[Any], Any],
    confirm: bool,
    headful: bool,
    chrome_dir: str | None,
    chrome_profile: str,
) -> None:
    """Изменение через веб-интерфейс: --dry-run → план; иначе подтверждение → действие → результат."""
    plan = {"title": title, "action": action, "params": params}
    if output.is_dry_run(ctx):

        def render_plan(d: dict) -> None:
            output.human.echo(f"[dry-run] {d['title']} ({d['action']})")
            output.human.console.print_json(data=d["params"])

        output.emit_success(ctx, {"dry_run": True, **plan}, render_human=render_plan)
        return
    output.require_confirmation(ctx, f"{title} (веб-интерфейс, {action})", confirm)
    result = run(ctx, operation, headful, chrome_dir, chrome_profile)

    def render(d: dict) -> None:
        output.human.echo_markup(f"[green]✓[/green] {d['title']}")
        output.human.console.print_json(data=d["result"])

    output.emit_success(ctx, {**plan, "result": result}, render_human=render)


def parse_slots(option: str, values: list[str] | None, limit: int) -> dict[int, str]:
    """`N=значение` (N с 1, как на странице) → {индекс с 0: значение}; ошибки — до запуска браузера."""
    parsed: dict[int, str] = {}
    for raw in values or []:
        number, sep, value = raw.partition("=")
        if not sep or not number.strip().isdigit():
            raise InvalidArguments(f'{option} {raw!r}: ожидается "N=значение", например "2=Новый текст".')
        slot = int(number)
        if not 1 <= slot <= limit:
            raise InvalidArguments(f"{option}: номер {slot} вне диапазона 1–{limit}.")
        if slot - 1 in parsed:
            raise InvalidArguments(f"{option}: номер {slot} указан дважды.")
        if not value.strip():
            raise InvalidArguments(f"{option}: пустое значение для {slot} — удалить вариант можно через --clear-*.")
        parsed[slot - 1] = value
    return parsed


def parse_goal_prices(option: str, values: list[str] | None) -> dict[int, float]:
    """`ID_цели=цена` → {goal_id: цена}."""
    parsed: dict[int, float] = {}
    for raw in values or []:
        goal, sep, price = raw.partition("=")
        if not sep:
            raise InvalidArguments(f'{option} {raw!r}: ожидается "ID_цели=цена", например "236386933=150".')
        try:
            parsed[int(goal)] = float(price)
        except ValueError:
            raise InvalidArguments(f'{option} {raw!r}: ожидается "ID_цели=цена", например "236386933=150".') from None
    return parsed


def one_based(option: str, values: list[int] | None) -> list[int]:
    """Номера позиций с 1 (как видит человек) → индексы с 0 (как ждёт библиотека)."""
    out = []
    for value in values or []:
        if value < 1:
            raise InvalidArguments(f"{option}: позиции считаются с 1, получено {value}.")
        out.append(value - 1)
    return out
