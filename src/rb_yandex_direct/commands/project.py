"""The project part (copier's include_project): `init`, `status`, `config`, the global --project and its doctor checks."""

from __future__ import annotations

from pathlib import Path

import typer
from typer.core import TyperOption

from .. import output
from ..core import services
from ..core.errors import CliTooOld
from . import config, init, status


def _remember_project(ctx: typer.Context, _param: object, value: str | None) -> None:
    ctx.ensure_object(dict)["project"] = value


def register(app: typer.Typer) -> None:
    """Add the project commands and the global --project to the CLI's root."""
    app.add_typer(config.app, name="config")
    app.command(name="init")(init.init)
    app.command(name="status")(status.status)
    output.RootGroup.part_options.append(
        TyperOption(
            param_decls=["--project"],
            metavar="TEXT",
            help="Path to the project root.",
            expose_value=False,
            callback=_remember_project,
        )
    )


def doctor_checks(ctx: typer.Context) -> list[dict]:
    """The `project`, `config` and `cli_compat` checks of `doctor`; outside a project only `project`, and it is ok."""
    start = Path(ctx.obj.get("project") or Path.cwd())
    output.vecho(ctx, f"Searching for a project root starting at: {start}")
    root = services.find_project_root(start)
    if root is None:
        return [{"name": "project", "ok": True, "detail": "doctor runs outside a project"}]
    checks: list[dict] = [{"name": "project", "ok": True, "detail": str(root)}]
    try:
        config = services.load_config(root, check_compat=False)
    except Exception as exc:
        checks.append({"name": "config", "ok": False, "detail": str(exc)})
        return checks
    checks.append({"name": "config", "ok": True})
    try:
        services.check_cli_compat(config)
        checks.append({"name": "cli_compat", "ok": True, "detail": f"project requires >= {config.cli.min_version}"})
    except CliTooOld as exc:
        checks.append({"name": "cli_compat", "ok": False, "detail": exc.message})
    return checks
