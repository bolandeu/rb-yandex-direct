"""`yd history` — «История изменений» кабинета: кто, когда и что поменял (только веб-интерфейс).

API Директа такого журнала не отдаёт (changes.check говорит лишь «что-то изменилось»).
Раздел общий для кабинета: кампании, группы, объявления, стратегии — не только Мастер.
"""

from __future__ import annotations

import typer

from .. import output
from ..core.errors import InvalidArguments
from ..providers import browser
from ._common import emit_list
from ._web import ChromeDirOption, ChromeProfileOption, HeadfulOption
from ._web import run as web_run

app = output.group("История изменений кабинета (веб-интерфейс, без API): кто, когда и что поменял.")

COLUMNS = [
    ("Когда", "Datetime"),
    ("Кто", "Login"),
    ("Источник", "ChangeSource"),
    ("Событие", "EventType"),
    ("Кампания", "CampaignId"),
    ("Название", "CampaignName"),
]


def _datetime(value: str | None, suffix: str) -> str | None:
    """YYYY-MM-DD → начало/конец дня; значение со временем передаётся как есть."""
    if value is None:
        return None
    return value if "T" in value else f"{value}{suffix}"


@app.command("get")
@output.guard
def get_history(
    ctx: typer.Context,
    campaign_ids: list[int] = typer.Option(None, "--campaign", help="Только записи этих кампаний (повторяемая)."),
    date_from: str = typer.Option(None, "--date-from", help="Начало периода: YYYY-MM-DD или YYYY-MM-DDTHH:MM:SS."),
    date_to: str = typer.Option(None, "--date-to", help="Конец периода: YYYY-MM-DD или YYYY-MM-DDTHH:MM:SS."),
    logins: list[str] = typer.Option(None, "--by", help="Только изменения этих логинов (повторяемая)."),
    sources: list[str] = typer.Option(None, "--source", help="Источник изменения: WEB, API, OTHER… (повторяемая)."),
    categories: list[str] = typer.Option(
        None, "--category", help="Категория изменения, например CAMPAIGN_STRATEGY (повторяемая; по умолчанию все)."
    ),
    limit: int = typer.Option(None, "--limit", help="Не больше N записей (по умолчанию все)."),
    headful: bool = HeadfulOption,
    chrome_dir: str = ChromeDirOption,
    chrome_profile: str = ChromeProfileOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Журнал изменений кабинета, новые сверху; фильтры применяет сам Директ.

    Без --date-from/--date-to — период раздела по умолчанию. В Event — поля события целиком,
    в том числе oldStrategy/newStrategy: какая цель или счётчик пропали из стратегии.
    --json: {"ok": true, "count": N, "history": [...]}.

    Example: {cli} history get --campaign 12345 --date-from 2026-09-01 --json
    """
    if limit is not None and limit <= 0:
        raise InvalidArguments("--limit должен быть положительным.")
    items = web_run(
        ctx,
        lambda page: browser.lib().change_history.fetch_change_history(
            page,
            campaign_ids=campaign_ids or None,
            date_from=_datetime(date_from, "T00:00:00"),
            date_to=_datetime(date_to, "T23:59:59"),
            categories=categories or None,
            logins=logins or None,
            change_sources=sources or None,
            limit=limit,
        ),
        headful,
        chrome_dir,
        chrome_profile,
    )
    emit_list(ctx, "history", items, COLUMNS, title="История изменений")
