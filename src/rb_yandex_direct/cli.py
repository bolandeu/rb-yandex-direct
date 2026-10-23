"""The root Typer app: global options, the command groups and the optional commands a generated package has, wired
together, and the console-script entry point.
"""

from __future__ import annotations

import typer
from typer import rich_utils

from . import output
from .commands import auth, doctor
from .commands.groups import GROUPS, TOP_LEVEL
from .core.version import DEV_VERSION, cli_name, installed_version, optional_module, package_summary

_PACKAGE_NAME = __name__.split(".")[0]
# Optional parts (copier questions, dropped by _exclude): each one ships a module that registers its
# commands and global options. Probed at runtime, so this file needs no template logic.
PARTS = ("project", "skill", "describe", "db")

# Заголовки справки Typer — по-русски. «Usage:» и «Show this message and exit.»
# зашиты во встроенный в Typer Click и остаются как есть.
rich_utils.ARGUMENTS_PANEL_TITLE = "Аргументы"
rich_utils.OPTIONS_PANEL_TITLE = "Параметры"
rich_utils.DEFAULT_STRING = "[по умолчанию: {}]"
rich_utils.REQUIRED_LONG_STRING = "[обязательный]"

# Голый `yd` — точка входа для людей и агентов: имя, версия, описание и все команды
# с первой строкой docstring. Без `no_args_is_help` (он выходит с кодом 2) —
# main_options() печатает справку и выходит с 0.
app = typer.Typer(
    cls=output.RootGroup,  # a usage error under --json is the error envelope
    add_completion=False,
    help=f"{cli_name()} {installed_version() or DEV_VERSION} — {package_summary() or 'Яндекс.Директ API'}",
)

app.add_typer(auth.app, name="auth")  # `auth status` in every CLI; login/logout only with credentials
app.command(name="doctor")(doctor.doctor)
for part in PARTS:
    if module := optional_module(f"{_PACKAGE_NAME}.commands.{part}"):
        module.register(app)

for _name, _group in GROUPS.items():
    app.add_typer(_group, name=_name)
for _name, _command in TOP_LEVEL.items():
    app.command(name=_name)(_command)


def _version_callback(value: bool) -> None:
    if not value:
        return
    typer.echo(installed_version() or DEV_VERSION)
    raise typer.Exit()


@app.callback(invoke_without_command=True)
def main_options(
    ctx: typer.Context,
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
) -> None:
    ctx.ensure_object(dict)  # a part's global option (--project) may have put its value here already
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
