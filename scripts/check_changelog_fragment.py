#!/usr/bin/env python3
"""Warn (never block) when a commit changes the package but no changelog fragment
exists for it — neither staged now nor already added on this branch.

Every user-visible change needs a `changelog.d/+<slug>.<type>.md` fragment
(`uv run towncrier create +<slug>.<type>.md -c "..."`); `scripts/release.py`
assembles them into CHANGELOG.md. The strict check is the gate
(`scripts/release.py --check`, "changelog fragment" step); this is the
local reminder. It never fails the commit, it just prints to stderr.

Runs from the versioned `.githooks/pre-commit` (`scripts/install_hooks.sh`
points git at it once per clone).
"""

from __future__ import annotations

import subprocess
import sys

BASE = "origin/main"

# Changes that never need a changelog fragment (standard §3): they don't
# change what users of the package get. Keep this list identical in
# scripts/release.py and scripts/check_changelog_fragment.py (a test checks).
NO_FRAGMENT_NEEDED = ("uv.lock", ".github/", "scripts/", "tests/", ".githooks/", ".claude/", "AGENTS.md", "CLAUDE.md")


def needs_fragment(path: str) -> bool:
    """Whether a change to `path` (repo-relative, POSIX) is user-visible enough to need a fragment."""
    return not any(path == entry or (entry.endswith("/") and path.startswith(entry)) for entry in NO_FRAGMENT_NEEDED)


def project_table_changed(old: str | None, new: str | None) -> bool:
    """Whether pyproject.toml's [project] table differs — the package metadata users get.

    Everything else in pyproject.toml ([tool.*], [dependency-groups], build
    settings) is tooling and needs no changelog fragment (standard §3).
    Unreadable or missing on either side counts as changed.
    """
    try:
        import tomllib
    except ModuleNotFoundError:  # a pre-commit hook's python3 older than 3.11
        return True
    if old is None or new is None:
        return True
    try:
        return tomllib.loads(old).get("project") != tomllib.loads(new).get("project")
    except tomllib.TOMLDecodeError:
        return True


def _git_lines(*args: str) -> list[str]:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return result.stdout.splitlines() if result.returncode == 0 else []


def _is_fragment(path: str) -> bool:
    return path.startswith("changelog.d/") and not path.rsplit("/", 1)[-1].startswith(".")


def _tooling_only_pyproject(path: str) -> bool:
    if path != "pyproject.toml":
        return False
    head, staged = _git_lines("show", "HEAD:pyproject.toml"), _git_lines("show", ":pyproject.toml")
    return not project_table_changed("\n".join(head) if head else None, "\n".join(staged) if staged else None)


def main() -> int:
    staged = _git_lines("diff", "--cached", "--name-only")
    # Release commits (CHANGELOG.md assembled) and fragment-only commits need nothing more.
    if not staged or "CHANGELOG.md" in staged or any(_is_fragment(p) for p in staged):
        return 0
    if not any(needs_fragment(p) for p in staged if not _tooling_only_pyproject(p)):
        return 0
    if any(_is_fragment(p) for p in _git_lines("diff", "--name-only", "--diff-filter=A", f"{BASE}...HEAD")):
        return 0
    print(
        "changelog: this commit changes the package but the branch has no changelog.d/ fragment. If the change "
        'is user-visible, add one: uv run towncrier create +<slug>.<type>.md -c "..." '
        "(type: added/changed/deprecated/removed/fixed/security).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
