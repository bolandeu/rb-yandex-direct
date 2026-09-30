"""Параметры кабинета (Clients, AgencyClients) из опций CLI; перечни — из WSDL generalclients.xsd."""

from __future__ import annotations

from typing import Any

from .errors import InvalidArguments
from .strategy import yes_no_pairs

CURRENCIES = ("RUB", "BYN", "KZT", "USD", "EUR", "CHF", "TRY", "UAH", "GBP")
LANGS = ("RU", "UK", "EN", "TR")
EMAIL_SUBSCRIPTIONS = ("RECEIVE_RECOMMENDATIONS", "TRACK_MANAGED_CAMPAIGNS", "TRACK_POSITION_CHANGES")
SETTINGS_ADD = ("CORRECT_TYPOS_AUTOMATICALLY", "DISPLAY_STORE_RATING", "SHARED_ACCOUNT_ENABLED")
SETTINGS_UPDATE = ("CORRECT_TYPOS_AUTOMATICALLY", "DISPLAY_STORE_RATING")
PRIVILEGES = ("EDIT_CAMPAIGNS", "IMPORT_XLS", "TRANSFER_MONEY")
TIN_TYPES = ("PHYSICAL", "FOREIGN_PHYSICAL", "LEGAL", "FOREIGN_LEGAL", "INDIVIDUAL")
ROLES = ("ADMIN", "USER")

AGENCY_CLIENT_FIELDS = [
    "AccountQuality", "Archived", "ClientId", "ClientInfo", "CountryId", "CreatedAt", "Currency", "Grants",
    "Bonuses", "Login", "Notification", "OverdraftSumAvailable", "Phone", "Representatives", "Restrictions",
    "Settings", "Type", "VatRate", "ForbiddenPlatform", "AvailableCampaignTypes", "AvailableAdGroupTypes",
]  # fmt: skip


def _choice(value: str | None, allowed: tuple[str, ...], option: str) -> str | None:
    if value is None:
        return None
    value = value.upper()
    if value not in allowed:
        raise InvalidArguments(f"{option}: один из {', '.join(allowed)}.")
    return value


def option_items(items: list[str] | None, allowed: tuple[str, ...], option: str, key: str = "Option") -> list[dict]:
    """`ИМЯ=YES|NO` (повторяемая) → [{<key>: ИМЯ, "Value": YES|NO}]."""
    return [{key: k, "Value": v} for k, v in yes_no_pairs(items, allowed, option)]


def notification_add(email: str, lang: str, subscriptions: list[str] | None) -> dict[str, Any]:
    """NotificationAdd: Email, Lang и подписки — API требует все три; неуказанные подписки — NO."""
    given = dict(yes_no_pairs(subscriptions, EMAIL_SUBSCRIPTIONS, "--subscription"))
    return {
        "Email": email,
        "Lang": _choice(lang, LANGS, "--lang"),
        "EmailSubscriptions": [{"Option": o, "Value": given.get(o, "NO")} for o in EMAIL_SUBSCRIPTIONS],
    }


def client_update_fields(
    *,
    client_info: str | None,
    phone: str | None,
    email: str | None,
    lang: str | None,
    subscriptions: list[str] | None,
    settings: list[str] | None,
    tin_type: str | None,
    tin: str | None,
) -> dict[str, Any]:
    """Поля ClientUpdateItem (общие для clients.update и agencyclients.update); только переданные."""
    item: dict[str, Any] = {}
    if client_info is not None:
        item["ClientInfo"] = client_info
    if phone is not None:
        item["Phone"] = phone
    notification: dict[str, Any] = {}
    if email:
        notification["Email"] = email
    if lang:
        notification["Lang"] = _choice(lang, LANGS, "--lang")
    if subscriptions:
        notification["EmailSubscriptions"] = option_items(subscriptions, EMAIL_SUBSCRIPTIONS, "--subscription")
    if notification:
        item["Notification"] = notification
    if settings:
        item["Settings"] = option_items(settings, SETTINGS_UPDATE, "--setting")
    if tin_type or tin:
        tin_info: dict[str, Any] = {}
        if tin_type:
            tin_info["TinType"] = _choice(tin_type, TIN_TYPES, "--tin-type")
        if tin:
            tin_info["Tin"] = tin
        item["TinInfo"] = tin_info
    return item


choice = _choice
