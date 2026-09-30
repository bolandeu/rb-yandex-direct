from __future__ import annotations

from pydantic import BaseModel, Field


class DirectConfig(BaseModel):
    """Кабинет по умолчанию для каталога проекта (клиента): `--login` и env важнее."""

    login: str | None = None
    sandbox: bool = False


class OutputConfig(BaseModel):
    format: str = "human"


class CliCompat(BaseModel):
    min_version: str = "0.1.0"


class ProjectConfig(BaseModel):
    version: int = 1
    name: str
    direct: DirectConfig = Field(default_factory=DirectConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    cli: CliCompat = Field(default_factory=CliCompat)
