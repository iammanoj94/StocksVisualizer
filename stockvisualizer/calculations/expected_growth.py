import math


def calculate_expected_growth(
    revenue_cagr: float | None,
    revenue_cagr_4y: float | None = None,
    net_profit_cagr: float | None = None,
    net_profit_cagr_4y: float | None = None,
) -> float | None:
    """Average all finite available revenue and net-profit CAGR observations."""
    growth_rates = (
        revenue_cagr,
        revenue_cagr_4y,
        net_profit_cagr,
        net_profit_cagr_4y,
    )
    try:
        values = [
            float(value)
            for value in growth_rates
            if value is not None and math.isfinite(float(value))
        ]
    except (TypeError, ValueError, OverflowError):
        return None
    if not values:
        return None
    try:
        result = math.fsum(values) / len(values)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None
