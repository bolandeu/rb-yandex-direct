"""Tests of `core.deps`: finding the CLIs this package depends on and the errors for a missing or too old one."""

from __future__ import annotations

import re
import subprocess

import pytest

from rb_yandex_direct.core import deps
from rb_yandex_direct.core.errors import DependencyTooOld


@pytest.fixture
def fake_cli(monkeypatch: pytest.MonkeyPatch):
    """Pretend a CLI `other` is on PATH and prints `state["version"]` for --version."""
    state: dict = {"path": "/usr/bin/other", "version": "0.3.1", "returncode": 0}
    monkeypatch.setattr(deps.shutil, "which", lambda name: state["path"] if name == "other" else None)

    def fake_run(argv, **kwargs):
        assert argv == [state["path"], "--version"]
        return subprocess.CompletedProcess(argv, state["returncode"], stdout=f"{state['version']}\n", stderr="")

    monkeypatch.setattr(deps.subprocess, "run", fake_run)
    return state


def test_new_enough_cli_returns_its_path(fake_cli) -> None:
    assert deps.require_cli("other", "0.3.0") == "/usr/bin/other"
    fake_cli["version"] = "0.0.0.post3.dev0+gabc123"  # dev build: accepted
    assert deps.require_cli("other", "0.3.0") == "/usr/bin/other"


def test_old_cli_is_dependency_too_old(fake_cli) -> None:
    fake_cli["version"] = "0.2.9"
    with pytest.raises(DependencyTooOld) as excinfo:
        deps.require_cli("other", "0.3.0")
    error = excinfo.value
    assert (error.code, error.exit_code) == ("DEPENDENCY_TOO_OLD", 1)
    assert "0.2.9" in error.message and ">= 0.3.0" in error.message
    assert "uv tool upgrade other" in (error.action or "")


@pytest.mark.parametrize("change", [{"path": None}, {"version": "garbage"}, {"returncode": 1}])
def test_missing_or_unreadable_cli(fake_cli, change: dict) -> None:
    fake_cli.update(change)
    with pytest.raises(DependencyTooOld):
        deps.require_cli("other", "0.3.0")


def test_missing_cli_action_uses_install_url(fake_cli) -> None:
    fake_cli["path"] = None
    with pytest.raises(DependencyTooOld) as excinfo:
        deps.require_cli("other", "0.3.0", install_url="https://github.com/example/other")
    pinned = 'uv tool install "rb-other @ git+https://github.com/example/other.git@v0.3.0" --force'
    assert excinfo.value.action == f"Run '{pinned}', then retry."

    with pytest.raises(DependencyTooOld) as excinfo:
        deps.require_cli("other", "0.3.0")
    action = excinfo.value.action or ""
    assert "git+" not in action  # no URL known: no made-up install line
    assert "other >= 0.3.0" in action


def test_old_cli_action_names_the_distribution(fake_cli) -> None:
    fake_cli["version"] = "0.2.0"
    with pytest.raises(DependencyTooOld) as excinfo:
        deps.require_cli("other", "0.3.0", install_url="https://github.com/example/other.git")
    assert '"rb-other @ git+https://github.com/example/other.git@v0.3.0" --force' in (excinfo.value.action or "")

    with pytest.raises(DependencyTooOld) as excinfo:
        deps.require_cli("other", "0.3.0")
    assert "uv tool upgrade other" in (excinfo.value.action or "")


REGISTRY = """
[project]
name = "x"

[[tool.rb.external]]
name = "other"
required = true
min_version = "0.3.0"
check = "other version"
why = "does the other thing"
dist = "rb-other-tool"
url = "https://github.com/example/other"

[[tool.rb.external]]
name = "maybe"
required = false
why = "nice to have"
"""


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(deps, "_pyproject_text", lambda: REGISTRY)
    deps.declared.cache_clear()
    yield deps.declared()
    deps.declared.cache_clear()


def test_registry_is_read(registry) -> None:
    assert set(registry) == {"other", "maybe"}
    other, maybe = registry["other"], registry["maybe"]
    assert (other.min_version, other.check, maybe.required) == ("0.3.0", "other version", False)


def test_require_cli_takes_min_version_and_check_from_registry(registry, fake_cli, monkeypatch) -> None:
    seen: list[list[str]] = []

    def fake_run(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=f"other {fake_cli['version']}\n", stderr="")

    monkeypatch.setattr(deps.subprocess, "run", fake_run)
    fake_cli["version"] = "0.2.9"
    with pytest.raises(DependencyTooOld, match=re.escape(">= 0.3.0")):
        deps.require_cli("other")
    assert seen[-1] == ["/usr/bin/other", "version"]  # the registry's check command


def test_doctor_checks_required_and_optional(registry, monkeypatch: pytest.MonkeyPatch) -> None:
    installed = {"other": ("/bin/other", "0.4.0")}
    monkeypatch.setattr(deps, "installed_cli_version", lambda name: installed.get(name, (None, None)))
    checks = {check["name"]: check for check in deps.doctor_checks()}
    assert checks["external:other"]["ok"] is True
    assert checks["external:maybe"]["ok"] is True  # optional and missing: still healthy
    assert "optional" in checks["external:maybe"]["detail"]


@pytest.mark.parametrize(
    ("output", "version"),
    [
        ("0.3.1", "0.3.1"),
        ("ffmpeg version 6.1.1-3ubuntu5 Copyright", "6.1.1"),
        ("v20.11.0", "20.11.0"),
        ("nothing", None),
    ],
)
def test_version_parsing(output: str, version: str | None) -> None:
    assert deps._version_in(output) == version


def test_registry_dist_and_url_shape_the_hint(registry, fake_cli) -> None:
    fake_cli["path"] = None
    with pytest.raises(DependencyTooOld) as excinfo:
        deps.require_cli("other")
    assert '"rb-other-tool @ git+https://github.com/example/other.git@v0.3.0" --force' in (excinfo.value.action or "")
