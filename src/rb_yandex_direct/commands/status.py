"""The `status` command: the state of the current project."""

from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import services


@output.guard
def status(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Проект в текущей папке: имя, путь, кабинет по умолчанию, песочница.

    Нет проекта — PROJECT_NOT_INITIALIZED (exit 4); создать — `{cli} init`.

    Example: {cli} status --json
    """
    start = Path(ctx.obj.get("project") or Path.cwd())
    root = services.require_project_root(start)
    output.vecho(ctx, f"Корень проекта: {root}")
    config = services.load_config(root)
    output.emit_success(
        ctx,
        {"project": config.name, "path": str(root), "login": config.direct.login, "sandbox": config.direct.sandbox},
        render_human=lambda data: output.human.key_values(
            "Проект",
            {
                "имя": data["project"],
                "путь": data["path"],
                "кабинет": data["login"] or "свой",
                "песочница": data["sandbox"],
            },
        ),
    )
