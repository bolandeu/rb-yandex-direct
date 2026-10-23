"""The provider contract: what a provider declares, how its credentials are checked, and the discovery of the providers
in this package.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Literal

from ..core.version import module_exists

# What a provider's own health check can conclude. `missing` and `unchecked`
# are decided by `auth status` before a check ever runs.
HealthStatus = Literal["ok", "invalid", "expired", "quota_exhausted", "unreachable"]


@dataclass(frozen=True)
class Quota:
    remaining: int | None = None
    limit: int | None = None
    unit: str = "requests"


@dataclass(frozen=True)
class Health:
    """Result of `Provider.health_check()`. Never put a credential value in `message`."""

    status: HealthStatus = "ok"
    expires_at: datetime | None = None
    quota: Quota | None = None
    message: str | None = None


class Provider:
    """Base for every external integration, whatever its transport.

    A concrete provider sets `name` and `credential_fields` (the field names
    it reads via `credentials.manager` under `credential_name`; `()` if it
    needs none), `required`, `per_target` and `legacy_env` where they
    differ, and must implement `health_check()` — `tests/test_providers.py`
    fails for any provider that doesn't. `auth status --check` gets an
    instance via `for_health_check()`: `cls()` by default; a provider whose
    constructor needs arguments overrides it (building them from config/env).

    Classes that are only bases for others set `abstract = True` in their own
    body; everything else defined under `providers/` is discovered by
    `all_providers()`, so there is no registry to forget to update.
    """

    abstract: ClassVar[bool] = True
    name: ClassVar[str] = "default"
    credential_fields: ClassVar[tuple[str, ...]] = ("api_key",)
    # False for a provider the CLI works without: its missing credential is
    # reported but doesn't fail `auth status` (a wrong one still does).
    required: ClassVar[bool] = True
    # True when the credential is per target (a site, host, account): one
    # stored credential per target, named "<name>:<target>" — e.g.
    # `auth login --provider deploy:example.com`. `auth status` reports each
    # stored target separately and sets `target` before `health_check()`.
    per_target: ClassVar[bool] = False
    # Older env var names still honoured, field -> name; looked up after the
    # keychain unless `legacy_env_first`. In a subclass keep the annotation
    # (ruff RUF012): legacy_env: ClassVar[dict[str, str]] = {"api_key": "XMLRIVER_TOKEN"}
    legacy_env: ClassVar[dict[str, str]] = {}
    legacy_env_first: ClassVar[bool] = False
    # Other CLIs' credential namespaces (their command names) to read this
    # provider's credential from after our own — e.g. wordstat reading the
    # key `serp auth login` stored: shared_namespaces = ("serp",). Read-only.
    shared_namespaces: ClassVar[tuple[str, ...]] = ()
    target: str | None = None

    def credential(self) -> dict[str, str] | None:
        """This provider's credential, resolved with all of the options above (use it in auth_headers()).

        None in a CLI generated without credentials (include_auth=false): there
        is no key store to read, so a provider there declares
        `credential_fields = ()` and never needs one.
        """
        manager_module = f"{__name__.split('.')[0]}.credentials.manager"
        if not module_exists(manager_module):
            return None
        manager = importlib.import_module(manager_module)
        return manager.get_credential(
            self.credential_name,
            env_fields=list(self.credential_fields),
            legacy_env=self.legacy_env,
            legacy_env_first=self.legacy_env_first,
            shared_namespaces=self.shared_namespaces,
        )

    @classmethod
    def for_health_check(cls, target: str | None = None) -> Provider:
        """An instance for `auth status --check` (for `target`, if per-target)."""
        provider = cls()
        provider.target = target
        return provider

    @property
    def credential_name(self) -> str:
        """The key to read this provider's credential under in `credentials.manager`."""
        return f"{self.name}:{self.target}" if self.per_target and self.target else self.name

    def health_check(self) -> Health:
        """One cheap, read-only, non-billed call proving the credential works.

        Typically `self.get_json("/me")` (or whatever the API's cheapest
        authenticated read is) then `return Health()`; add `expires_at` for
        anything with a lifetime and `quota` if the API reports it. Just let
        `AuthRequired` / `ProviderError` propagate — `auth status` maps them
        to `invalid` / `unreachable`. It must finish within 10 s and not retry,
        and it is the provider's own client timeout that guarantees it —
        `auth status` runs no watchdog thread. `HttpProvider.probe()` makes
        exactly one request with a 10 s httpx timeout; anything else passes
        `credentials.health.CHECK_TIMEOUT` (10 s) to what it calls.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement health_check()")


def all_providers() -> list[type[Provider]]:
    """Every concrete Provider subclass defined in this package, sorted by name."""
    package = __name__.rsplit(".", 1)[0]
    for module in pkgutil.iter_modules(importlib.import_module(package).__path__):
        # base/http hold only abstract bases; importing http.py would pull in
        # httpx for CLIs without HTTP providers (their subclasses import it anyway).
        if module.name not in ("base", "http"):
            importlib.import_module(f"{package}.{module.name}")
    found: set[type[Provider]] = set()
    pending = list(Provider.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if cls.__module__.startswith(f"{package}.") and not cls.__dict__.get("abstract", False):
            found.add(cls)
    return sorted(found, key=lambda cls: cls.name)
