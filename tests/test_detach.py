"""scripts/run_detached.sh / runs_status.sh / detach.py: long commands that outlive the agent's turn."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX sessions and process groups")


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    return tmp_path / "runs"


def sh(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SCRIPTS / script), *args], capture_output=True, text=True, check=False)  # noqa: S603


def status(label: str) -> dict:
    result = sh("runs_status.sh", label, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["runs"][0]


def wait_for(label: str, state: str, timeout: float = 15) -> dict:
    deadline = time.monotonic() + timeout
    while (current := status(label))["state"] != state:
        assert time.monotonic() < deadline, current
        time.sleep(0.1)
    return current


def load_detach():
    spec = importlib.util.spec_from_file_location("detach", SCRIPTS / "detach.py")
    assert spec is not None and spec.loader is not None
    detach = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(detach)
    return detach


def py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_a_run_records_output_errors_and_exit_code(runs: Path) -> None:
    code = "import sys; print('step 1'); print('boom', file=sys.stderr); sys.exit(3)"
    started = sh("run_detached.sh", "job", *py(code))
    assert started.returncode == 0, started.stderr
    assert "job" in started.stdout

    done = wait_for("job", "done")
    assert done["exit_code"] == 3
    assert done["log_tail"] == ["step 1"]
    assert done["stderr_tail"] == ["boom"]
    assert (runs / "job.pid").is_file()

    human = sh("runs_status.sh")
    assert "job: failed, exit 3" in human.stdout and "boom" in human.stdout


def test_the_run_is_in_its_own_session(runs: Path) -> None:
    sh("run_detached.sh", "session", *py("import os; print(os.getsid(0))"))
    run = wait_for("session", "done")
    assert int(run["log_tail"][0]) != os.getsid(0)  # an interrupt of this session doesn't reach it
    assert int(run["log_tail"][0]) == run["pid"]


def test_stop_ends_the_command_and_records_it(runs: Path) -> None:
    sh("run_detached.sh", "sleeper", "--", *py("import time; time.sleep(60)"))
    assert status("sleeper")["state"] == "running"
    again = sh("run_detached.sh", "sleeper", *py("pass"))
    assert again.returncode == 1 and "still running" in again.stderr

    stopped = subprocess.run([sys.executable, str(SCRIPTS / "detach.py"), "stop", "sleeper"], check=False)  # noqa: S603
    assert stopped.returncode == 0
    assert wait_for("sleeper", "done")["exit_code"] == -15  # SIGTERM


def test_killed_outright(runs: Path) -> None:
    sh("run_detached.sh", "victim", *py("import time; time.sleep(60)"))
    os.killpg(status("victim")["pid"], 9)
    assert "exit_code" not in wait_for("victim", "killed")  # SIGKILL leaves no exit record


def test_state_lives_in_the_tools_state_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RUNS_DIR", raising=False)
    detach = load_detach()
    pyproject = (SCRIPTS.parent / "pyproject.toml").read_text()
    assert f'\n{detach.tool_name()} = "' in pyproject.split("[project.scripts]")[1]
    assert detach.runs_dir().parts[-2:] == (detach.tool_name(), "runs")


def test_bad_input(runs: Path) -> None:
    assert sh("run_detached.sh", "../x", "true").returncode == 2
    assert sh("run_detached.sh", "nothing").returncode == 2
    assert sh("runs_status.sh", "missing").returncode == 1
    missing = sh("run_detached.sh", "ghost", "no-such-program-xyz")
    assert missing.returncode == 0
    assert wait_for("ghost", "done")["exit_code"] == 127


def exited(pid: int) -> None:
    """Wait until the child has exited, without reaping it: state Z (/proc on Linux, `ps` where there is no /proc)."""
    deadline = time.monotonic() + 10
    while not _state_z(pid):
        assert time.monotonic() < deadline, f"pid {pid} did not become a zombie"
        time.sleep(0.05)


def _state_z(pid: int) -> bool:
    if Path("/proc").is_dir():  # after the last ')': the command name may hold spaces and parentheses
        return Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0] == "Z"
    command = ["ps", "-o", "stat=", "-p", str(pid)]
    return subprocess.run(command, capture_output=True, text=True, check=False).stdout.startswith("Z")  # noqa: S603


def zombie() -> subprocess.Popen[bytes]:
    """A child that has exited and that nobody has waited for — what PID 1 `tail -f /dev/null` leaves behind."""
    child = subprocess.Popen(["true"])  # noqa: S607
    exited(child.pid)
    return child


def test_a_zombie_is_not_alive() -> None:
    child = zombie()
    try:
        assert not load_detach()._alive(child.pid)
    finally:
        child.wait()


def test_a_live_process_is_alive() -> None:
    child = subprocess.Popen(py("import time; time.sleep(60)"))  # noqa: S603
    try:
        assert load_detach()._alive(child.pid)
    finally:
        child.kill()
        child.wait()


def test_a_killed_run_whose_supervisor_is_not_reaped_is_killed(runs: Path) -> None:
    runs.mkdir()
    supervisor = subprocess.Popen(py("import time; time.sleep(60)"), start_new_session=True)  # noqa: S603
    (runs / "victim.pid").write_text(f"{supervisor.pid}\n")
    os.killpg(supervisor.pid, 9)
    exited(supervisor.pid)
    try:
        assert status("victim")["state"] == "killed"
    finally:
        supervisor.wait()
