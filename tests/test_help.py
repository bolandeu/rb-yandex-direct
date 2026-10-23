"""The --help contract: every command's help is complete, and any change to it shows up in review.

Help text is rendered from command docstrings and `typer.Option`/`Argument`
`help=` strings — it's the documentation agents and humans read, so it's
tested like an API:

- the help standard (the cli-generator Standard, Commands) on every command, walked from the app's
  registry so a new command is covered automatically: a one-line summary, one to three `Example:` lines that
  parse against the command tree, help on every parameter, no parameter help repeated in the description.
  A command not yet brought to the standard is listed in tests/help_allowlist.txt (one command path per line,
  `#` comments); a failing run prints the failing commands as lines ready to paste there. Every group has a
  description;
- snapshots: `<command> --help` is stored in tests/snapshots/help/<command>.txt
  (syrupy). A changed help text fails until the snapshot is refreshed with
  `uv run pytest --snapshot-update`, which puts the new text in the diff.
  A new command fails until its snapshot exists; a removed one leaves an
  orphan file that fails too.
"""

from __future__ import annotations

import inspect
import re
import shlex
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import typer
import typer.rich_utils
from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode
from typer.testing import CliRunner

from rb_yandex_direct import output
from rb_yandex_direct.cli import app

CLI = "yd"
SNAPSHOT_DIR = Path(__file__).parent / "snapshots" / "help"
ALLOWLIST = Path(__file__).parent / "help_allowlist.txt"
MAX_EXAMPLES = 3
EXAMPLE = "Example: "
RESULT = "-> "  # the line after an example: what it gives
# A docstring line that explains parameters: «mode: …», «`action`: …», «core, column: …», «first / last: …».
PARAM_NAMES = r"`?\w+`?(?:(?:, | / )`?\w+`?)*"
PARAM_LINE = re.compile(rf"^(?P<names>{PARAM_NAMES}): ")
# The explanation of another parameter inside a line, after the end of a sentence: «… is bad. good: a phrase …».
INLINE_PARAM = re.compile(rf"(?<=[.;]) (?P<names>{PARAM_NAMES}): ")
LIST_ITEM = re.compile(r"^(?:[-*]|\d+[.)]) ")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# Fixed width and no colour so the rendering doesn't depend on the terminal running the tests.
HELP_ENV = {"COLUMNS": "100", "NO_COLOR": "1", "TERM": "dumb"}


def _commands(group: typer.Typer, prefix: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Callable]]:
    for info in group.registered_commands:
        assert info.callback is not None
        name = info.name or getattr(info.callback, "__name__", "").replace("_", "-")
        yield (*prefix, name), info.callback
    for sub in group.registered_groups:
        assert sub.name is not None and sub.typer_instance is not None
        yield from _commands(sub.typer_instance, (*prefix, sub.name))


def _groups(group: typer.Typer, prefix: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], typer.Typer]]:
    for sub in group.registered_groups:
        assert sub.name is not None and sub.typer_instance is not None
        yield (*prefix, sub.name), sub.typer_instance
        yield from _groups(sub.typer_instance, (*prefix, sub.name))


COMMANDS = dict(_commands(app))
GROUPS = dict(_groups(app))
HELP_PAGES = sorted([*COMMANDS, *GROUPS])


@pytest.fixture(autouse=True)
def _plain_help(monkeypatch: pytest.MonkeyPatch) -> None:
    """Typer reads GITHUB_ACTIONS / FORCE_COLOR / PY_COLORS once, at import, and then forces terminal output (CI)."""
    monkeypatch.setattr(typer.rich_utils, "FORCE_TERMINAL", False)


def _slug(path: tuple[str, ...]) -> str:
    return "-".join(path)


def _render_help(path: tuple[str, ...]) -> str:
    result = CliRunner().invoke(app, [*path, "--help"], env=HELP_ENV, prog_name=CLI)
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


def test_help_is_the_same_in_ci(same_in_ci: Callable[[str], None]) -> None:
    same_in_ci("test_help_snapshot")


def test_no_orphan_help_snapshots() -> None:
    stored = {p.stem for p in SNAPSHOT_DIR.glob("*.txt")}
    expected = {_slug(path) for path in HELP_PAGES}
    assert stored <= expected, f"snapshots for commands that no longer exist: {sorted(stored - expected)}"


@pytest.mark.parametrize("path", sorted(COMMANDS), ids=_slug)
def test_every_command_is_guarded(path: tuple[str, ...]) -> None:
    # output.guard gives the JSON error envelope, local --json/--quiet and the {cli} substitution in help.
    assert output.is_guarded(COMMANDS[path]), f"`{_slug(path)}` must be wrapped in @output.guard"


def _leaves(command: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    if (subcommands := getattr(command, "commands", None)) is not None:
        for name, sub in subcommands.items():
            yield from _leaves(sub, (*path, name))
    else:
        yield path, command


def _example_failure(path: tuple[str, ...], command: Any, example: str) -> str | None:
    """Why `example` does not parse against the command: its path, options and arguments. Nothing is run."""
    try:
        tokens = shlex.split(example)
    except ValueError as exc:
        return f"{exc}"
    if tokens[: len(path) + 1] != [CLI, *path]:
        return f"does not start with `{CLI} {' '.join(path)}`"
    ctx = typer.Context(command, info_name=path[-1])
    try:
        values, _, _ = command.make_parser(ctx).parse_args(tokens[len(path) + 1 :])
        for param in command.get_params(ctx):  # type_cast_value stops before the option callbacks
            if param.is_eager and param.name in values:  # --help, --version: the parser keeps only what is given
                return "asks for help or the version instead of a command"
            value, _ = param.consume_value(ctx, values)
            if param.value_is_missing(value):
                if param.required:
                    return f"Missing {param.param_type_name} {param.get_error_hint(ctx)}."
            else:
                param.type_cast_value(ctx, value)
    except Exception as exc:  # Click's own UsageError has format_message; anything else is a bug in the command
        format_message = getattr(exc, "format_message", None)
        return format_message() if callable(format_message) else f"raised {type(exc).__name__}: {exc}"
    return None


def _cleaned(text: str | None) -> str:
    """A help text as the docstring wrote it: output.guard escaped `[` for Typer's rich markup."""
    return inspect.cleandoc(text or "").replace("\\[", "[").strip()


def _param_names(found: re.Match[str]) -> list[str]:
    return [name.strip("`") for name in re.split(r", | / ", found["names"])]


def _doc_lines(paragraph: str, params: set[str]) -> list[str]:
    """The lines of a docstring paragraph as the help shows them.

    A line goes on the line before it, unless it starts an item of a list, the explanation of parameters, an example or
    its result; so does the explanation of a parameter that follows the end of a sentence.
    """
    lines: list[str] = []
    for line in paragraph.splitlines():
        text = line.strip()
        if lines and not (PARAM_LINE.match(text) or LIST_ITEM.match(text) or text.startswith((EXAMPLE, RESULT))):
            lines[-1] += f" {text}"
        else:
            lines.append(text)
    split: list[str] = []
    for line in lines:
        start = 0
        for found in INLINE_PARAM.finditer(line):
            if all(name in params for name in _param_names(found)):
                split.append(line[start : found.start()])
                start = found.start() + 1
        split.append(line[start:])
    return split


def _described(lines: list[str], params: set[str]) -> list[str]:
    """The lines of a paragraph that describe the command: no parameter line (nor the items of its list), no example."""
    kept, in_param = [], False
    for line in lines:
        if in_param and LIST_ITEM.match(line):
            continue
        found = PARAM_LINE.match(line)
        in_param = bool(found) and any(name in params for name in _param_names(found))
        if not in_param and not line.startswith((EXAMPLE, RESULT)):
            kept.append(line)
    return kept


def _failures(path: tuple[str, ...], command: Any) -> list[str]:
    """The rules of the help standard that the command breaks, each as a line naming the command."""
    name = " ".join(path)
    help_text = _cleaned(command.help)
    found: list[str] = []
    if not help_text:
        return [f"`{name}`: no docstring"]
    params = {param.name for param in command.params}
    paragraphs = [_doc_lines(paragraph, params) for paragraph in help_text.split("\n\n")]
    examples = [line.removeprefix(EXAMPLE) for lines in paragraphs for line in lines if line.startswith(EXAMPLE)]
    described = [line for lines in paragraphs for line in _described(lines, params)]
    summary = SENTENCE_END.split(described[0], maxsplit=1)[0] if described else ""
    if not summary:
        found.append(f"`{name}`: no summary")
    elif not help_text.splitlines()[0].startswith(summary):
        found.append(f"`{name}`: summary not one line")
    if not examples:
        found.append(f"`{name}`: no Example")
    if len(examples) > MAX_EXAMPLES:
        found.append(f"`{name}`: more than three examples")
    for example in examples:
        if problem := _example_failure(path, command, example):
            found.append(f"`{name}`: example `{example}` {problem}")
    flat = " ".join(" ".join(described).split())
    for param in command.params:
        help_of_param = " ".join((getattr(param, "help", None) or "").split())
        if not help_of_param:
            found.append(f"`{name}`: parameter `{param.name}` has no help")
        elif help_of_param in flat:
            found.append(f"`{name}`: description repeats the help of `{param.name}`")
    return found


def help_failures(root: typer.Typer) -> dict[tuple[str, ...], list[str]]:
    """The failures of every command of `root`, by command path; a command that meets the standard is absent."""
    found = {path: _failures(path, command) for path, command in _leaves(typer.main.get_command(root))}
    return {path: failures for path, failures in found.items() if failures}


def _allowed(text: str) -> set[tuple[str, ...]]:
    lines = (line.split("#", 1)[0].strip() for line in text.splitlines())
    return {tuple(line.split()) for line in lines if line}


def _why_allowed_is_stale(click_root: Any, path: tuple[str, ...]) -> str:
    """Why an allowlist line that no failure needs is there: the command passes, is a group, or does not exist."""
    command = click_root
    for name in path:
        command = getattr(command, "commands", {}).get(name)
        if command is None:
            return "no such command"
    return "is a group, not a command" if hasattr(command, "commands") else "it meets the standard"


def check_help_standard(root: typer.Typer, allowlist: str) -> str:
    """The report of a run against the allowlist: empty when the help meets the standard."""
    failing, allowed = help_failures(root), _allowed(allowlist)
    report = [line for path, lines in failing.items() if path not in allowed for line in lines]
    click_root = typer.main.get_command(root)
    report += [
        f"remove from tests/help_allowlist.txt, {_why_allowed_is_stale(click_root, p)}: {' '.join(p)}"
        for p in sorted(allowed - failing.keys())
    ]
    new = sorted(" ".join(path) for path in failing if path not in allowed)
    if new:
        report += ["Lines for tests/help_allowlist.txt:", *new]
    return "\n".join(report)


def test_help_meets_the_standard() -> None:
    report = check_help_standard(app, ALLOWLIST.read_text(encoding="utf-8"))
    assert not report, f"\n{report}"


def _other(ctx: typer.Context) -> None:
    """Stand beside the command under test.

    Example: {cli} other
    """


def _probe(**commands: Callable[..., None]) -> typer.Typer:
    probe = typer.Typer(add_completion=False)
    for name, callback in commands.items():
        probe.command(name)(output.guard(callback))
    probe.command("other")(output.guard(_other))  # a Typer app of one command has no command name
    return probe


def _report(callback: Callable[..., None], allowlist: str = "") -> str:
    return check_help_standard(_probe(cmd=callback), allowlist)


def _good(ctx: typer.Context, size: int = typer.Option(3, "--size", help="The size.")) -> None:
    """Do the thing.

    Example: {cli} cmd --size 2
    """


def test_a_command_that_meets_the_standard_passes() -> None:
    assert _report(_good) == ""


def test_a_command_without_an_example_fails() -> None:
    def cmd(ctx: typer.Context) -> None:
        """Do the thing."""

    assert "`cmd`: no Example" in _report(cmd)


def test_a_summary_on_two_lines_fails() -> None:
    def cmd(ctx: typer.Context) -> None:
        """Do the thing that takes
        two lines to say.

        Example: {cli} cmd
        """

    assert "`cmd`: summary not one line" in _report(cmd)


def test_a_description_that_repeats_an_option_help_fails() -> None:
    def cmd(ctx: typer.Context, size: int = typer.Option(3, "--size", help="The size of it.")) -> None:
        """Do the thing.

        The size of it. Then it goes.

        Example: {cli} cmd
        """

    assert "`cmd`: description repeats the help of `size`" in _report(cmd)


def test_an_example_with_an_unknown_option_fails() -> None:
    def cmd(ctx: typer.Context) -> None:
        """Do the thing.

        Example: {cli} cmd --nope
        """

    report = _report(cmd)
    assert "`cmd`: example `yd cmd --nope`" in report
    assert "No such option: --nope" in report


def test_an_example_does_not_run_the_callback_of_an_option() -> None:
    calls: list[str] = []

    def record(value: str) -> str:
        calls.append(value)
        return value

    def cmd(ctx: typer.Context, name: str = typer.Option("x", "--name", help="The name.", callback=record)) -> None:
        """Do the thing.

        Example: {cli} cmd --name Ann
        """

    assert _report(cmd) == ""
    assert calls == []


def test_an_error_that_is_not_click_names_its_type() -> None:
    def explode(value: str) -> str:
        raise ZeroDivisionError("boom")

    def cmd(ctx: typer.Context, name: str = typer.Option("x", "--name", help="The name.", parser=explode)) -> None:
        """Do the thing.

        Example: {cli} cmd --name Ann
        """

    assert "ZeroDivisionError" in _report(cmd)


def test_an_allowlist_line_for_a_missing_command_says_so() -> None:
    assert "remove from tests/help_allowlist.txt, no such command: ghost" in _report(_good, "ghost\n")


def test_an_example_that_asks_for_help_fails() -> None:
    def cmd(ctx: typer.Context) -> None:
        """Do the thing.

        Example: {cli} cmd --help
        """

    assert "`cmd`: example `yd cmd --help` asks for help or the version instead of a command" in _report(cmd)


def test_an_example_missing_a_required_option_names_the_flag() -> None:
    def cmd(ctx: typer.Context, name: str = typer.Option(..., "--name", help="The name.")) -> None:
        """Do the thing.

        Example: {cli} cmd
        """

    assert "`cmd`: example `yd cmd` Missing option '--name'." in _report(cmd)


def test_an_allowlist_line_for_a_group_says_so() -> None:
    probe = _probe(cmd=_good)
    probe.add_typer(_probe(cmd=_good), name="sub", help="A group.")
    assert "remove from tests/help_allowlist.txt, is a group, not a command: sub" in check_help_standard(probe, "sub\n")


def test_an_example_outside_the_command_path_fails() -> None:
    def cmd(ctx: typer.Context) -> None:
        """Do the thing.

        Example: {cli} other
        """

    assert "does not start with `yd cmd`" in _report(cmd)


def test_an_example_missing_an_argument_fails() -> None:
    def cmd(ctx: typer.Context, key: str = typer.Argument(..., help="The key.")) -> None:
        """Do the thing.

        Example: {cli} cmd
        """

    assert "`cmd`: example `yd cmd`" in _report(cmd)


def test_a_parameter_without_help_fails() -> None:
    def cmd(ctx: typer.Context, size: int = typer.Option(3, "--size")) -> None:
        """Do the thing.

        Example: {cli} cmd
        """

    assert "`cmd`: parameter `size` has no help" in _report(cmd)


def test_more_than_three_examples_fail() -> None:
    def cmd(ctx: typer.Context) -> None:
        """Do the thing.

        Example: {cli} cmd
        Example: {cli} cmd
        Example: {cli} cmd
        Example: {cli} cmd
        """

    assert "`cmd`: more than three examples" in _report(cmd)


def test_a_failing_command_in_the_allowlist_passes() -> None:
    def cmd(ctx: typer.Context) -> None:
        """Do the thing."""

    assert _report(cmd, "# not yet\ncmd  # old\n") == ""


def test_an_allowlisted_command_that_meets_the_standard_must_be_removed() -> None:
    assert "remove from tests/help_allowlist.txt, it meets the standard: cmd" in _report(_good, "cmd\n")


def test_a_failure_prints_the_lines_for_the_allowlist() -> None:
    def cmd(ctx: typer.Context) -> None:
        """Do the thing."""

    assert _report(cmd).splitlines()[-2:] == ["Lines for tests/help_allowlist.txt:", "cmd"]


@pytest.mark.parametrize("path", sorted(GROUPS), ids=_slug)
def test_every_group_has_help(path: tuple[str, ...]) -> None:
    assert (GROUPS[path].info.help or "").strip(), f"group `{_slug(path)}` has no description"


def test_help_keeps_brackets() -> None:
    """Typer renders help as rich markup, which drops `[...]`; output.guard escapes docstrings."""

    def cmd(ctx: typer.Context) -> None:
        """Declared in [[tool.rb.external]], see [x].

        Example: {cli} cmd
        """

    probe = typer.Typer()
    probe.command("cmd")(output.guard(cmd))
    probe.command("other")(output.guard(cmd))
    result = CliRunner().invoke(probe, ["cmd", "--help"], env=HELP_ENV)
    assert "[[tool.rb.external]], see [x]." in result.output
