"""Tests of the CLI as a whole: the distribution name, root and group help, the output layer's errors and exit codes,
and the built-in commands.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
import typer
import yaml
from typer.testing import CliRunner

from rb_yandex_direct import output
from rb_yandex_direct._distribution import DIST_NAME
from rb_yandex_direct.cli import app
from rb_yandex_direct.constants import PROFILE
from rb_yandex_direct.core import errors, services
from rb_yandex_direct.core.errors import InvalidArguments

runner = CliRunner()


def invoke(*args: str, **kwargs):
    return runner.invoke(app, list(args), **kwargs)


def plain(text: str) -> str:
    """The text without ANSI colour codes: CI forces Rich colours the Mac does not."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def invoke_json(*args: str, **kwargs) -> tuple[int, dict]:
    """Run a command with --json and parse stdout — the contract agents rely on."""
    result = invoke(*args, "--json", **kwargs)
    assert result.stdout.strip(), f"no stdout for {args!r}; stderr: {result.stderr}"
    return result.exit_code, json.loads(result.stdout)


def init(tmp_path: Path, name: str = "demo") -> None:
    assert invoke("--project", str(tmp_path), "init", "--name", name).exit_code == 0


# --- names ----------------------------------------------------------------------


def test_distribution_name_is_declared_once() -> None:
    """Only _distribution.py assigns DIST_NAME; a merge that re-declares it elsewhere would silently win."""
    src = Path(__file__).resolve().parents[1] / "src" / "rb_yandex_direct"
    declaring = sorted(
        str(path.relative_to(src))
        for path in src.rglob("*.py")
        if re.search(r"^DIST_NAME\s*[:=]", path.read_text(), re.M)
    )
    assert declaring == ["_distribution.py"]


def test_version_falls_back_to_legacy_distribution_name(monkeypatch: pytest.MonkeyPatch) -> None:
    from rb_yandex_direct.core import version

    installed = version.installed_version()
    monkeypatch.setattr(version, "DIST_NAME", "no-such-distribution-xyz")
    monkeypatch.setattr(version, "DIST_NAME_LEGACY", DIST_NAME)  # an install made under the old name
    assert version.installed_version() == installed
    monkeypatch.setattr(version, "DIST_NAME_LEGACY", None)
    assert version.installed_version() is None


def test_distribution_name_matches_pyproject() -> None:
    """_distribution.DIST_NAME is how importlib.metadata finds this package; it must equal [project] name."""
    pyproject = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    assert pyproject["project"]["name"] == DIST_NAME


def test_install_section_matches_copier_answers() -> None:
    """[tool.rb.install] is rendered from the copier answers: users split on commas, mac as a bool.

    extras is not a copier answer: a hand-added one only has to be a list of strings.
    """
    root = Path(__file__).resolve().parents[1]
    install = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["rb"]["install"]
    answers = yaml.safe_load((root / ".copier-answers.yml").read_text())
    users = [name.strip() for name in answers["install_homeserver_users"].split(",") if name.strip()]
    assert install["homeserver"] == users
    assert install["mac"] is answers["install_mac"]
    extras = install.get("extras", [])
    assert isinstance(extras, list) and all(isinstance(extra, str) for extra in extras)


# --- help-on-no-args -------------------------------------------------------


def test_bare_invocation_shows_help_and_exits_zero() -> None:
    result = invoke()
    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_bare_group_shows_help_and_exits_zero() -> None:
    result = invoke("auth")
    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "Missing command" not in result.output


# --- init / status / config ------------------------------------------------


def test_init_and_status(tmp_path: Path) -> None:
    init(tmp_path)
    code, payload = invoke_json("--project", str(tmp_path), "status")
    assert code == 0
    assert payload["ok"] is True
    assert payload["project"] == "demo"


def test_init_is_idempotent_without_force(tmp_path: Path) -> None:
    init(tmp_path)
    invoke("--project", str(tmp_path), "config", "set", "direct.login", "custom")

    code, payload = invoke_json("--project", str(tmp_path), "init", "--name", "ignored")
    assert code == 0
    assert payload["already_initialized"] is True

    _, payload = invoke_json("--project", str(tmp_path), "config", "get", "direct.login")
    assert payload["value"] == "custom"


def test_init_force_resets_config(tmp_path: Path) -> None:
    init(tmp_path)
    invoke("--project", str(tmp_path), "config", "set", "direct.login", "custom")

    code, payload = invoke_json("--project", str(tmp_path), "init", "--name", "demo", "--force")
    assert code == 0
    assert payload["already_initialized"] is False

    _, payload = invoke_json("--project", str(tmp_path), "config", "get", "direct.login")
    assert payload["value"] is None


def test_status_without_init_fails(tmp_path: Path) -> None:
    code, payload = invoke_json("--project", str(tmp_path), "status")
    assert code == 4
    assert payload["ok"] is False
    assert payload["error"]["code"] == "PROJECT_NOT_INITIALIZED"
    assert "init" in payload["error"]["action"]


def test_config_get_set_round_trip(tmp_path: Path) -> None:
    init(tmp_path)
    assert invoke("--project", str(tmp_path), "config", "set", "direct.login", "custom").exit_code == 0
    code, payload = invoke_json("--project", str(tmp_path), "config", "get", "direct.login")
    assert code == 0
    assert payload["value"] == "custom"


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


def test_doctor_json() -> None:
    code, payload = invoke_json("doctor")
    assert code == 0
    names = [check["name"] for check in payload["checks"]]
    assert names[:3] == ["python", "cli_version", "project"]
    assert payload["healthy"] is False  # no project here


def test_doctor_reports_config_parse_error(tmp_path: Path) -> None:
    init(tmp_path)
    (tmp_path / ".yd" / "config.toml").write_text("this is not valid toml [[[")

    code, payload = invoke_json("--project", str(tmp_path), "doctor")
    assert code == 0
    config_check = next(check for check in payload["checks"] if check["name"] == "config")
    assert config_check["ok"] is False
    assert config_check["detail"]


def test_doctor_reports_incompatible_cli_instead_of_failing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services, "installed_version", lambda: "1.0.0")
    init(tmp_path)
    invoke("--project", str(tmp_path), "config", "set", "cli.min_version", "99.0.0")

    code, payload = invoke_json("--project", str(tmp_path), "doctor")
    assert code == 0
    compat = next(check for check in payload["checks"] if check["name"] == "cli_compat")
    assert compat["ok"] is False
    assert "99.0.0" in compat["detail"]


def test_doctor_prints_one_line_per_check_for_a_human() -> None:
    result = invoke("doctor")
    assert result.exit_code == 0
    assert plain(result.stdout).splitlines()[0] == "✓ python"


# --- error handling contract ---------------------------------------------------


def _app_with(command):
    """A throwaway app with the real ctx.obj plumbing, for exercising output.guard."""
    test_app = typer.Typer()

    @test_app.callback()
    def _root(
        ctx: typer.Context,
        json_output: bool = output.JsonOption,
        verbose: bool = output.VerboseOption,
        non_interactive: bool = output.NonInteractiveOption,
    ) -> None:
        ctx.ensure_object(dict)
        ctx.obj["json"] = json_output
        ctx.obj["verbose"] = verbose
        ctx.obj["non_interactive"] = non_interactive

    test_app.command("cmd")(output.guard(command))
    return test_app


def test_error_message_and_action_in_square_brackets_reach_stderr_whole() -> None:
    def fail(ctx: typer.Context) -> None:
        raise errors.CliError("PATH_NOT_FOUND", "[library] path not found", action="use [a-z0-9-]")

    result = runner.invoke(_app_with(fail), ["cmd"])
    assert result.exit_code == 1
    assert "[library] path not found" in plain(result.stderr)
    assert "use [a-z0-9-]" in plain(result.stderr)


def test_verbose_line_in_square_brackets_reaches_stderr_whole() -> None:
    def progress(ctx: typer.Context) -> None:
        output.vecho(ctx, "step [1/3] of [a-z0-9-]")

    result = runner.invoke(_app_with(progress), ["--verbose", "cmd"])
    assert "step [1/3] of [a-z0-9-]" in plain(result.stderr)


@pytest.mark.parametrize(
    ("error", "code", "exit_code"),
    [
        (errors.InvalidArguments("bad"), "INVALID_ARGUMENTS", 2),
        (errors.AuthRequired(PROFILE), "AUTH_REQUIRED", 3),
        (errors.CredentialsUnhealthy(PROFILE, {"direct": "invalid"}), "CREDENTIALS_UNHEALTHY", 3),
        (errors.ProjectNotInitialized("/work"), "PROJECT_NOT_INITIALIZED", 4),
        (errors.ProviderError("demo", "down", status=503), "PROVIDER_ERROR", 5),
        (errors.DatabaseUnavailable("down"), "DATABASE_UNAVAILABLE", 5),
        (errors.CliTooOld("1.0.0", "2.0.0"), "CLI_TOO_OLD", 6),
        (errors.DatabaseTooNew("0009"), "CLI_TOO_OLD", 6),
        (errors.DatabaseNotMigrated(None, "0002"), "DATABASE_NOT_MIGRATED", 1),
        (errors.DependencyTooOld("serp", None, "0.3"), "DEPENDENCY_TOO_OLD", 1),
        (errors.CredentialStoreUnavailable(PROFILE, "locked"), "CREDENTIAL_STORE_UNAVAILABLE", 1),
        (errors.Aborted("Delete everything"), "ABORTED", 1),
    ],
    ids=lambda value: type(value).__name__ if isinstance(value, errors.CliError) else None,
)
def test_each_error_has_the_code_and_exit_code_of_the_standard(
    error: errors.CliError, code: str, exit_code: int
) -> None:
    """The error codes table of the Standard (Errors): the code in the envelope and the exit code."""
    payload = error.to_dict()
    assert (payload["code"], error.exit_code) == (code, exit_code)
    assert payload["message"]


def test_report_with_a_problem_keeps_the_payload() -> None:
    """output.emit_report: data plus ok=false + error, exit code from the problem (auth status uses it)."""

    def report(ctx: typer.Context) -> None:
        render = lambda d: output.human.echo(f"items: {d['items']}")  # noqa: E731
        output.emit_report(ctx, {"items": [1]}, render, InvalidArguments("bad"))

    result = runner.invoke(_app_with(report), ["--json", "cmd"])
    payload = json.loads(result.stdout)
    assert (result.exit_code, payload["ok"], payload["items"], payload["error"]["code"]) == (
        2,
        False,
        [1],
        "INVALID_ARGUMENTS",
    )
    result = runner.invoke(_app_with(report), ["cmd"])
    assert result.exit_code == 2
    assert "items: [1]" in plain(result.stdout)
    assert "bad" in result.stderr


def test_unexpected_exception_still_yields_json_envelope() -> None:
    def boom(ctx: typer.Context) -> None:
        raise RuntimeError("kaboom")

    result = runner.invoke(_app_with(boom), ["--json", "cmd"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "UNEXPECTED"
    assert "kaboom" in payload["error"]["message"]
    assert "Traceback" not in result.stdout


def test_unexpected_exception_prints_traceback_only_with_verbose() -> None:
    def boom(ctx: typer.Context) -> None:
        raise RuntimeError("kaboom")

    quiet = runner.invoke(_app_with(boom), ["cmd"])
    assert quiet.exit_code == 1
    assert "Traceback" not in quiet.stderr
    assert "kaboom" in quiet.stderr  # human error goes to stderr, not stdout
    assert quiet.stdout == ""

    loud = runner.invoke(_app_with(boom), ["--verbose", "cmd"])
    assert "Traceback" in loud.stderr or "RuntimeError" in loud.stderr


@pytest.mark.parametrize(
    "args",
    [
        ("doctor", "--json", "--no-such-option"),
        ("--json", "--no-such-option"),
        ("--json", "auth", "status", "--provider"),
    ],
)
def test_usage_error_under_json_is_the_error_envelope(args: tuple[str, ...]) -> None:
    """An unknown option or a missing value (Click's usage errors) under --json: the envelope on stdout, exit 2."""
    result = invoke(*args)
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert (payload["ok"], payload["error"]["code"]) == (False, "INVALID_ARGUMENTS")
    assert payload["error"]["message"]


def test_usage_error_without_json_stays_on_stderr() -> None:
    result = invoke("doctor", "--no-such-option")
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "--no-such-option" in plain(result.stderr)


def test_require_confirmation_blocks_non_interactive_without_confirm() -> None:
    def destroy(ctx: typer.Context, confirm: bool = output.ConfirmOption) -> None:
        output.require_confirmation(ctx, "Delete everything", confirm=confirm)
        print("destroyed")

    blocked = runner.invoke(_app_with(destroy), ["--json", "--non-interactive", "cmd"])
    assert blocked.exit_code == 2
    assert json.loads(blocked.stdout)["error"]["code"] == "INVALID_ARGUMENTS"

    # --confirm bypasses the prompt/non-interactive check entirely.
    allowed = runner.invoke(_app_with(destroy), ["--non-interactive", "cmd", "--confirm"])
    assert allowed.exit_code == 0
    assert "destroyed" in allowed.stdout


def test_declined_confirmation_is_a_structured_abort() -> None:
    def destroy(ctx: typer.Context) -> None:
        output.require_confirmation(ctx, "Delete everything", confirm=False)
        raise AssertionError("must not get here")

    result = runner.invoke(_app_with(destroy), ["--json", "cmd"], input="n\n")
    assert result.exit_code == 1
    # The prompt itself precedes the envelope on stdout; the envelope is the last line.
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["error"]["code"] == "ABORTED"


# --- skill / run ---------------------------------------------------------------


def test_skill_install_writes_to_project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    code, payload = invoke_json("skill", "install", "--tool", "claude-code", "--project")
    assert code == 0
    installed = tmp_path / ".claude" / "skills" / "yd" / "SKILL.md"
    assert installed.is_file()
    assert "name: yd" in installed.read_text()
    assert payload["path"] == str(installed)
