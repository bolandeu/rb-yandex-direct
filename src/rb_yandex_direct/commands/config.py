from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import services
from ..core.errors import InvalidArguments
from ..core.models import ProjectConfig

app = output.group("Настройки проекта (.yd/config.toml): кабинет по умолчанию, песочница, min_version.")


@app.command("list")
@output.guard
def list_config(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Все настройки проекта.

    Example: {cli} config list --json
    """
    start = Path(ctx.obj.get("project") or Path.cwd())
    root = services.require_project_root(start)
    config = services.load_config(root)
    data = config.model_dump()
    output.emit_success(ctx, data, render_human=lambda d: output.human.key_values("Настройки", d))


@app.command("get")
@output.guard
def get_config(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Ключ через точку, например direct.login (см. `config list`)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Одна настройка проекта.

    Example: {cli} config get cli.min_version
    """
    start = Path(ctx.obj.get("project") or Path.cwd())
    root = services.require_project_root(start)
    value: object = services.load_config(root).model_dump()
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise InvalidArguments(f"Неизвестный ключ настроек '{key}'.")
        value = value[part]
    output.emit_success(
        ctx, {"key": key, "value": value}, render_human=lambda d: output.human.echo(f"{d['key']} = {d['value']}")
    )


@app.command("set")
@output.guard
def set_config(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Ключ через точку, например direct.login (см. `config list`)."),
    value: str = typer.Argument(..., help="Новое значение (true/false — для direct.sandbox)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить одну настройку проекта (не секрет: токены — только `auth login`).

    Example: {cli} config set direct.login shop@yandex.ru
    """
    start = Path(ctx.obj.get("project") or Path.cwd())
    root = services.require_project_root(start)
    data = services.load_config(root).model_dump()
    parts = key.split(".")
    target = data
    for part in parts[:-1]:
        if not isinstance(target, dict) or part not in target:
            raise InvalidArguments(f"Неизвестный ключ настроек '{key}'.")
        target = target[part]
    if not isinstance(target, dict) or parts[-1] not in target:
        raise InvalidArguments(f"Неизвестный ключ настроек '{key}'.")
    target[parts[-1]] = value
    services.save_config(root, ProjectConfig.model_validate(data))
    output.emit_success(
        ctx, {"key": key, "value": value}, render_human=lambda d: output.human.echo(f"{d['key']} = {d['value']}")
    )
