"""Общее для команд Директа: вывод списков, изменения с dry-run/--confirm, разбор `*Results`.

Команды остаются тонкими: собрать параметры → `emit_list(...)` или `mutate(...)`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine, Sequence
from pathlib import Path
from typing import Any

import typer
from rich.markup import escape
from rich.table import Table

from .. import output
from ..core import services
from ..core.errors import CliError, InvalidArguments

# Колонка человеческой таблицы: заголовок и ключ записи (через точку для вложенных) или функция.
Column = tuple[str, str | Callable[[dict], Any]]

IdsArgument = typer.Argument(..., help="Id объектов через пробел.")
FromJsonOption = typer.Option(
    ..., "--from-json", help="JSON-файл с параметрами метода API (как в документации Директа); `-` — stdin."
)


def ctx_obj(ctx: typer.Context) -> dict:
    return ctx.obj


def pick(item: dict, path: str) -> Any:
    """Значение по пути `A.B.C` во вложенных dict; нет ключа — None."""
    value: Any = item
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def table(title: str, items: Sequence[dict], columns: Sequence[Column]) -> Table:
    t = Table(title=escape(title), show_header=True, header_style="bold cyan")
    for header, _ in columns:
        t.add_column(escape(header), overflow="fold")
    for item in items:
        t.add_row(*(escape(_cell(key(item) if callable(key) else pick(item, key))) for _, key in columns))
    return t


def emit_list(
    ctx: typer.Context,
    key: str,
    items: list[dict],
    columns: Sequence[Column],
    *,
    title: str,
    extra: dict | None = None,
) -> None:
    """Список объектов: `--json` → {"ok": true, "count": N, <key>: [...] (+extra)}; иначе таблица."""

    def render(_: dict) -> None:
        if not items:
            output.human.echo(f"{title}: пусто.")
            return
        output.human.console.print(table(f"{title} ({len(items)})", items, columns))

    output.emit_success(ctx, {"count": len(items), key: items, **(extra or {})}, render_human=render)


def emit_object(ctx: typer.Context, key: str, value: Any, *, title: str) -> None:
    """Один объект или произвольный ответ API: `--json` → {"ok": true, <key>: ...}; иначе JSON с отступами."""

    def render(_: dict) -> None:
        output.human.echo(title)
        output.human.console.print_json(data=value)

    output.emit_success(ctx, {key: value}, render_human=render)


def read_json(path: str) -> Any:
    """JSON из файла (`-` — stdin); ошибка разбора — INVALID_ARGUMENTS, а не трейсбек."""
    try:
        text = typer.get_text_stream("stdin").read() if path == "-" else Path(path).read_text(encoding="utf-8")
        return json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidArguments(f"Не удалось прочитать JSON из {path!r}: {exc}") from exc


def read_lines(words: list[str] | None, from_file: str | None) -> list[str]:
    """Список строк из повторяемой опции и/или файла (по строке, пустые и `#`-комментарии пропускаются)."""
    out = list(words or [])
    if from_file:
        text = Path(from_file).read_text(encoding="utf-8")
        out += [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return out


def _results(result: dict) -> list[dict]:
    """Поэлементные итоги из ответа изменяющего метода: `AddResults`, `SuspendResults`, `SetResults`…"""
    for key, value in result.items():
        if key.endswith("Results") and isinstance(value, list):
            return value
    return []


def summarize(result: dict) -> dict:
    """{"succeeded", "failed", "ids", "errors", "warnings"} по `*Results` ответа."""
    items = _results(result)
    errors = [e for item in items for e in item.get("Errors") or []]
    warnings = [w for item in items for w in item.get("Warnings") or []]
    return {
        "succeeded": sum(1 for item in items if not item.get("Errors")),
        "failed": sum(1 for item in items if item.get("Errors")),
        "ids": [item["Id"] for item in items if "Id" in item and not item.get("Errors")],
        "errors": errors,
        "warnings": warnings,
    }


def _render_mutation(title: str) -> Callable[[dict], None]:
    def render(data: dict) -> None:
        mark = "[green]✓[/green]" if not data["failed"] else "[yellow]![/yellow]"
        ids = f" Id: {', '.join(map(str, data['ids']))}" if data["ids"] else ""
        output.human.echo_markup(
            f"{mark} {escape(title)}: успешно {data['succeeded']}, ошибок {data['failed']}, "
            f"предупреждений {len(data['warnings'])}.{escape(ids)}"
        )
        for e in data["errors"][:10]:
            output.human.echo_markup(f"  [red]⨯[/red] {escape(_problem(e))}")
        for w in data["warnings"][:5]:
            output.human.echo_markup(f"  [yellow]![/yellow] {escape(_problem(w))}")

    return render


def _problem(item: dict) -> str:
    detail = f" — {item['Details']}" if item.get("Details") else ""
    return f"[{item.get('Code')}] {item.get('Message')}{detail}"


def mutate(
    ctx: typer.Context,
    *,
    title: str,
    service: str,
    method: str,
    params: dict,
    confirm: bool,
    call: Callable[[], Coroutine[Any, Any, dict]] | None = None,
) -> None:
    """Изменение в кабинете: --dry-run показывает запрос; иначе подтверждение → вызов → итог.

    `call` — если нужен не прямой `service.method(params)`, а метод клиента с логикой
    (например, пересчёт рублей); по умолчанию — `DirectClient.call(service, method, params)`.
    Поэлементные ошибки API (`Errors` в `*Results`) — не сбой вызова: отчёт выводится целиком,
    а код выхода 5 (PROVIDER_ERROR) говорит, что часть объектов отклонена.
    """
    request = {"service": service, "method": method, "params": params}
    if output.is_dry_run(ctx):

        def render(d: dict) -> None:
            output.human.echo(f"[dry-run] {d['title']}: {service}.{method}")
            output.human.console.print_json(data=params)

        output.emit_success(ctx, {"dry_run": True, "title": title, **request}, render_human=render)
        return
    output.require_confirmation(ctx, f"{title} ({service}.{method})", confirm)
    result = services.run(call() if call else services.direct(ctx.obj).call(service, method, params))
    summary = summarize(result)
    problem = None
    if summary["failed"]:
        total = summary["failed"] + summary["succeeded"]
        problem = CliError(
            "PROVIDER_ERROR",
            f"Директ отклонил {summary['failed']} из {total} объектов ({service}.{method}).",
            action="Смотрите `errors` — коды и тексты ошибок по каждому объекту.",
            exit_code=5,
        )
    output.emit_report(ctx, {**request, **summary, "result": result}, _render_mutation(title), problem)
