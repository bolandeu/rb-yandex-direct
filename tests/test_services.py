from __future__ import annotations

from pathlib import Path

import pytest

from rb_yandex_direct.core import services
from rb_yandex_direct.core.errors import CliTooOld, ProjectNotInitialized
from rb_yandex_direct.core.models import ProjectConfig


def test_find_project_root_walks_up(tmp_path: Path) -> None:
    services.init_project(tmp_path, "demo")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert services.find_project_root(nested) == tmp_path.resolve()


def test_require_project_root_raises_when_absent(tmp_path: Path) -> None:
    with pytest.raises(ProjectNotInitialized):
        services.require_project_root(tmp_path)


def test_config_round_trip(tmp_path: Path) -> None:
    config = services.init_project(tmp_path, "demo")
    config.direct.login = "custom"
    services.save_config(tmp_path, config)
    assert services.load_config(tmp_path).direct.login == "custom"
    assert services.config_path(tmp_path).is_file()


def test_check_cli_compat(monkeypatch: pytest.MonkeyPatch) -> None:
    config = ProjectConfig(name="demo")
    config.cli.min_version = "1.2.0"

    monkeypatch.setattr(services, "installed_version", lambda: "1.2.0")
    services.check_cli_compat(config)

    monkeypatch.setattr(services, "installed_version", lambda: "1.1.9")
    with pytest.raises(CliTooOld) as excinfo:
        services.check_cli_compat(config)
    assert excinfo.value.exit_code == 6

    monkeypatch.setattr(services, "installed_version", lambda: None)  # bare source run: nothing to compare
    services.check_cli_compat(config)

    monkeypatch.setattr(services, "installed_version", lambda: "0.0.0.post3.dev0+g1a2b3c4")  # no tag yet: dev build
    services.check_cli_compat(config)
