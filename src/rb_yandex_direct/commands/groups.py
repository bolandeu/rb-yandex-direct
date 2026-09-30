"""Реестр групп и команд верхнего уровня: `cli.py` подключает всё отсюда.

Новая группа — модуль в `commands/` с `app = output.group(...)` и строка здесь.
"""

from __future__ import annotations

from collections.abc import Callable

import typer

from . import account, campaigns, finance, forecast, history, masters, v4misc, wordstat
from . import browser as browser_cmd

GROUPS: dict[str, typer.Typer] = {
    "clients": account.clients_app,
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
}

TOP_LEVEL: dict[str, Callable] = {
    "whoami": account.whoami,
    "accounts": account.accounts,
    "suggest": v4misc.suggest,  # API v4 Live
}
