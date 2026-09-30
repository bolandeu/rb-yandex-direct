"""`yd dict` — справочники Директа (сервис Dictionaries)."""

from __future__ import annotations

from enum import StrEnum

import typer

from .. import output
from ..core import services
from ..core.errors import InvalidArguments
from ..providers.direct import DICTIONARY_NAMES
from ._common import emit_list, emit_object

app = output.group("Справочники: регионы, валюты, часовые пояса, интересы, категории, константы.")

DictionaryName = StrEnum("DictionaryName", {n: n for n in DICTIONARY_NAMES})


@app.command("get")
@output.guard
def get(
    ctx: typer.Context,
    names: list[DictionaryName] = typer.Argument(..., help="Имена справочников (см. `dict names`)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Один или несколько справочников целиком (dictionaries.get).

    Справочники большие (GeoRegions — десятки тысяч записей): для поиска региона
    удобнее `dict geo-regions`. --json: {"ok": true, "dictionaries": {"<Имя>": [...]}}.

    Example: {cli} dict get Currencies TimeZones --json
    """
    data = services.run(services.direct(ctx.obj).get_dictionaries([n.value for n in names]))
    emit_object(ctx, "dictionaries", data, title=f"Справочники: {', '.join(n.value for n in names)}")


@app.command("geo-regions")
@output.guard
def geo_regions(
    ctx: typer.Context,
    name: str = typer.Option(None, "--name", help="Часть названия региона, например Москв."),
    region_ids: list[int] = typer.Option(None, "--id", help="Id региона (повторяемая)."),
    exact: list[str] = typer.Option(None, "--exact", help="Точное название региона (повторяемая)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Найти регионы по названию или Id: Id для таргетинга групп и корректировок (dictionaries.getGeoRegions).

    --json: {"ok": true, "count": N, "regions": [{GeoRegionId, GeoRegionName, ParentGeoRegionNames}]}.

    Example: {cli} dict geo-regions --name Казань
    """
    if not (name or region_ids or exact):
        raise InvalidArguments("Укажите --name, --id или --exact.")
    items = services.run(services.direct(ctx.obj).get_geo_regions(name, region_ids, exact))
    columns = [
        ("Id", "GeoRegionId"),
        ("Регион", "GeoRegionName"),
        ("Входит в", lambda r: " / ".join((r.get("ParentGeoRegionNames") or {}).get("Items") or [])),
    ]
    emit_list(ctx, "regions", items, columns, title="Регионы")


@app.command("names")
@output.guard
def names(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Имена справочников, которые принимает `dict get` (без запроса к API).

    Example: {cli} dict names
    """
    output.emit_success(
        ctx,
        {"count": len(DICTIONARY_NAMES), "names": DICTIONARY_NAMES},
        render_human=lambda d: output.human.echo("\n".join(d["names"])),
    )
