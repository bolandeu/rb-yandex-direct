"""`yd minus-sets` — общие наборы минус-фраз (сервис NegativeKeywordSharedSets)."""

from __future__ import annotations

from typing import Any

import typer

from .. import output
from ..core import services
from ..core.errors import InvalidArguments
from ._common import emit_list, mutate, read_lines
from ._targeting import IdFilter, IdsArgument, ids_mutation

app = output.group("Общие наборы минус-фраз: подключаются к группам и кампаниям вместо копий списков.")

WordsOption = typer.Option(None, "--word", "-w", help="Минус-фраза (повторяемая).")
FromFileOption = typer.Option(None, "--from-file", help="Файл с минус-фразами, по одной в строке.")

COLUMNS = [
    ("Id", "Id"),
    ("Название", "Name"),
    ("Фраз", lambda s: len(s.get("NegativeKeywords") or [])),
    ("Подключён", "Associated"),
]


@app.command("list")
@output.guard
def list_sets(
    ctx: typer.Context,
    ids: list[int] = IdFilter,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Наборы минус-фраз: название, фразы, подключён ли к группам.

    --json: {"ok": true, "count": N, "sets": [{Id, Name, NegativeKeywords: [...], Associated}]}.

    Example: {cli} minus-sets list --json
    """
    items = services.run(
        services.direct(ctx.obj).list_negative_keyword_shared_sets(
            ids=ids or None, field_names=["Id", "Name", "NegativeKeywords", "Associated"]
        )
    )
    emit_list(ctx, "sets", items, COLUMNS, title="Наборы минус-фраз")


@app.command("add")
@output.guard
def add(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Название набора."),
    words: list[str] = WordsOption,
    from_file: str = FromFileOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать набор минус-фраз (фразы без минуса в начале, до 7 слов).

    Example: {cli} minus-sets add --name Общие -w бесплатно -w скачать --dry-run
    """
    phrases = read_lines(words, from_file)
    if not phrases:
        raise InvalidArguments("Укажите минус-фразы: --word или --from-file.")
    mutate(
        ctx,
        title=f"Создать набор «{name}» ({len(phrases)} фраз)",
        service="negativekeywordsharedsets",
        method="add",
        params={"NegativeKeywordSharedSets": [{"Name": name, "NegativeKeywords": phrases}]},
        confirm=confirm,
    )


@app.command("update")
@output.guard
def update(
    ctx: typer.Context,
    set_id: int = typer.Argument(..., help="Id набора."),
    name: str = typer.Option(None, "--name", help="Новое название."),
    words: list[str] = WordsOption,
    from_file: str = FromFileOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Переименовать набор и/или заменить его фразы: переданный список целиком заменяет текущий.

    Example: {cli} minus-sets update 6001 --from-file minus.txt --dry-run
    """
    item: dict[str, Any] = {"Id": set_id}
    if name:
        item["Name"] = name
    phrases = read_lines(words, from_file)
    if phrases:
        item["NegativeKeywords"] = phrases
    if len(item) == 1:
        raise InvalidArguments("Нечего менять: укажите --name, --word или --from-file.")
    mutate(
        ctx,
        title=f"Изменить набор {set_id}",
        service="negativekeywordsharedsets",
        method="update",
        params={"NegativeKeywordSharedSets": [item]},
        confirm=confirm,
    )


@app.command("delete")
@output.guard
def delete(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить наборы минус-фраз (подключённые к группам не удаляются — API вернёт ошибку).

    Example: {cli} minus-sets delete 6001 --dry-run
    """
    ids_mutation(
        ctx,
        service="negativekeywordsharedsets",
        method="delete",
        verb="Удалить",
        noun="наборы минус-фраз",
        ids=ids,
        confirm=confirm,
    )
