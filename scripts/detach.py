#!/usr/bin/env python3
"""Run a long command detached from the session, so interrupting the agent doesn't kill it.

An agent's shell command dies with the agent's turn: an interrupt ("Request
interrupted by user", e.g. an incoming herdr message) kills its process group,
and the work is redone from scratch. A detached run lives in a session of its own
(`start_new_session=True` — macOS has no `setsid`), outlives the turn and the
terminal, and leaves its state in files the next turn can read.

    scripts/run_detached.sh <label> <command> [args...]   # start; prints the pid
    scripts/runs_status.sh [<label>] [--json]              # what runs, how it ended
    python3 scripts/detach.py stop <label>                 # SIGTERM to the whole run

Any command: the CLI itself, `uv run pytest`, `scripts/pg_test.sh`, a long import.
Per run, in `<state dir>/runs/` (the tool's user state dir; RUNS_DIR overrides):
`<label>.pid`, `<label>.log` (stdout — the progress), `<label>.stderr` (errors and
tracebacks; empty in a normal run), `<label>.exit` (exit code and end time, written
when it ends — a run whose pid is gone without one was killed outright).

Standard library only, Python >= 3.9: it runs before (and without) the venv.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def tool_name() -> str:
    """The CLI name: the first `[project.scripts]` entry in pyproject.toml, else the repo directory's name.

    A regex, not tomllib: that's 3.11+, and the same python3 must find the same
    directory whichever version it is.
    """
    with contextlib.suppress(OSError):
        text = (ROOT / "pyproject.toml").read_text()
        if match := re.search(r'^\[project\.scripts\]\s*\n\s*"?([A-Za-z0-9_.-]+)"?\s*=', text, re.M):
            return match.group(1)
    return ROOT.name


def runs_dir() -> Path:
    """`<user state dir>/<tool>/runs`, as platformdirs' user_state_dir has it (no dependency on it here)."""
    if override := os.environ.get("RUNS_DIR"):
        return Path(override)
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or home / ".local" / "state")
    return base / tool_name() / "runs"


def _zombie(pid: int) -> bool:
    """Exited but not reaped by its parent (state Z). Where PID 1 never reaps (`tail -f /dev/null` in a CI job), a killed run stays one."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return (
            stat.rpartition(")")[2].split()[0] == "Z"
        )  # after the last ')': the command name may hold spaces and parentheses
    except OSError, IndexError:
        pass
    with contextlib.suppress(OSError):  # macOS has no /proc
        ps = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False)
        return ps.stdout.strip().startswith("Z")
    return False


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return not _zombie(pid)


def _pid(runs: Path, label: str) -> int | None:
    try:
        return int((runs / f"{label}.pid").read_text().strip())
    except OSError, ValueError:
        return None


def start(label: str, command: list[str]) -> int:
    if not LABEL.match(label):
        print(f"detach: label must be letters, digits, '.', '_' or '-': {label!r}", file=sys.stderr)
        return 2
    if not command:
        print("detach: no command given", file=sys.stderr)
        return 2
    runs = runs_dir()
    runs.mkdir(parents=True, exist_ok=True)
    if (pid := _pid(runs, label)) is not None and _alive(pid):
        print(f"detach: '{label}' is still running (pid {pid}); pick another label or stop it", file=sys.stderr)
        return 1
    for suffix in (".pid", ".exit", ".log", ".stderr", ".json"):
        (runs / f"{label}{suffix}").unlink(missing_ok=True)
    meta = {"label": label, "command": command, "cwd": os.getcwd(), "started": time.time()}
    (runs / f"{label}.json").write_text(json.dumps(meta, ensure_ascii=False))
    with contextlib.ExitStack() as files:  # not `with (a, b):` — that's 3.10+, and this runs on any python3
        out = files.enter_context(open(runs / f"{label}.log", "ab", buffering=0))
        err = files.enter_context(open(runs / f"{label}.stderr", "ab", buffering=0))
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "_supervise", str(runs), label, "--", *command],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            start_new_session=True,  # its own session and process group: an interrupt here doesn't reach it
        )
    (runs / f"{label}.pid").write_text(f"{process.pid}\n")
    print(f"started: {label} (pid {process.pid})")
    print(f"  progress: tail -f {runs / f'{label}.log'}")
    print(f"  status:   {ROOT / 'scripts' / 'runs_status.sh'} {label}")
    return 0


def _supervise(runs: Path, label: str, command: list[str]) -> int:
    """Inside the detached session: run the command, then record how it ended."""
    signal.signal(signal.SIGTERM, lambda *_: None)  # `stop` signals the group: let the command end, then record it
    try:
        code = subprocess.call(command)
    except OSError as exc:  # not found, not executable
        print(f"detach: can't run {command[0]!r}: {exc}", file=sys.stderr)
        code = 127
    (runs / f"{label}.exit").write_text(json.dumps({"code": code, "ended": time.time()}))
    return code


def _state(runs: Path, label: str) -> dict:
    meta: dict = {}
    with contextlib.suppress(OSError, ValueError):
        meta = json.loads((runs / f"{label}.json").read_text())
    pid = _pid(runs, label)
    result: dict = {"label": label, "pid": pid, "command": meta.get("command"), "started": meta.get("started")}
    try:
        ended = json.loads((runs / f"{label}.exit").read_text())
        result.update(state="done", exit_code=ended["code"], ended=ended["ended"])
    except OSError, ValueError, KeyError:
        result["state"] = "running" if pid is not None and _alive(pid) else "killed"
    stderr = runs / f"{label}.stderr"
    result["stderr_bytes"] = stderr.stat().st_size if stderr.exists() else 0
    return result


def _tail(path: Path, lines: int) -> list[str]:
    try:
        return path.read_text(errors="replace").splitlines()[-lines:]
    except OSError:
        return []


def status(label: str | None, as_json: bool) -> int:
    runs = runs_dir()
    labels = [label] if label else sorted(p.stem for p in runs.glob("*.pid"))
    states = [_state(runs, name) for name in labels if (runs / f"{name}.pid").exists()]
    if label and not states:
        print(f"detach: no run '{label}' in {runs}", file=sys.stderr)
        return 1
    if as_json:
        for state in states:
            state["log_tail"] = _tail(runs / f"{state['label']}.log", 5)
            state["stderr_tail"] = _tail(runs / f"{state['label']}.stderr", 5)
        print(json.dumps({"runs_dir": str(runs), "runs": states}, ensure_ascii=False))
        return 0
    if not states:
        print(f"no runs in {runs}")
    now = time.time()
    for state in states:
        took = (state.get("ended") or now) - (state["started"] or now)
        how = {"running": "running", "killed": "killed (no exit code)"}.get(state["state"])
        how = how or ("ok" if state["exit_code"] == 0 else f"failed, exit {state['exit_code']}")
        print(f"== {state['label']}: {how}, {took / 60:.1f} min, pid {state['pid']}")
        if state["command"]:
            print(f"   $ {' '.join(state['command'])}")
        for line in _tail(runs / f"{state['label']}.log", 3):
            print(f"   {line[:160]}")
        if state["stderr_bytes"]:
            print("   stderr:")
            for line in _tail(runs / f"{state['label']}.stderr", 5):
                print(f"     {line[:160]}")
    return 0


def stop(label: str) -> int:
    runs = runs_dir()
    pid = _pid(runs, label)
    if pid is None or not _alive(pid):
        print(f"detach: '{label}' is not running", file=sys.stderr)
        return 1
    os.killpg(pid, signal.SIGTERM)  # the supervisor leads its own process group: the command gets it too
    print(f"stopping: {label} (process group {pid})")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["_supervise"]:
        runs, label, _sep, *command = argv[1:]
        return _supervise(Path(runs), label, command)
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)
    p_start = sub.add_parser("start", help="start a detached run")
    p_start.add_argument("label")
    p_start.add_argument("command", nargs=argparse.REMAINDER)
    p_status = sub.add_parser("status", help="what runs and how it ended")
    p_status.add_argument("label", nargs="?")
    p_status.add_argument("--json", action="store_true")
    p_stop = sub.add_parser("stop", help="SIGTERM to a run's whole process group")
    p_stop.add_argument("label")
    args = parser.parse_args(argv)
    if args.action == "start":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        return start(args.label, command)
    if args.action == "status":
        return status(args.label, args.json)
    return stop(args.label)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
