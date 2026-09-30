"""The repo's own tooling scripts: the parts of their logic that decide what the gate demands."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = _load("release")
hook = _load("check_changelog_fragment")


@pytest.mark.parametrize(
    "path",
    [
        "uv.lock",
        ".github/workflows/ci.yml",
        "scripts/release.py",
        "tests/test_cli.py",
        ".githooks/pre-commit",
        ".claude/settings.json",
        "AGENTS.md",
        "CLAUDE.md",
    ],
)
def test_tooling_changes_need_no_fragment(path: str) -> None:
    assert not release.needs_fragment(path)


@pytest.mark.parametrize("path", ["src/pkg/cli.py", "pyproject.toml", "README.md", "scripts.py", "testsuite/x.py"])
def test_package_changes_need_a_fragment(path: str) -> None:
    assert release.needs_fragment(path)


def test_gate_and_pre_commit_hook_agree() -> None:
    assert release.NO_FRAGMENT_NEEDED == hook.NO_FRAGMENT_NEEDED


def test_release_follows_towncrier_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release, "_tool", lambda name: {"filename": "docs/CHANGES.md"} if name == "towncrier" else {})
    assert release.changelog_file() == "docs/CHANGES.md"
    monkeypatch.setattr(release, "_tool", lambda name: {})
    assert release.changelog_file() == "CHANGELOG.md"


def test_release_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    # Independent of this project's own [tool.cli-generator]: defaults, then configured values.
    monkeypatch.setattr(release, "_tool", lambda name: {})
    assert (release.gate_extras(), release.release_commit_message("1.2.3")) == ([], "Release v1.2.3")

    config = {"gate_extras": ["browser"], "release_commit": "chore(release): v{version}"}
    monkeypatch.setattr(release, "_tool", lambda name: config if name == "cli-generator" else {})
    assert (release.gate_extras(), release.release_commit_message("1.2.3")) == (["browser"], "chore(release): v1.2.3")


BASE_PYPROJECT = """
[project]
name = "x"
dependencies = ["httpx>=0.27"]

[tool.ruff]
line-length = 120
"""


@pytest.mark.parametrize("script", [release, hook], ids=["release", "pre-commit"])
@pytest.mark.parametrize(
    ("new", "changed"),
    [
        (BASE_PYPROJECT.replace("line-length = 120", "line-length = 100"), False),  # [tool.*] is tooling
        (BASE_PYPROJECT + '\n[tool.cli-generator]\ngate_extras = ["x"]\n', False),
        (BASE_PYPROJECT.replace('"httpx>=0.27"', '"httpx>=0.28"'), True),  # dependencies reach users
        (BASE_PYPROJECT.replace('name = "x"', 'name = "rb-x"'), True),
        (BASE_PYPROJECT + '\n[project.scripts]\nx = "x.cli:main"\n', True),
        ("not [valid toml", True),
    ],
)
def test_pyproject_needs_a_fragment_only_when_project_changes(script: ModuleType, new: str, changed: bool) -> None:
    assert script.project_table_changed(BASE_PYPROJECT, new) is changed


@pytest.mark.parametrize("script", [release, hook], ids=["release", "pre-commit"])
def test_missing_pyproject_side_counts_as_changed(script: ModuleType) -> None:
    assert script.project_table_changed(None, BASE_PYPROJECT) is True


@pytest.mark.parametrize(
    "url", ["git@github.com:owner/tool.git", "https://github.com/owner/tool.git", "https://github.com/owner/tool"]
)
def test_repo_url_normalized(url: str) -> None:
    assert release.normalize_repo_url(url) == "https://github.com/owner/tool"


def test_install_command_is_pinned_and_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release, "repository_url", lambda: "https://github.com/owner/tool")
    command = release.install_command("v1.2.3")
    assert command.startswith('uv tool install "') and command.endswith(
        ' @ git+https://github.com/owner/tool.git@v1.2.3"'
    )


def test_external_programs_found_by_literal_name() -> None:
    source = """
import shutil, subprocess
from .core import deps
exe = deps.require_cli("serp", "0.3.0")
shutil.which("ffmpeg")
subprocess.run(["npx", "-y", "lighthouse"], check=True)
subprocess.check_output(("git", "rev-parse", "HEAD"))
subprocess.run([exe, "search"])  # built at runtime: covered by require_cli above
"""
    assert release.external_programs(source) == {"serp", "ffmpeg", "npx", "git"}


def test_external_registry_must_match_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.py").write_text('import shutil\nshutil.which("ffmpeg")\n')
    monkeypatch.setattr(release, "ROOT", tmp_path)

    monkeypatch.setattr(release, "_tool", lambda name: {})
    with pytest.raises(release.StepFailed, match=re.escape("`ffmpeg` is run in src/mod.py but not declared")):
        release.check_external_deps()

    registry: dict[str, list[dict[str, object]]] = {
        "external": [{"name": "ffmpeg", "why": "video"}, {"name": "node", "why": "unused"}]
    }
    monkeypatch.setattr(release, "_tool", lambda name: registry if name == "rb" else {})
    with pytest.raises(release.StepFailed, match=re.escape("`node` is declared but nothing in src/ runs it")):
        release.check_external_deps()

    registry["external"][1]["detect"] = False  # run through an injected runner: declared on trust
    assert release.check_external_deps() == "2 declared, all used (1 with detect = false)"

    registry["external"][1]["why"] = ""
    with pytest.raises(release.StepFailed, match="needs `name` and `why`"):
        release.check_external_deps()
