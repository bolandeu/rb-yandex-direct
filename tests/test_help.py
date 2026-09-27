"""The --help contract: every command's help is complete, and any change to it shows up in review.

Help text is rendered from command docstrings and `click.option(help=...)` —
it's the documentation agents and humans read, so it's tested like an API
(standard §7, adapted from the cli-generator template for Click):

- contract tests: every command (walked from the Click registry, so a new
  command is covered automatically) has a docstring with an
  `Example: rb-yandex-direct <command> ...` line, every option has non-empty
  help, every group has a description;
- snapshots: `<command> --help` is stored in tests/snapshots/help/<command>.txt
  (syrupy). A changed help text fails until the snapshot is refreshed with
  `uv run pytest --snapshot-update`, which puts the new text in the diff.
  A new command fails until its snapshot exists; a removed one leaves an
  orphan file that fails too.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import click
import pytest
from click.testing import CliRunner
from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode

from rb_yandex_direct.cli import cli

CLI = "rb-yandex-direct"
SNAPSHOT_DIR = Path(__file__).parent / "snapshots" / "help"
# Fixed width and no colour so the rendering doesn't depend on the terminal running the tests.
HELP_ENV = {"COLUMNS": "100", "NO_COLOR": "1", "TERM": "dumb"}


def _walk(group: click.Group, prefix: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], click.Command]]:
    for name, command in group.commands.items():
        yield (*prefix, name), command
        if isinstance(command, click.Group):
            yield from _walk(command, (*prefix, name))


ALL = dict(_walk(cli))
COMMANDS = {path: c for path, c in ALL.items() if not isinstance(c, click.Group)}
GROUPS = {path: c for path, c in ALL.items() if isinstance(c, click.Group)}
HELP_PAGES = sorted([(), *ALL])


def _slug(path: tuple[str, ...]) -> str:
    return "-".join(path) or CLI


def _render_help(path: tuple[str, ...]) -> str:
    result = CliRunner().invoke(cli, [*path, "--help"], env=HELP_ENV, prog_name=CLI, obj={}, terminal_width=100)
    assert result.exit_code == 0, result.output
    # Trailing padding isn't content; keeping it out keeps the diffs readable.
    return "\n".join(line.rstrip() for line in result.output.splitlines()) + "\n"


class HelpSnapshot(SingleFileSnapshotExtension):
    """One plain-text file per help page: tests/snapshots/help/<command>.txt."""

    _write_mode = WriteMode.TEXT
    file_extension = "txt"

    @classmethod
    def dirname(cls, *, test_location) -> str:
        return str(SNAPSHOT_DIR)

    @classmethod
    def get_snapshot_name(cls, *, test_location, index=0) -> str:
        return str(index)


@pytest.mark.parametrize("path", HELP_PAGES, ids=_slug)
def test_help_snapshot(path: tuple[str, ...], snapshot) -> None:
    assert _render_help(path) == snapshot(extension_class=HelpSnapshot, name=_slug(path))


def test_no_orphan_help_snapshots() -> None:
    stored = {p.stem for p in SNAPSHOT_DIR.glob("*.txt")}
    expected = {_slug(path) for path in HELP_PAGES}
    assert stored <= expected, f"snapshots for commands that no longer exist: {sorted(stored - expected)}"


@pytest.mark.parametrize("path", sorted(COMMANDS), ids=_slug)
def test_command_docstring_has_summary_and_example(path: tuple[str, ...]) -> None:
    doc = COMMANDS[path].help or ""
    assert doc.strip(), f"`{_slug(path)}` has no docstring — it is the command's --help text"
    invocation = f"{CLI} {' '.join(path)}"
    examples = [line.strip() for line in doc.splitlines() if line.strip().startswith("Example:")]
    assert any(invocation in line for line in examples), (
        f"`{_slug(path)}` docstring needs an `Example: {invocation} ...` line"
    )


@pytest.mark.parametrize("path", sorted(COMMANDS), ids=_slug)
def test_every_option_has_help(path: tuple[str, ...]) -> None:
    # click.Argument has no help=; arguments are described in the docstring and its Example line.
    for param in COMMANDS[path].params:
        if isinstance(param, click.Option):
            assert (param.help or "").strip(), f"`{_slug(path)}` option `{param.opts[-1]}` has no help"


@pytest.mark.parametrize("path", sorted(GROUPS), ids=_slug)
def test_every_group_has_help(path: tuple[str, ...]) -> None:
    assert (GROUPS[path].help or "").strip(), f"group `{_slug(path)}` has no description"


@pytest.mark.parametrize("path", [(), *sorted(GROUPS)], ids=_slug)
def test_bare_group_prints_help_and_exits_0(path: tuple[str, ...]) -> None:
    result = CliRunner().invoke(cli, list(path), prog_name=CLI, obj={})
    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output
