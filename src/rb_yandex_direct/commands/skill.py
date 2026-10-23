"""The `skill` command group: print this CLI's agent skill or install it for AI tools."""

from __future__ import annotations

from pathlib import Path

import typer
from typer.core import TyperOption

from .. import output
from ..core import skills

app = output.group("Памятка yd для AI-агентов (SKILL.md из пакета).")


def _print_skill(ctx: typer.Context, _param: object, value: bool) -> None:
    """Print the bundled agent skill doc to stdout.

    For agents that can execute this CLI but cannot read files from disk
    (e.g. a sandboxed shell with no access to a SKILL.md on the filesystem),
    this is the fallback way to get full usage guidance.
    """
    if not value:
        return
    typer.echo(skills.conventions().text)
    raise typer.Exit()


def register(root: typer.Typer) -> None:
    """Add the `skill` group and the global --ai to the CLI's root (the package skill part, copier's include_skill)."""
    root.add_typer(app, name="skill")
    output.RootGroup.part_options.append(
        TyperOption(
            param_decls=["--ai"],
            is_flag=True,
            default=False,
            is_eager=True,
            expose_value=False,
            callback=_print_skill,
            help="Print AI-oriented usage documentation (the bundled skill doc) and exit.",
        )
    )


# Where each AI tool looks for personal (user-level) and project-level skills.
_TOOL_TARGETS = {
    "claude-code": {
        "user": Path.home() / ".claude" / "skills",
        "project": Path(".claude") / "skills",
    },
    "agents": {
        "user": Path.home() / ".agents" / "skills",
        "project": Path(".agents") / "skills",
    },
}


def _chosen(wanted: str | None) -> list[skills.Skill]:
    """Every bundled skill, or the one `--skill` names (by its name or its short name)."""
    from ..core.errors import InvalidArguments

    bundled = skills.bundled()
    if wanted is None:
        return bundled
    found = [s for s in bundled if wanted in (s.name, s.short_name)]
    if not found:
        raise InvalidArguments(f"Unknown --skill '{wanted}'. Bundled skills: {', '.join(s.name for s in bundled)}.")
    return found


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
    skill: str = typer.Option(
        None, "--skill", help="Install only this bundled skill (see `skill list`); by default all."
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Copy this CLI's bundled skills into an AI tool's skill directory.

    The conventions skill and every extra skill the package ships, each into its own directory.

    Example: {cli} skill install --tool claude-code
    """
    from ..core.errors import InvalidArguments

    if tool not in _TOOL_TARGETS:
        raise InvalidArguments(f"Неизвестный --tool '{tool}'. Варианты: {', '.join(_TOOL_TARGETS)}.")

    chosen = _chosen(skill)
    scope = "project" if project else "user"
    paths = []
    for item in chosen:
        target_dir = _TOOL_TARGETS[tool][scope] / item.name
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "SKILL.md"
        target_path.write_text(item.text)
        paths.append(str(target_path.resolve()))

    data = {"tool": tool, "scope": scope, "path": paths[0]}
    if len(paths) > 1:
        data["paths"] = paths
    output.emit_success(
        ctx,
        data,
        render_human=lambda d: output.human.echo(
            f"Installed skill for '{d['tool']}' ({d['scope']}) at " + "\n  ".join(d.get("paths", [d["path"]]))
        ),
    )


@app.command("list")
@output.guard
def list_skills(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """List the agent skills this CLI bundles: name and description.

    Example: {cli} skill list
    """
    found = [{"name": s.name, "description": s.description} for s in skills.bundled()]
    output.emit_success(
        ctx,
        {"skills": found},
        render_human=lambda d: output.human.echo("\n".join(f"{s['name']}: {s['description']}" for s in d["skills"])),
    )
