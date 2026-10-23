"""The Gitea Actions workflow: every package has one (the Standard, CI)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".gitea" / "workflows" / "ci.yml"
# The gate of the template tag this project was generated or last updated from, run through uvx.
TEMPLATE_TAG = yaml.safe_load((ROOT / ".copier-answers.yml").read_text())["_commit"]
GATE = (
    'uvx --from "git+https://homeserver.tailee01ab.ts.net:3000/bolandeu/cli-generator.git'
    f'@{TEMPLATE_TAG}#subdirectory=gate" rb-release check'
)
STANDARD = "https://homeserver.tailee01ab.ts.net:3000/bolandeu/cli-generator/src/branch/main/skills/cli-builder/reference/standard.md"


def test_no_github_workflow() -> None:
    assert not (ROOT / ".github").exists()


def test_workflow_runs_the_gate_on_the_docker_runner() -> None:
    job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["gate"]
    assert job["runs-on"] == "docker"
    assert "ci-cache:/cache" in job["container"]["volumes"]
    checkout = next(step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0
    assert job["steps"][-1]["run"].strip() == GATE


def _steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["gate"]["steps"]


def test_scanners_are_installed_before_the_gate_at_pinned_versions() -> None:
    steps = _steps()
    gate = next(i for i, step in enumerate(steps) if str(step.get("run", "")).strip() == GATE)
    scripts = [step["run"] for step in steps[:gate] if "run" in step]
    for tool in ("osv-scanner", "gitleaks"):
        script = next(s for s in scripts if f"/cache/bin/{tool}-" in s)
        urls = re.findall(r"https://github\.com/\S+", script)
        assert urls
        assert all(re.search(r"/download/v\d+\.\d+\.\d+/", url) for url in urls)
        assert "latest" not in script


def test_scanners_are_cached_per_pinned_version() -> None:
    script = next(step["run"] for step in _steps() if "gitleaks" in step.get("run", ""))
    lines = script.splitlines()
    for tool, version in (("osv-scanner", "2.7.0"), ("gitleaks", "8.30.1")):
        cached = f"/cache/bin/{tool}-{version}"
        var = next(line.split("=")[0] for line in lines if line.endswith(f"={cached}"))
        download = next(line for line in lines if line.startswith(f"[ -x ${var} ] ||"))
        assert f"/download/v{version}/" in download
        assert f"ln -sf ${var} /usr/local/bin/{tool}" in lines


def test_only_the_workflow_writes_the_gate_command_and_the_files_point_to_it() -> None:
    import tomllib

    config = tomllib.loads((ROOT / ".agents" / "antagor" / "antagor.toml").read_text())
    assert "python3 scripts/check_command_docstrings.py" in config["checks"]
    assert not any("rb-release" in check for check in config["checks"])
    publish = config["publish"]
    if publish.get("gate") == "remote":
        assert publish["gate_status_url"].endswith("/commits/{commit}/status")
    for name in ("AGENTS.md", "CODING_STANDARDS.md"):
        text = (ROOT / name).read_text()
        assert ".gitea/workflows/ci.yml" in text
        assert "rb-release check" in text
        assert "uvx --from" not in text
    # README.md is the project's own (copier skips it on update): not checked here.
    assert not (ROOT / "scripts" / "release.py").exists()


def test_agents_file_links_the_standard() -> None:
    assert STANDARD in (ROOT / "AGENTS.md").read_text()


def test_workflow_runs_on_main_tags_and_the_remote_gate_branch() -> None:
    triggers = yaml.safe_load(WORKFLOW.read_text())[True]  # YAML reads the key `on` as True
    assert triggers["push"]["branches"] == ["main", "antagor/publish-*"]
    assert triggers["push"]["tags"] == ["v*"]
