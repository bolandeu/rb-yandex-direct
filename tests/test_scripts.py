"""The repo's own tooling scripts: the parts of their logic that decide what the gate demands."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_antagor_project_config() -> None:
    import tomllib

    root = SCRIPTS.parent
    config = tomllib.loads((root / ".agents" / "antagor" / "antagor.toml").read_text())
    # A package may add or reorder checks; the template guarantees only the package's own facts.
    assert "python3 scripts/check_command_docstrings.py" in config["checks"]
    assert "gate check" in config["heavy"]
    publish = config["publish"]
    if publish.get("gate") == "remote":
        status_url = publish["gate_status_url"]
        assert status_url.startswith("https://homeserver.tailee01ab.ts.net:3000/api/v1/repos/bolandeu/")
        assert status_url.endswith("/commits/{commit}/status")
    expected = {"versioning": "semver", "changelog": "CHANGELOG.md", "deploy_command": "sh scripts/deploy.sh"}
    assert {k: config["publish"].get(k) for k in expected} == expected  # Antagor may add its own keys
    assert "git push origin main --follow-tags" in (SCRIPTS / "deploy.sh").read_text()


def test_agents_file_names_the_standard_and_the_gate() -> None:
    agents = (SCRIPTS.parent / "AGENTS.md").read_text()
    assert "cli-generator/src/branch/main/skills/cli-builder/reference/standard.md" in agents
    assert "gate check" in agents


def test_docstring_check_reads_the_working_tree_only() -> None:
    import inspect

    check = _load("check_command_docstrings")
    assert list(inspect.signature(check.stale_commands).parameters) == ["paths"]
    assert "index" not in (check.stale_commands.__doc__ or "")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_env_files_are_ignored(tmp_path: Path) -> None:
    shutil.copy(SCRIPTS.parent / ".gitignore", tmp_path / ".gitignore")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "i")
    (tmp_path / ".env").write_text("TOKEN=x\n")
    (tmp_path / ".env.local").write_text("TOKEN=y\n")
    assert _git(tmp_path, "status", "--porcelain", "--untracked-files=all") == ""
