"""The project part (copier's include_project): `init`, `status`, `config`, the global --project, doctor's checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from rb_yandex_direct.core import services

from .test_cli import invoke, invoke_json


def init(tmp_path: Path, name: str = "demo") -> None:
    assert invoke("--project", str(tmp_path), "init", "--name", name).exit_code == 0


def test_bare_config_group_shows_help_and_exits_zero() -> None:
    result = invoke("config")
    assert result.exit_code == 0
    assert "Usage:" in result.output


# --- init / status / config ------------------------------------------------


def test_init_and_status(tmp_path: Path) -> None:
    init(tmp_path)
    code, payload = invoke_json("--project", str(tmp_path), "status")
    assert code == 0
    assert payload["ok"] is True
    assert payload["project"] == "demo"


def test_status_without_init_fails(tmp_path: Path) -> None:
    code, payload = invoke_json("--project", str(tmp_path), "status")
    assert code == 4
    assert payload["ok"] is False
    assert payload["error"]["code"] == "PROJECT_NOT_INITIALIZED"
    assert "init" in payload["error"]["action"]


def test_config_get_unknown_key_fails(tmp_path: Path) -> None:
    init(tmp_path)
    code, payload = invoke_json("--project", str(tmp_path), "config", "get", "does.not.exist")
    assert code == 2
    assert payload["error"]["code"] == "INVALID_ARGUMENTS"


def test_config_set_unknown_key_fails_without_persisting(tmp_path: Path) -> None:
    init(tmp_path)
    code, payload = invoke_json("--project", str(tmp_path), "config", "set", "does.not.exist", "x")
    assert code == 2
    assert payload["error"]["code"] == "INVALID_ARGUMENTS"

    _, payload = invoke_json("--project", str(tmp_path), "config", "list")
    assert "does" not in payload


# --- version compatibility -------------------------------------------------


def test_min_version_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Pin the installed version: an untagged checkout builds as 0.0.0, which the gate skips.
    monkeypatch.setattr(services, "installed_version", lambda: "1.0.0")
    init(tmp_path)
    assert invoke("--project", str(tmp_path), "config", "set", "cli.min_version", "99.0.0").exit_code == 0

    code, payload = invoke_json("--project", str(tmp_path), "status")
    assert code == 6
    assert payload["error"]["code"] == "CLI_TOO_OLD"
    assert "uv tool upgrade" in payload["error"]["action"]

    monkeypatch.setattr(services, "installed_version", lambda: "99.0.0")
    code, _ = invoke_json("--project", str(tmp_path), "status")
    assert code == 0


# --- doctor ------------------------------------------------------------------


def test_doctor_reports_a_missing_project(tmp_path: Path) -> None:
    code, payload = invoke_json("--project", str(tmp_path), "doctor")
    assert code == 0
    names = [check["name"] for check in payload["checks"]]
    assert names[:3] == ["python", "cli_version", "project"]
    project = payload["checks"][2]
    assert project["ok"] is True  # doctor outside a project is not a failure
    assert "outside a project" in project["detail"]
    assert "config" not in names


def test_doctor_reports_incompatible_cli_instead_of_failing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services, "installed_version", lambda: "1.0.0")
    init(tmp_path)
    invoke("--project", str(tmp_path), "config", "set", "cli.min_version", "99.0.0")

    code, payload = invoke_json("--project", str(tmp_path), "doctor")
    assert code == 0
    compat = next(check for check in payload["checks"] if check["name"] == "cli_compat")
    assert compat["ok"] is False
    assert "99.0.0" in compat["detail"]


# --- errors --------------------------------------------------------------------


def test_human_error_goes_to_stderr(tmp_path: Path) -> None:
    result = invoke("--project", str(tmp_path), "status")
    assert result.exit_code == 4
    assert result.stdout == ""
    assert "Error:" in result.stderr
