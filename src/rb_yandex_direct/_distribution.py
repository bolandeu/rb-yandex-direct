# Rendered by copier from the `dist_name` answer: the [project] name in
# pyproject.toml (standard §10: `rb-<slug>`), which may differ from this
# import package's name. importlib.metadata finds this package's version,
# summary and console script by it; an editable install (`uv sync`) can't be
# mapped from package to distribution at runtime, so it is written down here.
# tests/test_cli.py fails if it drifts from pyproject.toml.
DIST_NAME = "rb-yandex-direct"
# The previous distribution name during a rename (standard §10): an install made
# under it (not yet reinstalled) still finds its own version. Drop it once
# every machine has the new name.
DIST_NAME_LEGACY: str | None = None
