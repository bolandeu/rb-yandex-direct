"""The `doctor` command: checks of this CLI's own setup, one line per check."""

from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import deps, services
from ..core.auth import store
from ..core.errors import CliError
from ..core.version import DEV_VERSION, cli_name, installed_version, optional_module

_PACKAGE_NAME = __name__.split(".")[0]


def _auth_check() -> dict:
    try:
        source = store.source()
        detail = source or f"токен не найден — {cli_name()} auth login"
        if source == "keychain":
            bag = store.stored()
            exp = store.expires_at(bag)
            if exp:
                detail += f", до {exp.date()}, автообновление: {'да' if store.can_refresh(bag) else 'нет'}"
        return {"name": "auth", "ok": source is not None, "detail": detail}
    except CliError as exc:
        return {"name": "auth", "ok": False, "detail": exc.message}


@output.guard
def doctor(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Диагностика: версия CLI, проект, конфиг, совместимость версий, токен, кабинет по умолчанию.

    Сетевых запросов не делает (живая проверка токена — `auth status --check`).
    Всегда завершается с кодом 0 — результат в самом отчёте.
    --json: {"ok": true, "healthy": bool, "checks": [{name, ok, detail}]}.

    Example: {cli} doctor --json
    """
    checks: list[dict] = [{"name": "python", "ok": True}]
    checks.append({"name": "cli_version", "ok": True, "detail": installed_version() or DEV_VERSION})

    if project := optional_module(f"{_PACKAGE_NAME}.commands.project"):  # include_project=false drops it
        checks.extend(project.doctor_checks(ctx))

    checks.append(_auth_check())
    start = Path(ctx.obj.get("project") or Path.cwd())
    root = services.find_project_root(start)
    try:
        conn = services.connection({**ctx.obj, "project": str(root) if root else ctx.obj.get("project")})
        where = "песочница" if conn["sandbox"] else "боевой API"
        checks.append({"name": "login", "ok": True, "detail": f"{conn['client_login'] or 'свой кабинет'}, {where}"})
    except Exception as exc:  # битый конфиг уже показан проверкой config
        checks.append({"name": "login", "ok": False, "detail": getattr(exc, "message", str(exc))})
    managed = services.managed_logins()
    checks.append({"name": "managed_logins", "ok": True, "detail": ", ".join(managed) or "не заданы"})
    checks.extend(deps.doctor_checks())  # [[tool.rb.external]] in pyproject.toml
    if db := optional_module(f"{_PACKAGE_NAME}.core.db"):  # include_db=false drops it at generation time
        checks.extend(db.doctor_checks())

    all_ok = all(check["ok"] for check in checks)
    output.emit_success(
        ctx, {"healthy": all_ok, "checks": checks}, render_human=lambda data: output.human.render_doctor(data["checks"])
    )
