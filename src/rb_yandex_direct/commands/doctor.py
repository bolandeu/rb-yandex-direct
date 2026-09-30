from __future__ import annotations

from pathlib import Path

import typer

from .. import output
from ..core import deps, services
from ..core.auth import store
from ..core.errors import CliError, CliTooOld
from ..core.models import ProjectConfig
from ..core.version import DEV_VERSION, cli_name, installed_version


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

    start = Path(ctx.obj.get("project") or Path.cwd())
    output.vecho(ctx, f"Поиск корня проекта начиная с: {start}")
    root = services.find_project_root(start)
    # Проект необязателен: без него кабинет берётся из --login / YANDEX_DIRECT_LOGIN.
    checks.append({"name": "project", "ok": True, "detail": str(root) if root else "нет (необязателен)"})

    config: ProjectConfig | None = None
    if root is not None:
        try:
            config = services.load_config(root, check_compat=False)
            checks.append({"name": "config", "ok": True})
        except Exception as exc:
            checks.append({"name": "config", "ok": False, "detail": str(exc)})
    if config is not None:
        try:
            services.check_cli_compat(config)
            checks.append({"name": "cli_compat", "ok": True, "detail": f"проекту нужен >= {config.cli.min_version}"})
        except CliTooOld as exc:
            checks.append({"name": "cli_compat", "ok": False, "detail": exc.message})

    checks.append(_auth_check())
    try:
        conn = services.connection({**ctx.obj, "project": str(root) if root else ctx.obj.get("project")})
        where = "песочница" if conn["sandbox"] else "боевой API"
        checks.append({"name": "login", "ok": True, "detail": f"{conn['client_login'] or 'свой кабинет'}, {where}"})
    except Exception as exc:  # битый конфиг уже показан проверкой config
        checks.append({"name": "login", "ok": False, "detail": getattr(exc, "message", str(exc))})
    managed = services.managed_logins()
    checks.append({"name": "managed_logins", "ok": True, "detail": ", ".join(managed) or "не заданы"})
    checks.extend(deps.doctor_checks())  # [[tool.rb.external]] в pyproject.toml

    all_ok = all(check["ok"] for check in checks)
    output.emit_success(
        ctx, {"healthy": all_ok, "checks": checks}, render_human=lambda data: output.human.render_doctor(data["checks"])
    )
