"""The package skill part (copier's include_skill): `skill install`, `skill list`, --ai, and every bundled agent
skill: frontmatter present, name = <cli>-<dir name> (<cli> for the conventions skill), and no skill lists the
CLI's commands (the Standard, Package skill: the help is the list)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import typer.core
import typer.main

from rb_yandex_direct.cli import app
from rb_yandex_direct.core import skills
from rb_yandex_direct.core.version import cli_name

from .test_cli import invoke, invoke_json

DATA = Path(skills.__file__).resolve().parents[1] / "data"


def _command_names() -> list[str]:
    root = typer.main.get_command(app)
    assert isinstance(root, typer.core.TyperGroup)
    return sorted(root.commands)


def _problems(data: Path) -> list[str]:
    """What is wrong with the skills under a data dir, each line naming the file."""
    cli = cli_name()
    found = []
    paths = [data / "SKILL.md", *sorted(data.glob(f"{skills.EXTRAS_DIR}/*/SKILL.md"))]
    list_item = re.compile(rf"^\s*(?:[-*]|\d+\.|\|)\s*`?{re.escape(cli)} ({'|'.join(_command_names())})\b", re.M)
    for path in paths:
        text = path.read_text()
        meta = skills.frontmatter(text)
        expected = cli if path.parent == data else f"{cli}-{path.parent.name}"
        if not meta:
            found.append(f"{path}: no frontmatter")
            continue
        if meta.get("name") != expected:
            found.append(f"{path}: name is {meta.get('name')!r}, expected {expected!r}")
        if not meta.get("description"):
            found.append(f"{path}: no description")
        if list_item.search(text):
            found.append(f"{path}: lists the commands of {cli}")
    return found


def test_every_bundled_skill_follows_the_standard() -> None:
    assert _problems(DATA) == []


def test_a_wrong_name_no_frontmatter_or_a_command_list_names_the_file(tmp_path: Path) -> None:
    cli = cli_name()
    good = f"---\nname: {cli}\ndescription: d\n---\n\n# x\n"
    (tmp_path / "SKILL.md").write_text(good)
    extras = tmp_path / skills.EXTRAS_DIR
    for directory, text in {
        "fine": f"---\nname: {cli}-fine\ndescription: d\n---\n",
        "misnamed": f"---\nname: {cli}-other\ndescription: d\n---\n",
        "bare": "# no frontmatter\n",
        "listing": f"---\nname: {cli}-listing\ndescription: d\n---\n\n- `{cli} {_command_names()[0]}` does a thing\n",
    }.items():
        (extras / directory).mkdir(parents=True)
        (extras / directory / "SKILL.md").write_text(text)
    problems = _problems(tmp_path)
    assert [Path(line.split(":")[0]).parent.name for line in problems] == ["bare", "listing", "misnamed"]


def test_frontmatter_of_text_without_it_is_empty() -> None:
    assert skills.frontmatter("# title\n") == {}
    assert skills.frontmatter("---\nname: a\n") == {}
    assert skills.frontmatter("---\nname: a\ndescription: b: c\n---\nbody") == {"name": "a", "description": "b: c"}


def test_skill_install_writes_to_project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    code, payload = invoke_json("skill", "install", "--tool", "claude-code", "--project")
    assert code == 0
    installed = tmp_path / ".claude" / "skills" / "yd" / "SKILL.md"
    assert installed.is_file()
    assert "name: yd" in installed.read_text()
    assert payload["path"] == str(installed)


def test_skill_install_without_extra_skills_writes_only_the_conventions_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    code, payload = invoke_json("skill", "install", "--tool", "claude-code", "--project")
    assert code == 0
    assert set(payload) == {"ok", "tool", "scope", "path"}
    assert [p.parent.name for p in (tmp_path / ".claude" / "skills").glob("*/SKILL.md")] == ["yd"]


@pytest.fixture
def extra_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A package data dir holding the conventions skill and two extra skills."""
    data = tmp_path / "pkgdata"
    data.mkdir()
    (data / "SKILL.md").write_text("---\nname: yd\ndescription: Conventions.\n---\n")
    for name, description in {"og-image": "Make og images.", "video": "Make videos."}.items():
        (data / "skills" / name).mkdir(parents=True)
        (data / "skills" / name / "SKILL.md").write_text(f"---\nname: yd-{name}\ndescription: {description}\n---\n")
    monkeypatch.setattr(skills, "_data", lambda: data)
    return data


def test_skill_install_writes_every_bundled_skill_into_its_own_directory(
    extra_skills: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    code, payload = invoke_json("skill", "install", "--tool", "claude-code", "--project")
    assert code == 0
    names = ("yd", "yd-og-image", "yd-video")
    expected = [work / ".claude" / "skills" / name / "SKILL.md" for name in names]
    assert all(path.is_file() for path in expected)
    assert payload["paths"] == [str(path) for path in expected]
    assert payload["path"] == str(expected[0])


def test_skill_install_one_skill_by_short_or_full_name(
    extra_skills: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    for wanted in ("video", "yd-video"):
        code, payload = invoke_json("skill", "install", "--project", "--skill", wanted)
        assert code == 0
        assert "paths" not in payload
    assert [p.parent.name for p in (work / ".claude" / "skills").glob("*/SKILL.md")] == ["yd-video"]


def test_skill_install_unknown_skill_names_the_bundled_ones(
    extra_skills: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    code, payload = invoke_json("skill", "install", "--project", "--skill", "nope")
    assert code == 2
    assert payload["error"]["code"] == "INVALID_ARGUMENTS"
    assert "yd, yd-og-image, yd-video" in payload["error"]["message"]


EXPECTED_SKILLS = [
    {"name": "yd", "description": "Conventions."},
    {"name": "yd-og-image", "description": "Make og images."},
    {"name": "yd-video", "description": "Make videos."},
]


def test_skill_list_shows_every_bundled_skill(extra_skills: Path) -> None:
    code, payload = invoke_json("skill", "list")
    assert code == 0
    assert payload["skills"] == EXPECTED_SKILLS
    human = invoke("skill", "list").stdout
    assert "yd-video: Make videos." in human


def test_describe_lists_the_same_skills(extra_skills: Path) -> None:
    _, described = invoke_json("describe")
    meta = {item["name"]: item["value"] for item in described["command"]["metadata"]}
    assert meta["x-rb-skills"] == EXPECTED_SKILLS


def test_bare_skill_group_shows_help_and_exits_zero() -> None:
    result = invoke("skill")
    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_ai_prints_the_conventions_skill() -> None:
    result = invoke("--ai")
    assert result.exit_code == 0
    assert result.stdout == skills.conventions().text + "\n"
