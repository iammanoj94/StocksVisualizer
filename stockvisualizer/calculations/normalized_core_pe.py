import math
from collections.abc import Sequence


def calculate_normalized_core_pe(
    market_price: float, core_eps_values: Sequence[float | None]
) -> float | None:
    """Price divided by mean adjusted core EPS from documented historical data.

    Callers must provide EPS after identifying exceptional income/expenses and
    normalizing cyclical margins. This function does not infer those adjustments.
    """
    try:
        price = float(market_price)
        eps_values = [float(value) for value in core_eps_values]
    except (TypeError, ValueError, OverflowError):
        return None
    if (
        not math.isfinite(price)
        or price <= 0
        or not eps_values
        or any(not math.isfinite(value) or value <= 0 for value in eps_values)
    ):
        return None
    normalized_eps = sum(eps_values) / len(eps_values)
    if not math.isfinite(normalized_eps) or normalized_eps <= 0:
        return None
    result = price / normalized_eps
    return result if math.isfinite(result) else None
