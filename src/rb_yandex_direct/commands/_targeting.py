"""Общее для команд таргетинга и ставок: перечисления API, разбор условий и области действия."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Any

import typer

from ..core.errors import InvalidArguments
from ._common import IdsArgument, mutate

__all__ = [
    "IdsArgument",
    "Priority",
    "YesNo",
    "ids_mutation",
    "parse_conditions",
    "require_one_scope",
    "scope_item",
]


class Priority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class YesNo(StrEnum):
    YES = "YES"
    NO = "NO"


class ServingStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    RARELY_SERVED = "RARELY_SERVED"


class TargetState(StrEnum):
    """Состояния условий нацеливания (AdTargetStateSelectionEnum)."""

    ON = "ON"
    OFF = "OFF"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"


PriorityOption = typer.Option(None, "--priority", help="Приоритет для автостратегии: LOW, NORMAL, HIGH.")
AdGroupFilter = typer.Option(None, "--adgroup", help="Фильтр по группе объявлений (повторяемая).")
CampaignFilter = typer.Option(None, "--campaign", help="Фильтр по кампании (повторяемая).")
IdFilter = typer.Option(None, "--id", help="Только эти Id (повторяемая).")
FieldOption = typer.Option(None, "--field", help="Поле FieldNames вместо набора по умолчанию (повторяемая).")


def values(items: Sequence[StrEnum] | None) -> list[str] | None:
    return [i.value for i in items] if items else None


def parse_conditions(specs: list[str] | None) -> list[dict[str, Any]]:
    """`OPERAND:OPERATOR:ARG1|ARG2` → [{"Operand", "Operator", "Arguments": [...]}] (как в direct-cli)."""
    conditions = []
    for spec in specs or []:
        parts = [p.strip() for p in spec.split(":", 2)]
        if len(parts) != 3 or not all(parts):
            raise InvalidArguments(f"Условие {spec!r}: ожидается OPERAND:OPERATOR:ARG1|ARG2.")
        operand, operator, raw = parts
        args = [a.strip() for a in raw.split("|") if a.strip()]
        if not args:
            raise InvalidArguments(f"Условие {spec!r}: нужен хотя бы один аргумент после второго двоеточия.")
        conditions.append({"Operand": operand, "Operator": operator.upper(), "Arguments": args})
    return conditions


def require_one_scope(target_id: int | None, adgroup_id: int | None, campaign_id: int | None) -> None:
    if sum(x is not None for x in (target_id, adgroup_id, campaign_id)) != 1:
        raise InvalidArguments("Укажите ровно одно из --id, --adgroup, --campaign.")


def scope_item(
    target_id: int | None, adgroup_id: int | None, campaign_id: int | None, *, id_key: str = "Id"
) -> dict[str, Any]:
    """Элемент setBids/set: ровно один из Id (или KeywordId) / AdGroupId / CampaignId."""
    require_one_scope(target_id, adgroup_id, campaign_id)
    if target_id is not None:
        return {id_key: target_id}
    if adgroup_id is not None:
        return {"AdGroupId": adgroup_id}
    return {"CampaignId": campaign_id}


def ids_mutation(
    ctx: typer.Context, *, service: str, method: str, verb: str, noun: str, ids: list[int], confirm: bool
) -> None:
    """suspend/resume/delete и т.п. по списку Id: `{"SelectionCriteria": {"Ids": [...]}}`."""
    mutate(
        ctx,
        title=f"{verb} {noun} {', '.join(map(str, ids))}",
        service=service,
        method=method,
        params={"SelectionCriteria": {"Ids": ids}},
        confirm=confirm,
    )
