"""Медиа для объявлений: `yd images` (AdImages), `yd videos` (AdVideos), `yd creatives` (Creatives)."""

from __future__ import annotations

import base64
from enum import StrEnum
from pathlib import Path

import typer

from .. import output
from ..core import services
from ..core.errors import InvalidArguments
from ._common import emit_list, mutate

images_app = output.group("Изображения для объявлений: список, загрузка из файлов, удаление (сервис AdImages).")
videos_app = output.group("Видео для видеодополнений: загрузка по ссылке или из файла, статус (сервис AdVideos).")
creatives_app = output.group("Креативы: список и видеодополнения из загруженных видео (сервис Creatives).")


class ImageType(StrEnum):
    AUTO = "AUTO"
    REGULAR = "REGULAR"
    WIDE = "WIDE"
    FIXED_IMAGE = "FIXED_IMAGE"


class YesNo(StrEnum):
    YES = "YES"
    NO = "NO"


class CreativeType(StrEnum):
    IMAGE_CREATIVE = "IMAGE_CREATIVE"
    HTML5_CREATIVE = "HTML5_CREATIVE"
    VIDEO_EXTENSION_CREATIVE = "VIDEO_EXTENSION_CREATIVE"
    CPC_VIDEO_CREATIVE = "CPC_VIDEO_CREATIVE"
    CPM_VIDEO_CREATIVE = "CPM_VIDEO_CREATIVE"
    SMART_CREATIVE = "SMART_CREATIVE"


def _read_file(path: str) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise InvalidArguments(f"Не удалось прочитать файл {path!r}: {exc}") from exc


# --- images -------------------------------------------------------------------------------------


@images_app.command("list")
@output.guard
def images_list(
    ctx: typer.Context,
    hashes: list[str] = typer.Option(None, "--hash", help="Только эти изображения (повторяемая)."),
    associated: YesNo = typer.Option(None, "--associated", help="YES — привязанные к объявлениям, NO — свободные."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изображения, загруженные в кабинет.

    --json: {"ok": true, "count": N, "images": [{AdImageHash, Name, Type, Subtype, Associated, PreviewUrl, OriginalUrl}]}.

    Example: {cli} images list --associated NO --json
    """
    items = services.run(
        services.direct(ctx.obj).list_ad_images(
            hashes=hashes or None, associated=associated.value if associated else None
        )
    )
    columns = [("Хэш", "AdImageHash"), ("Имя", "Name"), ("Тип", "Type"), ("Привязано", "Associated")]
    emit_list(ctx, "images", items, columns, title="Изображения")


@images_app.command("add")
@output.guard
def images_add(
    ctx: typer.Context,
    paths: list[str] = typer.Argument(..., help="Файлы изображений (JPG, PNG, GIF), до 100 за вызов."),
    image_type: ImageType = typer.Option(ImageType.AUTO, "--type", help="Тип изображения; AUTO — по размерам."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Загрузить изображения из файлов; хэши из ответа привязываются к объявлениям (--image-hash).

    --dry-run показывает запрос без содержимого файлов (размер в байтах вместо base64).
    --json: отчёт изменения; хэши — в result.AddResults[].AdImageHash.

    Example: {cli} images add banner.png --confirm
    """
    if len(paths) > 100:
        raise InvalidArguments(f"Не более 100 файлов за вызов, получено {len(paths)}.")
    items = []
    preview = []
    for p in paths:
        data = _read_file(p)
        items.append(
            {"ImageData": base64.b64encode(data).decode("ascii"), "Name": Path(p).name, "Type": image_type.value}
        )
        preview.append({"ImageData": f"<{len(data)} байт>", "Name": Path(p).name, "Type": image_type.value})
    mutate(
        ctx,
        title=f"Загрузить изображения: {len(items)} шт.",
        service="adimages",
        method="add",
        params={"AdImages": preview},
        confirm=confirm,
        call=lambda: services.direct(ctx.obj).add_ad_images(items),
    )


@images_app.command("delete")
@output.guard
def images_delete(
    ctx: typer.Context,
    hashes: list[str] = typer.Argument(..., help="Хэши изображений через пробел."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить изображения по хэшам (привязанные к объявлениям API не удалит).

    Example: {cli} images delete abc123hash --dry-run
    """
    mutate(
        ctx,
        title=f"Удалить изображения: {len(hashes)} шт.",
        service="adimages",
        method="delete",
        params={"SelectionCriteria": {"AdImageHashes": hashes}},
        confirm=confirm,
    )


# --- videos -------------------------------------------------------------------------------------


@videos_app.command("list")
@output.guard
def videos_list(
    ctx: typer.Context,
    ids: list[str] = typer.Argument(..., help="Id видео через пробел (API не отдаёт список всех видео)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Статус обработки загруженных видео.

    --json: {"ok": true, "count": N, "videos": [{Id, Status}]}.

    Example: {cli} videos list 5f1a2b3c --json
    """
    items = services.run(services.direct(ctx.obj).list_ad_videos(ids))
    emit_list(ctx, "videos", items, [("Id", "Id"), ("Статус", "Status")], title="Видео")


@videos_app.command("add")
@output.guard
def videos_add(
    ctx: typer.Context,
    url: str = typer.Option(None, "--url", help="Ссылка на видеофайл (нужна она или --file)."),
    file: str = typer.Option(None, "--file", help="Локальный видеофайл."),
    name: str = typer.Option(None, "--name", help="Название видео (по умолчанию — имя файла)."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Загрузить видео; его Id — для `creatives add-video-extension`.

    --json: отчёт изменения; Id видео — в result.AddResults[].Id.

    Example: {cli} videos add --url https://example.com/promo.mp4 --name Промо --dry-run
    """
    if url and file:
        raise InvalidArguments("Укажите что-то одно: --url или --file.")
    if file:
        data = _read_file(file)
        item = {"VideoData": base64.b64encode(data).decode("ascii"), "Name": name or Path(file).name}
        preview = {"VideoData": f"<{len(data)} байт>", "Name": item["Name"]}
    elif url:
        item = preview = {"Url": url, **({"Name": name} if name else {})}
    else:
        raise InvalidArguments("Укажите --url или --file.")
    mutate(
        ctx,
        title=f"Загрузить видео {preview.get('Name') or url}",
        service="advideos",
        method="add",
        params={"AdVideos": [preview]},
        confirm=confirm,
        call=lambda: services.direct(ctx.obj).add_ad_videos([item]),
    )


# --- creatives ----------------------------------------------------------------------------------


@creatives_app.command("list")
@output.guard
def creatives_list(
    ctx: typer.Context,
    ids: list[int] = typer.Option(None, "--id", help="Только эти креативы (повторяемая)."),
    types: list[CreativeType] = typer.Option(None, "--type", help="Фильтр по типу креатива (повторяемая)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Креативы кабинета: изображения, HTML5, видео, смарт-баннеры.

    --json: {"ok": true, "count": N, "creatives": [{Id, Type, Name, Width, Height, Associated, IsAdaptive, …}]}.

    Example: {cli} creatives list --type VIDEO_EXTENSION_CREATIVE
    """
    items = services.run(
        services.direct(ctx.obj).list_creatives(ids=ids or None, types=[t.value for t in types or []] or None)
    )
    columns = [("Id", "Id"), ("Тип", "Type"), ("Имя", "Name"), ("Ширина", "Width"), ("Высота", "Height")]
    emit_list(ctx, "creatives", items, columns, title="Креативы")


@creatives_app.command("add-video-extension")
@output.guard
def creatives_add_video_extension(
    ctx: typer.Context,
    video_ids: list[str] = typer.Argument(..., help="Id видео из `videos add`, до 10 за вызов."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Создать видеодополнения (VideoExtensionCreative) из загруженных видео.

    Id креативов из ответа указываются в `ads add-text --video-extension`.

    Example: {cli} creatives add-video-extension 5f1a2b3c --confirm
    """
    if len(video_ids) > 10:
        raise InvalidArguments("creatives.add — не более 10 креативов за вызов.")
    mutate(
        ctx,
        title=f"Создать видеодополнения: {len(video_ids)} шт.",
        service="creatives",
        method="add",
        params={"Creatives": [{"VideoExtensionCreative": {"VideoId": v}} for v in video_ids]},
        confirm=confirm,
    )
