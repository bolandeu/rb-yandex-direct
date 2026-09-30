from __future__ import annotations

from importlib import resources

import typer
from typer import rich_utils

from . import output
from .commands import auth, doctor, init, skill, status
from .commands import config as config_cmd
from .commands.groups import GROUPS, TOP_LEVEL
from .core.version import DEV_VERSION, cli_name, installed_version, package_summary

_PACKAGE_NAME = __name__.split(".")[0]

# Заголовки справки Typer — по-русски. «Usage:» и «Show this message and exit.»
# зашиты во встроенный в Typer Click и остаются как есть.
rich_utils.ARGUMENTS_PANEL_TITLE = "Аргументы"
rich_utils.OPTIONS_PANEL_TITLE = "Параметры"
rich_utils.COMMANDS_PANEL_TITLE = "Команды"
rich_utils.DEFAULT_STRING = "[по умолчанию: {}]"
rich_utils.REQUIRED_LONG_STRING = "[обязательный]"

# Голый `yd` — точка входа для людей и агентов: имя, версия, описание и все команды
# с первой строкой docstring. Без `no_args_is_help` (он выходит с кодом 2) —
# main_options() печатает справку и выходит с 0.
app = typer.Typer(
    add_completion=False,
    help=f"{cli_name()} {installed_version() or DEV_VERSION} — {package_summary() or 'Яндекс.Директ API'}",
)

app.add_typer(config_cmd.app, name="config")
app.add_typer(auth.app, name="auth")
app.add_typer(skill.app, name="skill")

app.command(name="init")(init.init)
app.command(name="status")(status.status)
app.command(name="doctor")(doctor.doctor)

for _name, _group in GROUPS.items():
    app.add_typer(_group, name=_name)
for _name, _command in TOP_LEVEL.items():
    app.command(name=_name)(_command)


def _version_callback(value: bool) -> None:
    if not value:
        return
    typer.echo(installed_version() or DEV_VERSION)
    raise typer.Exit()


def _ai_callback(value: bool) -> None:
    """Напечатать памятку для AI-агентов (SKILL.md из пакета) в stdout.

    Для агента, который может запускать CLI, но не читает файлы с диска.
    """
    if not value:
        return
    content = resources.files(f"{_PACKAGE_NAME}.data").joinpath("SKILL.md").read_text(encoding="utf-8")
    typer.echo(content)
    raise typer.Exit()


@app.callback(invoke_without_command=True)
def main_options(
    ctx: typer.Context,
    project: str = typer.Option(None, "--project", help="Путь к корню проекта (иначе ищется вверх от текущей папки)."),
    login: str = typer.Option(
        None,
        "--login",
        help="Client-Login кабинета (агентство/представитель); часть логина из YANDEX_DIRECT_MANAGED_LOGINS тоже годится.",
    ),
    sandbox: bool = typer.Option(None, "--sandbox/--prod", help="Песочница или боевой API для этого вызова."),
    json_output: bool = typer.Option(False, "--json", help="Машиночитаемый вывод: JSON в stdout."),
    quiet: bool = typer.Option(False, "--quiet", help="Не печатать ничего, кроме данных."),
    verbose: bool = typer.Option(False, "--verbose", help="Подробная диагностика в stderr (в т.ч. Units и RequestId)."),
    non_interactive: bool = typer.Option(
        False, "--non-interactive", help="Никогда не спрашивать; при нехватке данных — ошибка."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Показать запрос к API, ничего не меняя."),
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Показать версию и выйти."
    ),
    ai: bool = typer.Option(
        False,
        "--ai",
        callback=_ai_callback,
        is_eager=True,
        help="Напечатать памятку для AI-агентов (SKILL.md) и выйти.",
    ),
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["project"] = project
    ctx.obj["login"] = login
    ctx.obj["sandbox"] = sandbox
    ctx.obj["json"] = json_output
    ctx.obj["quiet"] = quiet
    ctx.obj["verbose"] = verbose
    ctx.obj["non_interactive"] = non_interactive
    ctx.obj["dry_run"] = dry_run
    output.configure_logging(verbose)
    output.help_if_no_command(ctx)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
