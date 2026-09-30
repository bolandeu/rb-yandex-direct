"""Реестр групп и команд верхнего уровня: `cli.py` подключает всё отсюда.

Новая группа — модуль в `commands/` с `app = output.group(...)` и строка здесь.
"""

from __future__ import annotations

from collections.abc import Callable

import typer

from . import account, campaigns, history, masters
from . import browser as browser_cmd

GROUPS: dict[str, typer.Typer] = {
    "clients": account.clients_app,
    "campaigns": campaigns.app,
    "masters": masters.app,
    "history": history.app,
    "browser": browser_cmd.app,
}

TOP_LEVEL: dict[str, Callable] = {
    "whoami": account.whoami,
    "accounts": account.accounts,
}
