"""Реестр групп и команд верхнего уровня: `cli.py` подключает всё отсюда.

Новая группа — модуль в `commands/` с `app = output.group(...)` и строка здесь.
"""

from __future__ import annotations

from collections.abc import Callable

import typer

from . import account, agency, campaigns, changes, dictionaries, feeds, report, strategies

GROUPS: dict[str, typer.Typer] = {
    "clients": account.clients_app,
    "agency": agency.app,
    "campaigns": campaigns.app,
    "strategies": strategies.app,
    "feeds": feeds.app,
    "dict": dictionaries.app,
    "changes": changes.app,
    "report": report.app,
}

TOP_LEVEL: dict[str, Callable] = {
    "whoami": account.whoami,
    "accounts": account.accounts,
}
