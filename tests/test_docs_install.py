"""The install lines of the readme and of the bundled skill, if any, fit the repository_url of the project."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = "--index https://homeserver.tailee01ab.ts.net:3000/api/packages/bolandeu/pypi/simple"
DOCS = {"readme": ROOT / "README.md"}
DOCS.update(("skill", path) for path in ROOT.glob("src/*/data/SKILL.md"))  # the package skill is an optional part


def _repository_url() -> str:
    return yaml.safe_load((ROOT / ".copier-answers.yml").read_text())["repository_url"]


def _texts() -> dict[str, str]:
    return {name: path.read_text() for name, path in DOCS.items()}


def test_no_jinja_tag_is_left_in_the_docs():
    for name, text in _texts().items():
        assert "{{" not in text and "{%" not in text, name


def test_gitea_repository_gets_the_registry_line_and_no_github_advice():
    url = _repository_url()
    if not url or url.startswith("https://github.com/"):
        return
    for name, text in _texts().items():
        assert REGISTRY in text, name
        assert f"git+{url}.git@vX.Y.Z" in text, name
        assert "git@github.com" not in text, name
        assert "gh auth" not in text, name


def test_github_or_blank_repository_keeps_the_ssh_line_and_gh_advice():
    url = _repository_url()
    if url and not url.startswith("https://github.com/"):
        return
    ssh = f"git+ssh://git@github.com/{url.removeprefix('https://github.com/') or '<owner>/<repo>'}.git@vX.Y.Z"
    for name, text in _texts().items():
        assert ssh in text, name
        assert "gh auth setup-git" in text, name
        assert REGISTRY not in text, name
