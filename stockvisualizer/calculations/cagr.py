from __future__ import annotations

import math
from collections.abc import Sequence


def calculate_positive_cagr(
    values: Sequence[float | None],
    periods: int | None = None,
    fiscal_years: Sequence[int] | None = None,
) -> float | None:
    """Calculate CAGR for a trailing annual window with positive observations."""
    if periods is None:
        periods = len(values) - 1
    if isinstance(periods, bool) or not isinstance(periods, int) or periods <= 0:
        return None
    observation_count = periods + 1
    if len(values) < observation_count:
        return None
    if fiscal_years is not None and len(fiscal_years) != len(values):
        return None

    try:
        observations = [float(value) for value in values[-observation_count:]]
    except (TypeError, ValueError, OverflowError):
        return None
    if any(not math.isfinite(value) or value <= 0 for value in observations):
        return None

    if fiscal_years is not None:
        try:
            years = [int(year) for year in fiscal_years[-observation_count:]]
            original_years = [float(year) for year in fiscal_years[-observation_count:]]
        except (TypeError, ValueError, OverflowError):
            return None
        if any(not math.isfinite(year) or year != int(year) for year in original_years):
            return None
        if any(later - earlier != 1 for earlier, later in zip(years, years[1:])):
            return None

    try:
        result = (observations[-1] / observations[0]) ** (1 / periods) - 1
    except (OverflowError, ZeroDivisionError, ValueError):
        return None
    return result if math.isfinite(result) else None


def calculate_max_available_cagr(
    values: Sequence[float | None],
    fiscal_years: Sequence[int] | None = None,
    max_periods: int = 9,
) -> tuple[float | None, int | None]:
    """Calculate CAGR over the longest valid consecutive suffix, capped at 9 years."""
    if (
        isinstance(max_periods, bool)
        or not isinstance(max_periods, int)
        or max_periods <= 0
        or len(values) == 0
        or (fiscal_years is not None and len(fiscal_years) != len(values))
    ):
        return None, None

    observation_count = 1
    try:
        latest_value = float(values[-1])
    except (TypeError, ValueError, OverflowError):
        return None, None
    if not math.isfinite(latest_value) or latest_value <= 0:
        return None, None

    latest_year: int | None = None
    if fiscal_years is not None:
        try:
            year_number = float(fiscal_years[-1])
            latest_year = int(year_number)
        except (TypeError, ValueError, OverflowError):
            return None, None
        if not math.isfinite(year_number) or year_number != latest_year:
            return None, None

    limit = min(len(values), max_periods + 1)
    for offset in range(2, limit + 1):
        try:
            value = float(values[-offset])
        except (TypeError, ValueError, OverflowError):
            break
        if not math.isfinite(value) or value <= 0:
            break
        if fiscal_years is not None:
            try:
                year_number = float(fiscal_years[-offset])
                year = int(year_number)
            except (TypeError, ValueError, OverflowError):
                break
            if not math.isfinite(year_number) or year_number != year:
                break
            if latest_year is None or latest_year - year != offset - 1:
                break
        observation_count += 1

    if observation_count < 3:
        return None, None
    periods = observation_count - 1
    result = calculate_positive_cagr(values, periods, fiscal_years)
    return (result, periods) if result is not None else (None, None)
