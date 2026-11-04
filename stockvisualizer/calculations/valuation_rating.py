from __future__ import annotations

import math


def calculate_valuation_rating(
    pe_actual: float | None,
    expected_growth: float | None,
) -> str:
    """Rate valuation using P/E and growth, where growth is a decimal fraction."""
    try:
        pe = float(pe_actual) if pe_actual is not None else math.nan
        growth = float(expected_growth) if expected_growth is not None else math.nan
    except (TypeError, ValueError, OverflowError):
        return "Unavailable"

    if (
        not math.isfinite(pe)
        or pe <= 0
        or not math.isfinite(growth)
        or growth <= 0
    ):
        return "Unavailable"

    growth_percent = growth * 100
    fair_pe = 0.096 * growth_percent**2
    if not math.isfinite(fair_pe) or fair_pe <= 0:
        return "Unavailable"

    valuation_ratio = round(pe / fair_pe, 12)
    if not math.isfinite(valuation_ratio):
        return "Unavailable"
    if valuation_ratio <= 0.70:
        return "Strong Buy (Deep Value)"
    if valuation_ratio <= 0.90:
        return "Good Buy (Undervalued)"
    if valuation_ratio <= 1.10:
        return "Fair Value (Hold / Neutral)"
    if valuation_ratio <= 1.30:
        return "Slightly Overvalued"
    return "Overvalued (Avoid / Sell)"
