"""Реестр групп и команд верхнего уровня: `cli.py` подключает всё отсюда.

Новая группа — модуль в `commands/` с `app = output.group(...)` и строка здесь.
"""

from __future__ import annotations

from collections.abc import Callable

import typer

from . import account, bids, campaigns, keywords, minus_sets, modifiers, retargeting, targets

GROUPS: dict[str, typer.Typer] = {
    "clients": account.clients_app,
    "campaigns": campaigns.app,
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
}

TOP_LEVEL: dict[str, Callable] = {
    "whoami": account.whoami,
    "accounts": account.accounts,
}
