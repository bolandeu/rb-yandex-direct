from __future__ import annotations

from importlib import resources
from pathlib import Path

import typer

from .. import output
from ..core.version import cli_name

app = output.group("Памятка yd для AI-агентов (SKILL.md из пакета).")

_PACKAGE_NAME = __name__.split(".")[0]
_SKILL_NAME = cli_name()  # matches `name:` in the bundled SKILL.md

# Where each AI tool looks for personal (user-level) and project-level skills.
_TOOL_TARGETS = {
    "claude-code": {
        "user": Path.home() / ".claude" / "skills" / _SKILL_NAME,
        "project": Path(".claude") / "skills" / _SKILL_NAME,
    },
    "agents": {
        "user": Path.home() / ".agents" / "skills" / _SKILL_NAME,
        "project": Path(".agents") / "skills" / _SKILL_NAME,
    },
}


def _skill_content() -> str:
    return resources.files(f"{_PACKAGE_NAME}.data").joinpath("SKILL.md").read_text(encoding="utf-8")


@app.command("install")
@output.guard
def install(
    ctx: typer.Context,
    tool: str = typer.Option(
        "claude-code",
        "--tool",
        help=f"Куда ставить: {', '.join(_TOOL_TARGETS)}.",
    ),
    project: bool = typer.Option(False, "--project", help="В текущий проект, а не в папку пользователя."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Скопировать SKILL.md из пакета в папку скиллов AI-инструмента.

    Example: {cli} skill install --tool claude-code
    """
    from ..core.errors import InvalidArguments

    if tool not in _TOOL_TARGETS:
        raise InvalidArguments(f"Неизвестный --tool '{tool}'. Варианты: {', '.join(_TOOL_TARGETS)}.")

    scope = "project" if project else "user"
    target_dir = _TOOL_TARGETS[tool][scope]
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "SKILL.md"
    target_path.write_text(_skill_content(), encoding="utf-8")

    output.emit_success(
        ctx,
        {"tool": tool, "scope": scope, "path": str(target_path.resolve())},
        render_human=lambda d: output.human.echo(f"Памятка для '{d['tool']}' ({d['scope']}): {d['path']}"),
    )
