from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class EPSPaybackYear:
    year: int
    annual_eps: float
    cumulative_eps: float


@dataclass(frozen=True)
class EPSPaybackAnalysis:
    schedule: tuple[EPSPaybackYear, ...]
    first_full_year: int | None
    estimated_payback_years: float | None


def calculate_eps_payback_analysis(
    market_price: float,
    current_eps: float,
    eps_growth: float,
    max_years: int = 30,
) -> EPSPaybackAnalysis | None:
    """Project annual EPS and estimate cumulative-EPS payback with final-year interpolation.

    Year one EPS is the supplied current EPS. Each following year's EPS grows
    by ``eps_growth``. The fractional estimate assumes EPS accrues evenly within
    the final year in which cumulative EPS reaches the market price.
    """
    try:
        price, eps, growth = (
            float(market_price),
            float(current_eps),
            float(eps_growth),
        )
    except (TypeError, ValueError, OverflowError):
        return None
    if (
        not math.isfinite(price)
        or not math.isfinite(eps)
        or not math.isfinite(growth)
        or price <= 0
        or eps <= 0
        or growth <= -1
        or isinstance(max_years, bool)
        or not isinstance(max_years, int)
        or max_years <= 0
    ):
        return None

    schedule: list[EPSPaybackYear] = []
    cumulative_eps = 0.0
    annual_eps = eps
    for year in range(1, max_years + 1):
        if not math.isfinite(annual_eps):
            return None
        cumulative_eps += annual_eps
        if not math.isfinite(cumulative_eps):
            return None
        schedule.append(EPSPaybackYear(year, annual_eps, cumulative_eps))
        if cumulative_eps >= price:
            previous_cumulative_eps = cumulative_eps - annual_eps
            final_year_fraction = (price - previous_cumulative_eps) / annual_eps
            return EPSPaybackAnalysis(
                schedule=tuple(schedule),
                first_full_year=year,
                estimated_payback_years=(year - 1) + final_year_fraction,
            )
        annual_eps *= 1 + growth

    return EPSPaybackAnalysis(tuple(schedule), None, None)


def calculate_cumulative_eps_payback(
    market_price: float,
    starting_eps: float,
    expected_growth: float,
    max_years: int = 30,
) -> float | None:
    """Return fractional estimated payback years, preserving the original API."""
    analysis = calculate_eps_payback_analysis(
        market_price, starting_eps, expected_growth, max_years
    )
    return analysis.estimated_payback_years if analysis is not None else None
