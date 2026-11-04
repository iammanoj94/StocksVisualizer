def calculate_stock_rating(
    normalized_pe: float | None,
    expected_growth: float | None,
    payback_years: float | None,
) -> str:
    """Return a simple educational screen based on valuation, growth, and payback."""
    if normalized_pe is None or expected_growth is None:
        return "Insufficient data"

    score = 0
    score += 2 if expected_growth >= 0.15 else 1 if expected_growth >= 0.08 else 0
    score += 2 if normalized_pe <= 20 else 1 if normalized_pe <= 30 else 0
    if payback_years is not None:
        score += 1 if payback_years <= 8 else 0

    if score >= 4:
        return "Attractive"
    if score >= 3:
        return "Positive"
    if score >= 1:
        return "Balanced"
    return "Cautious"
