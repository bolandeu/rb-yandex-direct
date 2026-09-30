"""Опции параметров стратегии — общие для `campaigns add/set-strategy` и `strategies add/update`."""

from __future__ import annotations

import typer

from ..core.strategy import StrategyParams

WeeklyBudgetOption = typer.Option(None, "--weekly-budget", help="Недельный бюджет стратегии (WeeklySpendLimit), ₽.")
BidCeilingOption = typer.Option(None, "--bid-ceiling", help="Максимальная ставка (BidCeiling), ₽.")
AverageCpcOption = typer.Option(None, "--average-cpc", help="Средняя цена клика (AverageCpc/FilterAverageCpc), ₽.")
AverageCpaOption = typer.Option(None, "--average-cpa", help="Средняя цена конверсии (AverageCpa/FilterAverageCpa), ₽.")
CpaOption = typer.Option(None, "--cpa", help="Цена конверсии при оплате за конверсии (Cpa), ₽.")
AverageCpiOption = typer.Option(None, "--average-cpi", help="Средняя цена установки приложения (AverageCpi), ₽.")
AverageCpmOption = typer.Option(None, "--average-cpm", help="Средняя цена тысячи показов (AverageCpm), ₽.")
AverageCpvOption = typer.Option(None, "--average-cpv", help="Средняя цена просмотра (AverageCpv), ₽.")
SpendLimitOption = typer.Option(None, "--spend-limit", help="Бюджет медийной стратегии (SpendLimit), ₽.")
GoalIdOption = typer.Option(None, "--goal-id", help="Id цели Метрики для конверсионных стратегий (GoalId).")
CrrOption = typer.Option(None, "--crr", help="Доля рекламных расходов, % (Crr).")
ClicksPerWeekOption = typer.Option(None, "--clicks-per-week", help="Пакет кликов в неделю (ClicksPerWeek).")
LimitPercentOption = typer.Option(
    None, "--limit-percent", help="Доля бюджета на сети при NETWORK_DEFAULT, % (LimitPercent)."
)


def params(
    weekly_budget: float | None,
    bid_ceiling: float | None,
    average_cpc: float | None,
    average_cpa: float | None,
    cpa: float | None,
    goal_id: int | None,
    crr: int | None,
    clicks_per_week: int | None = None,
    limit_percent: int | None = None,
    average_cpi: float | None = None,
    average_cpm: float | None = None,
    average_cpv: float | None = None,
    spend_limit: float | None = None,
) -> StrategyParams:
    return StrategyParams(
        weekly_budget=weekly_budget,
        bid_ceiling=bid_ceiling,
        average_cpc=average_cpc,
        average_cpa=average_cpa,
        cpa=cpa,
        goal_id=goal_id,
        crr=crr,
        clicks_per_week=clicks_per_week,
        limit_percent=limit_percent,
        average_cpi=average_cpi,
        average_cpm=average_cpm,
        average_cpv=average_cpv,
        spend_limit=spend_limit,
    )
