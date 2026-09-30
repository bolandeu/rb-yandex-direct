from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import services


@output.guard
def init(
    ctx: typer.Context,
    name: str | None = typer.Option(None, "--name", help="Имя проекта (по умолчанию — имя папки)."),
    force: bool = typer.Option(False, "--force", help="Перезаписать конфиг уже созданного проекта."),
    login: str | None = typer.Option(
        None, "--client-login", help="Client-Login кабинета клиента: команды в этой папке пойдут в него."
    ),
    sandbox: bool = typer.Option(False, "--sandbox", help="Работать в песочнице API по умолчанию."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Создать проект клиента: .{cli}/config.toml в текущей папке (или --project).

    В проекте задаётся кабинет по умолчанию: `--login` и YANDEX_DIRECT_LOGIN важнее него.
    Проект необязателен — без него команды работают со своим кабинетом.

    Example: {cli} init --name shop --client-login shop@yandex.ru
    """
    target = Path(ctx.obj.get("project") or Path.cwd()).resolve()

    if not force and services.find_project_root(target) == target:
        output.vecho(ctx, f"Найден конфиг: {services.config_path(target)}")
        config = services.load_config(target)
        output.emit_success(
            ctx,
            {"project": config.name, "path": str(target), "already_initialized": True},
            render_human=lambda data: output.human.echo(f"Проект уже создан в {data['path']} (--force — пересоздать)."),
        )
        return

    project_name = name or target.name
    config = services.init_project(target, project_name, login=login, sandbox=sandbox)
    output.emit_success(
        ctx,
        {"project": config.name, "path": str(target), "login": login, "sandbox": sandbox, "already_initialized": False},
        render_human=lambda data: output.human.key_values(
            f"Проект создан в {data['path']}", {"имя": data["project"], "кабинет": data["login"] or "свой"}
        ),
    )
