"""`yd modifiers` — корректировки ставок (сервис BidModifiers)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import typer

from .. import output
from ..core import services
from ..core.errors import InvalidArguments
from ._common import emit_list, mutate
from ._targeting import FieldOption, IdFilter, IdsArgument, ids_mutation, values

app = output.group("Корректировки ставок: устройства, пол и возраст, регионы, ретаргетинг, доход, позиция и др.")


class ModifierType(StrEnum):
    """Тип корректировки для `add` (без суффикса _ADJUSTMENT)."""

    MOBILE = "MOBILE"
    DESKTOP = "DESKTOP"
    SMART_TV = "SMART_TV"
    TABLET = "TABLET"
    DESKTOP_ONLY = "DESKTOP_ONLY"
    DEMOGRAPHICS = "DEMOGRAPHICS"
    RETARGETING = "RETARGETING"
    REGIONAL = "REGIONAL"
    VIDEO = "VIDEO"
    SMART_AD = "SMART_AD"
    SERP_LAYOUT = "SERP_LAYOUT"
    INCOME_GRADE = "INCOME_GRADE"
    AD_GROUP = "AD_GROUP"


class Level(StrEnum):
    CAMPAIGN = "CAMPAIGN"
    AD_GROUP = "AD_GROUP"


class Gender(StrEnum):
    GENDER_MALE = "GENDER_MALE"
    GENDER_FEMALE = "GENDER_FEMALE"


class Age(StrEnum):
    AGE_0_17 = "AGE_0_17"
    AGE_18_24 = "AGE_18_24"
    AGE_25_34 = "AGE_25_34"
    AGE_35_44 = "AGE_35_44"
    AGE_45 = "AGE_45"
    AGE_45_54 = "AGE_45_54"
    AGE_55 = "AGE_55"


class Os(StrEnum):
    IOS = "IOS"
    ANDROID = "ANDROID"


class SerpLayout(StrEnum):
    ALONE = "ALONE"
    SUGGEST = "SUGGEST"


class IncomeGrade(StrEnum):
    VERY_HIGH = "VERY_HIGH"
    HIGH = "HIGH"
    ABOVE_AVERAGE = "ABOVE_AVERAGE"


# Блок BidModifierAddItem по типу; True — массив (несколько условий в одной корректировке).
BLOCKS: dict[ModifierType, tuple[str, bool]] = {
    ModifierType.MOBILE: ("MobileAdjustment", False),
    ModifierType.DESKTOP: ("DesktopAdjustment", False),
    ModifierType.SMART_TV: ("SmartTvAdjustment", False),
    ModifierType.TABLET: ("TabletAdjustment", False),
    ModifierType.DESKTOP_ONLY: ("DesktopOnlyAdjustment", False),
    ModifierType.DEMOGRAPHICS: ("DemographicsAdjustments", True),
    ModifierType.RETARGETING: ("RetargetingAdjustments", True),
    ModifierType.REGIONAL: ("RegionalAdjustments", True),
    ModifierType.VIDEO: ("VideoAdjustment", False),
    ModifierType.SMART_AD: ("SmartAdAdjustment", False),
    ModifierType.SERP_LAYOUT: ("SerpLayoutAdjustments", True),
    ModifierType.INCOME_GRADE: ("IncomeGradeAdjustments", True),
    ModifierType.AD_GROUP: ("AdGroupAdjustment", False),
}


def _value(item: dict) -> Any:
    """Процент корректировки из блока её типа (MobileAdjustment.BidModifier и т.п.)."""
    for key, block in item.items():
        if key.endswith("Adjustment") and isinstance(block, dict):
            return block.get("BidModifier")
    return None


COLUMNS = [
    ("Id", "Id"),
    ("Кампания", "CampaignId"),
    ("Группа", "AdGroupId"),
    ("Уровень", "Level"),
    ("Тип", "Type"),
    ("%", _value),
]


@app.command("list")
@output.guard
def list_modifiers(
    ctx: typer.Context,
    ids: list[int] = IdFilter,
    campaigns: list[int] = typer.Option(None, "--campaign", help="Фильтр по кампании (повторяемая)."),
    adgroups: list[int] = typer.Option(None, "--adgroup", help="Фильтр по группе (повторяемая)."),
    types: list[str] = typer.Option(
        None, "--type", help="Тип с суффиксом: MOBILE_ADJUSTMENT, DEMOGRAPHICS_ADJUSTMENT, … (повторяемая)."
    ),
    levels: list[Level] = typer.Option(None, "--level", help="Уровень: CAMPAIGN и/или AD_GROUP (по умолчанию оба)."),
    fields: list[str] = FieldOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Корректировки ставок кампаний и групп со значениями по каждому типу.

    Нужен хотя бы один из --id, --campaign, --adgroup.
    --json: {"ok": true, "count": N, "modifiers": [{Id, CampaignId, AdGroupId, Level, Type,
    <Тип>Adjustment: {BidModifier, …}}]}.

    Example: {cli} modifiers list --campaign 12345
    """
    if not (ids or campaigns or adgroups):
        raise InvalidArguments("Укажите хотя бы один фильтр: --id, --campaign или --adgroup.")
    items = services.run(
        services.direct(ctx.obj).list_bid_modifiers(
            campaign_ids=campaigns or None,
            adgroup_ids=adgroups or None,
            ids=ids or None,
            types=[t.upper() for t in types] if types else None,
            field_names=fields or None,
            levels=values(levels),
        )
    )
    emit_list(ctx, "modifiers", items, COLUMNS, title="Корректировки ставок")


@app.command("add")
@output.guard
def add(
    ctx: typer.Context,
    modifier_type: ModifierType = typer.Option(..., "--type", help="Тип корректировки."),
    value: int = typer.Option(..., "--value", help="Процент ставки: 100 — без изменений, 0 — не показывать."),
    campaign: int = typer.Option(None, "--campaign", help="Кампания (или --adgroup)."),
    adgroup: int = typer.Option(None, "--adgroup", help="Группа объявлений (или --campaign)."),
    os_type: Os = typer.Option(None, "--os", help="MOBILE/TABLET: только IOS или ANDROID."),
    gender: Gender = typer.Option(None, "--gender", help="DEMOGRAPHICS: пол."),
    age: Age = typer.Option(None, "--age", help="DEMOGRAPHICS: возраст."),
    region: int = typer.Option(None, "--region", help="REGIONAL: Id региона (213 — Москва)."),
    retargeting: int = typer.Option(None, "--retargeting", help="RETARGETING: Id условия ретаргетинга."),
    serp_layout: SerpLayout = typer.Option(
        None, "--serp-layout", help="SERP_LAYOUT: ALONE — эксклюзив, SUGGEST — подсказка."
    ),
    grade: IncomeGrade = typer.Option(None, "--grade", help="INCOME_GRADE: уровень дохода."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Добавить корректировку ставки на кампанию или группу.

    \b
    Ещё примеры:
      {cli} modifiers add --adgroup 456 --type DEMOGRAPHICS --gender GENDER_MALE --age AGE_25_34 --value 120
      {cli} modifiers add --campaign 123 --type REGIONAL --region 213 --value 150
      {cli} modifiers add --campaign 123 --type MOBILE --os IOS --value 80

    Example: {cli} modifiers add --campaign 12345 --type MOBILE --value 50 --dry-run
    """
    if (campaign is None) == (adgroup is None):
        raise InvalidArguments("Укажите ровно одно из --campaign, --adgroup.")
    block: dict[str, Any] = {"BidModifier": value}
    if modifier_type in (ModifierType.MOBILE, ModifierType.TABLET) and os_type:
        block["OperatingSystemType"] = os_type.value
    elif modifier_type == ModifierType.DEMOGRAPHICS:
        if not (gender or age):
            raise InvalidArguments("Для DEMOGRAPHICS нужны --gender и/или --age.")
        if gender:
            block["Gender"] = gender.value
        if age:
            block["Age"] = age.value
    elif modifier_type == ModifierType.REGIONAL:
        if region is None:
            raise InvalidArguments("Для REGIONAL нужен --region.")
        block["RegionId"] = region
    elif modifier_type == ModifierType.RETARGETING:
        if retargeting is None:
            raise InvalidArguments("Для RETARGETING нужен --retargeting.")
        block["RetargetingConditionId"] = retargeting
    elif modifier_type == ModifierType.SERP_LAYOUT:
        if serp_layout is None:
            raise InvalidArguments("Для SERP_LAYOUT нужен --serp-layout.")
        block["SerpLayout"] = serp_layout.value
    elif modifier_type == ModifierType.INCOME_GRADE:
        if grade is None:
            raise InvalidArguments("Для INCOME_GRADE нужен --grade.")
        block["Grade"] = grade.value
    key, is_array = BLOCKS[modifier_type]
    item: dict[str, Any] = {"CampaignId": campaign} if campaign is not None else {"AdGroupId": adgroup}
    item[key] = [block] if is_array else block
    where = f"кампании {campaign}" if campaign is not None else f"группе {adgroup}"
    mutate(
        ctx,
        title=f"Корректировка {modifier_type.value} {value}% на {where}",
        service="bidmodifiers",
        method="add",
        params={"BidModifiers": [item]},
        confirm=confirm,
    )


@app.command("set")
@output.guard
def set_value(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    value: int = typer.Option(..., "--value", help="Новый процент ставки: 100 — без изменений, 0 — не показывать."),
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Изменить процент существующих корректировок (тип и условия не меняются).

    Example: {cli} modifiers set 3001 3002 --value 120 --dry-run
    """
    mutate(
        ctx,
        title=f"Корректировки {', '.join(map(str, ids))} → {value}%",
        service="bidmodifiers",
        method="set",
        params={"BidModifiers": [{"Id": i, "BidModifier": value} for i in ids]},
        confirm=confirm,
    )


@app.command("delete")
@output.guard
def delete(
    ctx: typer.Context,
    ids: list[int] = IdsArgument,
    confirm: bool = output.ConfirmOption,
    dry_run: bool = output.DryRunOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить корректировки ставок.

    Example: {cli} modifiers delete 3001 --dry-run
    """
    ids_mutation(
        ctx, service="bidmodifiers", method="delete", verb="Удалить", noun="корректировки", ids=ids, confirm=confirm
    )
