"""The `describe` command: the machine-readable description (OpenCLI document) of this CLI for agents."""

from __future__ import annotations

import json

import typer

from .. import output
from ..core import opencli


@output.guard
def describe(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Print this CLI's machine-readable contract: an OpenCLI document (opencli.org).

    Commands, options, arguments, exit codes, plus `x-rb-*` metadata: env vars,
    tables, v1 views, data files, external programs. With --json it is the bare
    document on one line (no {"ok": ...} envelope); without, the same indented.

    Example: {cli} describe --json
    """
    document = opencli.document(ctx.find_root().command)
    typer.echo(json.dumps(document, ensure_ascii=False, indent=None if ctx.obj.get("json") else 2))


def register(root: typer.Typer) -> None:
    """Add `describe` to the CLI's root (the describe part, copier's include_describe)."""
    root.command(name="describe")(describe)
