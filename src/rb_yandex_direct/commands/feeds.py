"""`yd feeds` — товарные фиды (сервис Feeds) для смарт-баннеров и динамических объявлений."""

from __future__ import annotations

import base64
from enum import StrEnum
from pathlib import Path
from typing import Any

import typer

from .. import output
from ..core import services
from ..core.errors import InvalidArguments
from ._common import FromJsonOption, IdsArgument, emit_list, mutate, read_json

app = output.group("Товарные фиды: список, создание по ссылке или файлом, изменение, удаление.")


class BusinessType(StrEnum):
    RETAIL = "RETAIL"
    HOTELS = "HOTELS"
    REALTY = "REALTY"
    AUTOMOBILES = "AUTOMOBILES"
    FLIGHTS = "FLIGHTS"
    OTHER = "OTHER"


COLUMNS = [
    ("Id", "Id"),
    ("Название", "Name"),
    ("Тип", "BusinessType"),
    ("Источник", lambda f: (f.get("UrlFeed") or {}).get("Url") or (f.get("FileFeed") or {}).get("Filename")),
    ("Статус", "Status"),
    ("Товаров", "NumberOfItems"),
    ("Обновлён", "UpdatedAt"),
]

UrlOption = typer.Option(None, "--url", help="Ссылка на фид (фид по ссылке Директ обновляет сам).")
FileOption = typer.Option(None, "--file", help="Файл фида (XML/YML/CSV) — загружается целиком.")
FeedLoginOption = typer.Option(None, "--feed-login", help="Логин HTTP-авторизации для ссылки на фид.")
FeedPasswordOption = typer.Option(
    None,
    "--feed-password",
    envvar="YANDEX_DIRECT_FEED_PASSWORD",
    help="Пароль HTTP-авторизации для ссылки (лучше через YANDEX_DIRECT_FEED_PASSWORD, не в истории shell).",
)
RemoveUtmOption = typer.Option(
    None, "--remove-utm/--keep-utm", help="Убирать ли UTM-метки из ссылок фида (RemoveUtmTags)."
)


def _source(
    url: str | None, file: str | None, login: str | None, password: str | None, remove_utm: bool | None
) -> dict[str, Any]:
    if url and file:
        raise InvalidArguments("Источник фида — либо --url, либо --file.")
    if file:
        if login or password or remove_utm is not None:
            raise InvalidArguments("--feed-login/--feed-password/--remove-utm — только для --url.")
        path = Path(file)
        try:
            data = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError as exc:
            raise InvalidArguments(f"Не прочитать файл фида {file!r}: {exc}") from exc
        return {"FileFeed": {"Data": data, "Filename": path.name}}
    if url or login or password or remove_utm is not None:
        feed: dict[str, Any] = {}
        if url:
            feed["Url"] = url
        if login:
            feed["Login"] = login
        if password:
            feed["Password"] = password
        if remove_utm is not None:
            feed["RemoveUtmTags"] = "YES" if remove_utm else "NO"
        return {"UrlFeed": feed}
    return {}


def _masked(item: dict[str, Any]) -> dict[str, Any]:
    """Для вывода (dry-run и отчёт): пароль ссылки и содержимое файла заменены заглушками."""
    preview = dict(item)
    if "Password" in preview.get("UrlFeed", {}):
        preview["UrlFeed"] = {**preview["UrlFeed"], "Password": "***"}
    if "FileFeed" in preview:
        size = len(preview["FileFeed"]["Data"])
        preview["FileFeed"] = {**preview["FileFeed"], "Data": f"<base64, {size} символов>"}
    return preview


@app.command("list")
@output.guard
def list_feeds(
    ctx: typer.Context,
    ids: list[int] = typer.Option(None, "--id", help="Только эти фиды (повторяемая)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Товарные фиды кабинета: источник, статус обработки, число товаров, кампании.

    --json: {"ok": true, "count": N, "feeds": [{Id, Name, BusinessType, SourceType, Status,
    NumberOfItems, UpdatedAt, CampaignIds, UrlFeed|FileFeed}]}.

    Example: {cli} feeds list
    """
    items = services.run(services.direct(ctx.obj).list_feeds(ids=ids or None))
    emit_list(ctx, "feeds", items, COLUMNS, title="Фиды")


@app.command("add")
@output.guard
def add(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Название фида."),
    business_type: BusinessType = typer.Option(BusinessType.RETAIL, "--business-type", help="Тип бизнеса фида."),
    url: str = UrlOption,
    file: str = FileOption,
    feed_login: str = FeedLoginOption,
    feed_password: str = FeedPasswordOption,
    remove_utm: bool = RemoveUtmOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Добавить фид по ссылке (--url) или файлом (--file).

    Example: {cli} feeds add --name Каталог --url https://example.com/feed.xml --dry-run
    """
    source = _source(url, file, feed_login, feed_password, remove_utm)
    if not source:
        raise InvalidArguments("Укажите источник фида: --url или --file.")
    item = {
        "Name": name,
        "BusinessType": business_type.value,
        "SourceType": "URL" if "UrlFeed" in source else "FILE",
        **source,
    }
    mutate(
        ctx,
        title=f"Добавить фид «{name}»",
        service="feeds",
        method="add",
        params={"Feeds": [_masked(item)]},
        confirm=confirm,
        call=lambda: services.direct(ctx.obj).call("feeds", "add", {"Feeds": [item]}),
    )


@app.command("update")
@output.guard
def update(
    ctx: typer.Context,
    feed_id: int = typer.Argument(..., help="Id фида."),
    name: str = typer.Option(None, "--name", help="Новое название."),
    url: str = UrlOption,
    file: str = FileOption,
    feed_login: str = FeedLoginOption,
    feed_password: str = FeedPasswordOption,
    remove_utm: bool = RemoveUtmOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить фид: название, ссылку и её авторизацию, UTM, или загрузить новый файл.

    Тип источника (ссылка/файл) у фида не меняется.

    Example: {cli} feeds update 7001 --url https://example.com/feed-v2.xml --dry-run
    """
    item: dict[str, Any] = {"Id": feed_id, **_source(url, file, feed_login, feed_password, remove_utm)}
    if name:
        item["Name"] = name
    if len(item) == 1:
        raise InvalidArguments("Нечего менять: укажите --name, --url, --file или параметры ссылки.")
    mutate(
        ctx,
        title=f"Изменить фид {feed_id}",
        service="feeds",
        method="update",
        params={"Feeds": [_masked(item)]},
        confirm=confirm,
        call=lambda: services.direct(ctx.obj).call("feeds", "update", {"Feeds": [item]}),
    )


@app.command("delete")
@output.guard
def delete(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить фиды — необратимо; фид, к которому привязаны кампании, API не удалит.

    Example: {cli} feeds delete 7001 --dry-run
    """
    mutate(
        ctx,
        title=f"Удалить фиды {', '.join(map(str, ids))}",
        service="feeds",
        method="delete",
        params={"SelectionCriteria": {"Ids": ids}},
        confirm=confirm,
    )


@app.command("add-json")
@output.guard
def add_json(
    ctx: typer.Context,
    from_json: str = FromJsonOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Добавить фиды из JSON: список FeedAddItem или {"Feeds": [...]}.

    Example: {cli} feeds add-json --from-json feeds.json --dry-run
    """
    _json(ctx, "add", "Добавить", from_json, confirm)


@app.command("update-json")
@output.guard
def update_json(
    ctx: typer.Context,
    from_json: str = FromJsonOption,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить фиды из JSON: список FeedUpdateItem (с Id) или {"Feeds": [...]}.

    Example: {cli} feeds update-json --from-json feeds.json --dry-run
    """
    _json(ctx, "update", "Изменить", from_json, confirm)


def _json(ctx: typer.Context, method: str, verb: str, path: str, confirm: bool) -> None:
    data = read_json(path)
    items = data.get("Feeds") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise InvalidArguments('Ожидается непустой список фидов или {"Feeds": [...]}.')
    mutate(
        ctx,
        title=f"{verb} фиды: {len(items)} шт.",
        service="feeds",
        method=method,
        params={"Feeds": items},
        confirm=confirm,
    )
