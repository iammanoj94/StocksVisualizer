from stockvisualizer.calculations.cumulative_eps_payback import (
    EPSPaybackAnalysis,
    calculate_eps_payback_analysis,
)


SENSITIVITY_GROWTH_RATES = (0.08, 0.10, 0.12, 0.15)


def calculate_payback_sensitivity(
    market_price: float, current_eps: float, max_years: int = 30
) -> dict[float, EPSPaybackAnalysis | None]:
    """Calculate EPS payback at the requested standard growth assumptions."""
    return {
        growth: calculate_eps_payback_analysis(
            market_price, current_eps, growth, max_years
        )
        for growth in SENSITIVITY_GROWTH_RATES
    }
