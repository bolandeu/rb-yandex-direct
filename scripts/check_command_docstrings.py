#!/usr/bin/env python3
"""Block a command's logic from changing without its docstring changing too.

Every command function's docstring is what Typer renders as `--help` —
the documentation agents and humans read (the Standard, Commands). A command is a function in `src/*/commands/*.py` (or the globs in
`[tool.cli-generator] commands` in pyproject.toml) decorated with
`output.guard` or registered with `@<app>.command(...)`; "logic" is its signature plus its body minus the
docstring. Antagor runs it as one of the project's `checks`
on the working tree against HEAD; exit 1 on a stale docstring. A
behaviour-neutral edit (lint/type fix) keeps the body AST-identical with
`# noqa` / `# ty: ignore[...]` comments.
"""

from __future__ import annotations

import ast
import fnmatch
import functools
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_COMMAND_FILES = ("src/*/commands/*.py",)

@functools.cache
def command_globs() -> tuple[str, ...]:
    """Where commands live: `[tool.cli-generator] commands` in pyproject.toml (a glob or a list), else the default.

    Relative to the repo root (main() chdirs there first).
    """
    try:
        import tomllib
    except ModuleNotFoundError:  # the hook's python3 is older than 3.11
        return DEFAULT_COMMAND_FILES
    try:
        config = tomllib.loads(Path("pyproject.toml").read_text()).get("tool", {}).get("cli-generator", {})
    except OSError, tomllib.TOMLDecodeError:
        return DEFAULT_COMMAND_FILES
    value = config.get("commands", DEFAULT_COMMAND_FILES)
    return (value,) if isinstance(value, str) else tuple(value)

def is_command_file(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in command_globs())

def _git(*args: str) -> str | None:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else None

def _is_command_decorator(decorator: ast.expr) -> bool:
    """`@output.guard`, or a Typer registration: `@app.command`, `@app.command("name")`, `@group.command(...)`."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return ast.unparse(target).split(".")[-1] in ("guard", "command")

def _doc_assignments(tree: ast.Module) -> dict[str, str]:
    """`name.__doc__ = <expr>` at module level (e.g. an f-string help text) -> the expression's source."""
    assigned: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Attribute) and target.attr == "__doc__" and isinstance(target.value, ast.Name):
                assigned[target.value.id] = ast.unparse(node.value)
    return assigned

def _commands(source: str) -> dict[str, tuple[str | None, str]]:
    """Map command name -> (docstring, normalized signature + body excluding the docstring).

    The docstring is the literal one, or — when the module later sets
    `command.__doc__ = f"..."` — that expression's source, since that's what
    `--help` renders.
    """
    tree = ast.parse(source)
    assigned = _doc_assignments(tree)
    commands: dict[str, tuple[str | None, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not any(_is_command_decorator(dec) for dec in node.decorator_list):
            continue
        literal = ast.get_docstring(node)
        docstring = assigned.get(node.name, literal)
        body = node.body[1:] if literal is not None else node.body
        commands[node.name] = (docstring, "\n".join(ast.dump(part) for part in (node.args, *body)))
    return commands

def stale_commands(paths: list[str]) -> list[str]:
    """Commands in `paths` (repo-relative) whose logic differs from HEAD while their docstring doesn't."""
    stale: list[str] = []
    for path in paths:
        if not Path(path).is_file():
            continue
        new_source = Path(path).read_text()
        try:
            new = _commands(new_source)
            head_source = _git("show", f"HEAD:{path}")
            old = _commands(head_source) if head_source is not None else {}
        except SyntaxError:
            continue  # mid-edit; the next check sees the finished file
        for name, (doc, logic) in new.items():
            if not doc:
                stale.append(f"{path}: command `{name}` has no docstring — it is the command's --help text")
            elif name in old and logic != old[name][1] and doc == old[name][0]:
                stale.append(f"{path}: command `{name}` changed its logic, but its docstring (--help) did not")
    return stale

def _report(stale: list[str], footer: str) -> None:
    print("Command help is out of date:", file=sys.stderr)
    for item in stale:
        print(f"  - {item}", file=sys.stderr)
    print(
        "Update each docstring to describe the new behaviour (keep its `Example: {cli} ...` line valid), "
        "then refresh the help snapshots: uv run pytest --snapshot-update, and review tests/snapshots/help/.",
        file=sys.stderr,
    )
    print(footer, file=sys.stderr)

def _changed_command_files() -> list[str]:
    tracked = (_git("diff", "--name-only", "HEAD") or "").splitlines()
    untracked = (_git("ls-files", "--others", "--exclude-standard") or "").splitlines()
    return [p for p in tracked + untracked if is_command_file(p)]

def main(argv: list[str]) -> int:
    root = _git("rev-parse", "--show-toplevel")
    if root is None:
        return 0  # not a git checkout: nothing to compare against
    os.chdir(root.strip())

    stale = stale_commands(_changed_command_files())
    if stale:
        _report(
            stale,
            "A behaviour-neutral edit (lint/type fix) must keep the body AST-identical — use "
            "`# noqa` / `# ty: ignore[...]` comments.",
        )
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
