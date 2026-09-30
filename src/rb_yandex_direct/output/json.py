from __future__ import annotations

import json

import typer


def emit(data: dict) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False))
