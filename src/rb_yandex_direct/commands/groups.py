"""Реестр групп и команд верхнего уровня: `cli.py` подключает всё отсюда.

Новая группа — модуль в `commands/` с `app = output.group(...)` и строка здесь.
"""

from __future__ import annotations

from collections.abc import Callable

import typer

from . import (
    account,
    agency,
    bids,
    campaigns,
    changes,
    dictionaries,
    feeds,
    finance,
    forecast,
    history,
    keywords,
    masters,
    minus_sets,
    modifiers,
    report,
    retargeting,
    strategies,
    targets,
    v4misc,
    wordstat,
)
from . import adgroups as adgroups_cmd
from . import ads as ads_cmd
from . import browser as browser_cmd
from . import extensions as extensions_cmd
from . import media as media_cmd

GROUPS: dict[str, typer.Typer] = {
    "clients": account.clients_app,
    "agency": agency.app,
    "campaigns": campaigns.app,
    # API v4 Live
    "wordstat": wordstat.app,
    "forecast": forecast.app,
    "events": v4misc.events_app,
    "goals": v4misc.goals_app,
    "tags": v4misc.tags_app,
    "finance": finance.app,
    "shared-account": finance.shared_app,
    "v4": v4misc.v4_app,
    # Веб-интерфейс (браузер)
    "masters": masters.app,
    "history": history.app,
    "browser": browser_cmd.app,
    # --- структура объявлений ---
    "adgroups": adgroups_cmd.app,
    "ads": ads_cmd.app,
    "images": media_cmd.images_app,
    "videos": media_cmd.videos_app,
    "creatives": media_cmd.creatives_app,
    "sitelinks": extensions_cmd.sitelinks_app,
    "vcards": extensions_cmd.vcards_app,
    "extensions": extensions_cmd.extensions_app,
    "turbo": extensions_cmd.turbo_app,
    # Таргетинг и ставки.
    "keywords": keywords.app,
    "bids": bids.app,
    "bids-classic": bids.classic_app,
    "modifiers": modifiers.app,
    "minus-sets": minus_sets.app,
    "retargeting": retargeting.app,
    "audiences": retargeting.audiences_app,
    "dynamic-targets": targets.dynamic_app,
    "dynamic-feed-targets": targets.feed_app,
    "smart-targets": targets.smart_app,
    # Кампании, стратегии, инфраструктура
    "strategies": strategies.app,
    "feeds": feeds.app,
    "dict": dictionaries.app,
    "changes": changes.app,
    "report": report.app,
}

TOP_LEVEL: dict[str, Callable] = {
    "whoami": account.whoami,
    "accounts": account.accounts,
    "suggest": v4misc.suggest,  # API v4 Live
    # --- структура объявлений ---
    "businesses": extensions_cmd.businesses,
    "leads": extensions_cmd.leads,
}
