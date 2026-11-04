import math


def calculate_reported_pe(market_price: float, reported_eps: float) -> float | None:
    """Calculate price/EPS; return None for losses or invalid inputs."""
    try:
        price, eps = float(market_price), float(reported_eps)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(price) or not math.isfinite(eps) or price <= 0 or eps <= 0:
        return None
    result = price / eps
    return result if math.isfinite(result) else None
