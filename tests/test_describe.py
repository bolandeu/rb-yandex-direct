"""The `describe --json` contract: a valid OpenCLI document that matches the real CLI.

- valid against the OpenCLI JSON Schema, vendored at tests/data/opencli.schema.json
  (github.com/spectreconsole/open-cli, schema.json at 2118553e; spec 0.1);
- every command Typer registers is in it, and nothing else; every visible option
  it lists shows up in that command's --help;
- snapshot: tests/snapshots/describe.json (syrupy). A changed contract fails until
  the snapshot is refreshed with `uv run pytest --snapshot-update`, which puts the
  change in the diff — review it like any other breaking change.
"""

from __future__ import annotations

import enum
import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path

import jsonschema
import pytest
import typer
from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode
from typer.testing import CliRunner

from rb_yandex_direct.cli import app
from rb_yandex_direct.core import errors, opencli

from .test_cli import plain

CLI = "yd"
SCHEMA = json.loads((Path(__file__).parent / "data" / "opencli.schema.json").read_text())
HELP_ENV = {"COLUMNS": "200", "NO_COLOR": "1", "TERM": "dumb"}
runner = CliRunner()


def _describe() -> dict:
    result = runner.invoke(app, ["describe", "--json"], prog_name=CLI)
    assert result.exit_code == 0, result.output
    assert len(result.stdout.splitlines()) == 1, "--json prints the document on one line"
    return json.loads(result.stdout)


DOCUMENT = _describe()


def _walk(command: dict, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], dict]]:
    for sub in command.get("commands", []):
        yield (*path, sub["name"]), sub
        yield from _walk(sub, (*path, sub["name"]))


def _registered(group: typer.Typer, prefix: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    for info in group.registered_commands:
        assert info.callback is not None
        yield (*prefix, info.name or getattr(info.callback, "__name__", "").replace("_", "-"))
    for sub in group.registered_groups:
        assert sub.name is not None and sub.typer_instance is not None
        yield (*prefix, sub.name)
        yield from _registered(sub.typer_instance, (*prefix, sub.name))


COMMANDS = dict(_walk(DOCUMENT["command"]))


def _meta(entry: dict) -> dict:
    return {item["name"]: item.get("value") for item in entry.get("metadata", [])}


def test_valid_opencli_document() -> None:
    jsonschema.Draft202012Validator(SCHEMA).validate(DOCUMENT)
    assert DOCUMENT["info"]["title"] == CLI


def test_human_output_is_the_same_document() -> None:
    result = runner.invoke(app, ["describe"], prog_name=CLI)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == DOCUMENT


def test_lists_exactly_the_registered_commands() -> None:
    assert set(COMMANDS) == set(_registered(app))


@pytest.mark.parametrize("path", sorted(COMMANDS), ids="-".join)
def test_options_are_the_real_ones(path: tuple[str, ...]) -> None:
    result = runner.invoke(app, [*path, "--help"], env=HELP_ENV, prog_name=CLI)
    assert result.exit_code == 0, result.output
    squeezed = re.sub(
        r"[│\s]+", "", plain(result.output)
    )  # CI forces width 80: CI forces a narrow table: rich may elide a long name
    for option in COMMANDS[path].get("options", []):
        if not option.get("hidden"):
            name = option["name"]
            shown = name in squeezed or any(f"{name[:k]}…" in squeezed for k in range(8, len(name)))  # rich elides
            assert shown, f"{' '.join(path)}: {option['name']} isn't in --help"


def test_every_exit_code_is_documented() -> None:
    """Each `exit_code=N` a CliError in core/errors.py uses is in EXIT_CODES, hence in the document."""
    used = {int(code) for code in re.findall(r"exit_code=(\d+)", Path(errors.__file__).read_text())}
    assert used <= set(errors.EXIT_CODES)
    assert [entry["code"] for entry in DOCUMENT["command"]["exitCodes"]] == list(errors.EXIT_CODES)


def test_root_metadata() -> None:
    meta = _meta(DOCUMENT["command"])
    assert meta["x-rb-tool"]
    assert "user_data_dir" in meta["x-rb-data"]
    names = [entry["name"] for entry in meta["x-rb-env"]]
    assert len(names) == len(set(names))


class DescribeSnapshot(SingleFileSnapshotExtension):
    """tests/snapshots/describe.json, pretty-printed for readable diffs."""

    _write_mode = WriteMode.TEXT
    file_extension = "json"

    @classmethod
    def dirname(cls, *, test_location) -> str:
        return str(Path(__file__).parent / "snapshots")

    @classmethod
    def get_snapshot_name(cls, *, test_location, index=0) -> str:
        return "describe"


def test_describe_is_the_same_in_ci(same_in_ci: Callable[[str], None]) -> None:
    same_in_ci("test_describe_snapshot")


def test_describe_snapshot(snapshot) -> None:
    document = json.loads(json.dumps(DOCUMENT))
    # Versions move with every release and template update — not a contract change.
    document["info"]["version"] = "<version>"
    for item in document["command"]["metadata"]:
        if item["name"] == "x-rb-template-version":
            item["value"] = "<template-version>"
    rendered = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    assert rendered == snapshot(extension_class=DescribeSnapshot)


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


def test_parameter_shapes() -> None:
    """Choices, variadic and optional arguments, repeatable and hidden options, Enum/Path defaults, hidden commands."""
    probe = typer.Typer()

    @probe.command()
    def paint(
        targets: list[str] = typer.Argument(..., help="What to paint."),
        color: Color = typer.Option(Color.RED, "--color", "-c", help="Which color."),
        out: Path = typer.Option(Path("out"), help="Where to."),
        tag: list[str] = typer.Option([], help="Tags, repeatable."),
        secret: str = typer.Option("", hidden=True, help="Hidden."),
        force: bool = typer.Option(False, "--force/--no-force", help="Overwrite."),
        name: str = typer.Option(..., help="Required."),
    ) -> None:
        """Paint [things]."""

    @probe.command(hidden=True)
    def internal(path: str = typer.Argument(None, help="Optional.")) -> None:
        """Internal."""

    document = opencli.document(typer.main.get_command(probe))
    jsonschema.Draft202012Validator(SCHEMA).validate(document)
    paint_cmd, internal_cmd = document["command"]["commands"]
    assert paint_cmd["description"] == "Paint [things]."
    options = {option["name"]: option for option in paint_cmd["options"]}
    assert options["--color"]["aliases"] == ["-c"]
    assert options["--color"]["arguments"][0]["acceptedValues"] == ["red", "blue"]
    assert _meta(options["--color"])["x-rb-default"] == "red"
    assert _meta(options["--out"])["x-rb-default"] == "out"
    assert _meta(options["--tag"])["x-rb-multiple"] is True
    assert options["--color"]["arguments"][0]["arity"] == {"maximum": 1}
    assert "arity" not in options["--tag"]["arguments"][0]
    assert options["--secret"]["hidden"] is True
    assert options["--force"]["aliases"] == ["--no-force"] and "arguments" not in options["--force"]
    assert options["--name"]["required"] is True
    [targets] = paint_cmd["arguments"]
    assert targets["required"] is True and targets["arity"] == {"minimum": 1}
    assert internal_cmd["hidden"] is True
    [path] = internal_cmd["arguments"]
    assert path["required"] is False and path["arity"] == {"minimum": 0, "maximum": 1}
