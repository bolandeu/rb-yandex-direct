"""The agent skills bundled in the package data.

The conventions skill is `data/SKILL.md` (frontmatter name = the CLI's name). A package may ship
extra skills, one per kind of work, as `data/skills/<name>/SKILL.md` (frontmatter name =
`<cli>-<name>`). `skill install`, `skill list` and `describe` read them from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable

from .version import cli_name

_PACKAGE_NAME = __name__.split(".")[0]
EXTRAS_DIR = "skills"


@dataclass(frozen=True)
class Skill:
    name: str  # the frontmatter name: also the directory it is installed into
    short_name: str  # what `skill install --skill` takes: the directory name of an extra skill
    description: str
    text: str


def _data() -> Traversable:
    return resources.files(f"{_PACKAGE_NAME}.data")


def frontmatter(text: str) -> dict[str, str]:
    """The `key: value` lines between the leading `---` lines; empty when there is no frontmatter."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    found: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return found
        key, _, value = line.partition(":")
        if value:
            found[key.strip()] = value.strip()
    return {}  # never closed


def _skill(text: str, short_name: str) -> Skill:
    meta = frontmatter(text)
    return Skill(meta["name"], short_name, meta.get("description", ""), text)


def conventions() -> Skill:
    return _skill(_data().joinpath("SKILL.md").read_text(), cli_name())


def bundled() -> list[Skill]:
    """The conventions skill, then the extra skills by directory name."""
    found = [conventions()]
    extras = _data().joinpath(EXTRAS_DIR)
    if extras.is_dir():
        for entry in sorted(extras.iterdir(), key=lambda e: e.name):
            if entry.joinpath("SKILL.md").is_file():
                found.append(_skill(entry.joinpath("SKILL.md").read_text(), entry.name))
    return found
