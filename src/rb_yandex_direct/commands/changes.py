"""`yd changes` — что изменилось с момента времени (сервис Changes): для инкрементальной синхронизации."""

from __future__ import annotations

import typer

from .. import output
from ..core import services
from ..core.errors import InvalidArguments
from ._common import emit_list, emit_object

app = output.group("Изменения с момента времени: кампании, группы, объявления, статистика, справочники.")

TimestampArgument = typer.Argument(..., help="Момент времени UTC, ISO 8601: 2026-09-01T00:00:00Z.")


@app.command("campaigns")
@output.guard
def campaigns(
    ctx: typer.Context,
    timestamp: str = TimestampArgument,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Какие кампании менялись с момента времени: сами (SELF), их содержимое (CHILDREN), статистика (STAT).

    Первый шаг синхронизации: дальше `changes check --campaign …` по изменившимся.
    --json: {"ok": true, "count": N, "campaigns": [{CampaignId, ChangesIn: [...]}], "timestamp": "<новая точка отсчёта>"}.

    Example: {cli} changes campaigns 2026-09-01T00:00:00Z --json
    """
    result = services.run(services.direct(ctx.obj).check_campaign_changes(timestamp))
    items = result.get("Campaigns") or []
    columns = [("Кампания", "CampaignId"), ("Что изменилось", lambda c: ", ".join(c.get("ChangesIn") or []))]
    emit_list(
        ctx, "campaigns", items, columns, title="Изменённые кампании", extra={"timestamp": result.get("Timestamp")}
    )


@app.command("check")
@output.guard
def check(
    ctx: typer.Context,
    timestamp: str = TimestampArgument,
    campaign_ids: list[int] = typer.Option(None, "--campaign", help="Кампания (повторяемая)."),
    adgroup_ids: list[int] = typer.Option(None, "--adgroup", help="Группа объявлений (повторяемая)."),
    ad_ids: list[int] = typer.Option(None, "--ad", help="Объявление (повторяемая)."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменённые и удалённые объекты внутри кампаний, групп или объявлений с момента времени.

    Ровно один вид фильтра: --campaign, --adgroup или --ad (так требует API).
    --json: {"ok": true, "changes": {Modified: {CampaignIds, AdGroupIds, AdIds, CampaignsStat},
    NotFound: {...}, Unprocessed: {...}, Timestamp}}.

    Example: {cli} changes check 2026-09-01T00:00:00Z --campaign 12345
    """
    if len([x for x in (campaign_ids, adgroup_ids, ad_ids) if x]) != 1:
        raise InvalidArguments("Укажите ровно один вид фильтра: --campaign, --adgroup или --ad.")
    result = services.run(
        services.direct(ctx.obj).check_changes(
            timestamp, campaign_ids=campaign_ids, adgroup_ids=adgroup_ids, ad_ids=ad_ids
        )
    )
    emit_object(ctx, "changes", result, title=f"Изменения с {timestamp}")


@app.command("dictionaries")
@output.guard
def dictionaries(
    ctx: typer.Context,
    timestamp: str = typer.Argument(None, help="Момент времени UTC, ISO 8601; без него — только текущий Timestamp."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Менялись ли справочники регионов, часовых поясов и интересов с момента времени.

    --json: {"ok": true, "changes": {RegionsChanged, TimeZonesChanged, InterestsChanged, Timestamp}}.

    Example: {cli} changes dictionaries 2026-09-01T00:00:00Z
    """
    result = services.run(services.direct(ctx.obj).check_dictionaries(timestamp))
    emit_object(ctx, "changes", result, title="Справочники")
