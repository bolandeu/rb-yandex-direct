"""Общее для команд v4 Live: чтение, изменения с --dry-run/--confirm, разбор поэлементных ошибок.

Семантика та же, что у `_common.mutate` для v5; отличается форма ответа v4
(`data` вместо `result`, ошибки объектов — `Errors[{FaultCode, FaultString, FaultDetail}]`)
и финансовые поля: у финансовых методов --dry-run показывает тело с `finance_token: "***"`
и следующим номером операции, не расходуя его.
"""

from __future__ import annotations

import time
from typing import Any

import typer
from rich.markup import escape

from .. import output
from ..core import live as core_live
from ..core import services
from ..core.errors import CliError

# Пауза между проверками готовности асинхронного отчёта (wordstat/forecast run); тесты ставят 0.
POLL_INTERVAL = 2.0

CURRENCIES = ["RUB", "BYN", "KZT", "TRY", "UAH", "USD", "EUR", "CHF"]
CurrencyOption = typer.Option("RUB", "--currency", help=f"Валюта сумм: {', '.join(CURRENCIES)}.")


def call(ctx: typer.Context, method: str, param: Any = None) -> Any:
    """Читающий вызов v4 Live: вернуть `data`."""
    return services.run(core_live.live(ctx.obj).call(method, param))


def _item_errors(data: Any) -> tuple[int, int, list[dict]]:
    """(успешно, с ошибками, ошибки) по `ActionsResult[].Errors` или верхнему `Errors` ответа."""
    if not isinstance(data, dict):
        return 1, 0, []
    items = data.get("ActionsResult")
    if not isinstance(items, list):
        items = [data] if "Errors" in data else []
    errors = [e for item in items if isinstance(item, dict) for e in item.get("Errors") or []]
    failed = sum(1 for item in items if isinstance(item, dict) and item.get("Errors"))
    return max(len(items) - failed, 0 if items else 1), failed, errors


def _render(title: str) -> Any:
    def render(data: dict) -> None:
        mark = "[green]✓[/green]" if not data["failed"] else "[yellow]![/yellow]"
        output.human.echo_markup(f"{mark} {escape(title)}: успешно {data['succeeded']}, ошибок {data['failed']}.")
        for e in data["errors"][:10]:
            detail = f" — {e['FaultDetail']}" if e.get("FaultDetail") else ""
            output.human.echo(f"  ⨯ [{e.get('FaultCode')}] {e.get('FaultString')}{detail}")
        if data["data"] is not None and not isinstance(data["data"], dict):
            output.human.echo(f"  ответ: {data['data']}")

    return render


def mutate(
    ctx: typer.Context,
    *,
    title: str,
    method: str,
    param: Any,
    confirm: bool,
    finance: bool = False,
    finance_action: str = "",
) -> None:
    """Изменение через v4 Live: --dry-run → тело запроса; иначе подтверждение → вызов → итог.

    `finance` — метод требует финансовый токен (`finance_action` — операция AccountManagement,
    входит в токен). Номер операции расходуется только при настоящем вызове.
    """
    client = core_live.live(ctx.obj)
    if output.is_dry_run(ctx):
        body = client.body(method, param)
        if finance:
            body |= {"finance_token": "***", "operation_num": core_live.next_operation_num()}

        def render(d: dict) -> None:
            output.human.echo(f"[dry-run] {d['title']}: v4 {method}")
            output.human.console.print_json(data=d["body"])

        output.emit_success(ctx, {"dry_run": True, "title": title, "method": method, "body": body}, render)
        return
    output.require_confirmation(ctx, f"{title} (v4 {method})", confirm)
    fin = core_live.finance(method, finance_action) if finance else None
    data = services.run(client.call(method, param, finance=fin))
    succeeded, failed, errors = _item_errors(data)
    payload = {"method": method, "succeeded": succeeded, "failed": failed, "errors": errors, "data": data}
    if fin is not None:
        payload["operation_num"] = fin.operation_num
    problem = None
    if failed:
        problem = CliError(
            "PROVIDER_ERROR",
            f"Директ отклонил {failed} из {succeeded + failed} объектов (v4 {method}).",
            action="Смотрите `errors` — коды и тексты ошибок по каждому объекту.",
            exit_code=5,
        )
    output.emit_report(ctx, payload, _render(title), problem)


def parse_pairs(values: list[str], option: str) -> list[tuple[int, float]]:
    """`ID=СУММА` (повторяемая опция) → [(id, сумма)]; сумма > 0, не больше двух знаков после запятой."""
    from ..core.errors import InvalidArguments

    out: list[tuple[int, float]] = []
    for value in values:
        key, sep, amount = value.partition("=")
        try:
            ident, total = int(key), float(amount)
        except ValueError:
            ident, total = 0, 0.0
        if not sep or ident <= 0 or total <= 0 or round(total, 2) != total:
            raise InvalidArguments(f"{option}: ожидается ID=СУММА (сумма > 0, до копеек), получено {value!r}.")
        out.append((ident, total))
    if not out:
        raise InvalidArguments(f"Укажите хотя бы один {option} ID=СУММА.")
    return out


def wait_ready(ctx: typer.Context, list_method: str, id_key: str, status_key: str, ident: int, timeout: float) -> None:
    """Ждать статуса Done у отчёта; Failed или таймаут — PROVIDER_ERROR."""
    deadline = time.monotonic() + timeout
    while True:
        items = call(ctx, list_method) or []
        status = next((i.get(status_key) for i in items if i.get(id_key) == ident), None)
        if status == "Done":
            return
        if status == "Failed" or time.monotonic() >= deadline:
            raise CliError(
                "PROVIDER_ERROR",
                f"Отчёт {ident}: {'не удалось сформировать' if status == 'Failed' else f'не готов за {timeout:g} с'}.",
                action="Повторите позже или проверьте статус командой list.",
                exit_code=5,
            )
        time.sleep(POLL_INTERVAL)
