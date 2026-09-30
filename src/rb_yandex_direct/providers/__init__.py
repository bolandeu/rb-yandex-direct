"""External integrations (HTTP APIs, LLMs, ...) live here, one module per service.

Subclass `HttpProvider` for anything that speaks HTTP — it already maps
auth failures, rate limits, outages and network errors onto the CLI's
error codes and retries what's safe to retry. Keep API calls out of
`commands/` and `core/services.py`; services call a provider, commands
call a service.

Every concrete provider implements `health_check()` — the hook behind
`<cli> auth status --check` (see `base.Provider`).
"""

from __future__ import annotations

import importlib
from typing import Any

from .base import Health, Provider, Quota, all_providers

__all__ = ["Health", "Provider", "Quota", "all_providers"]


def __getattr__(name: str) -> Any:
    # `providers.HttpProvider` loads http.py (and httpx) only when used; a CLI
    # generated with include_http_provider=false has no http.py at all. HTTP
    # providers import it directly: `from .http import HttpProvider`.
    if name == "HttpProvider":
        return importlib.import_module(f"{__name__}.http").HttpProvider
    raise AttributeError(name)
