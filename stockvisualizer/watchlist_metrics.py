from __future__ import annotations

import math
from datetime import date
from typing import Any

from stockvisualizer.calculations.cumulative_eps_payback import (
    calculate_cumulative_eps_payback,
)
from stockvisualizer.calculations.expected_growth import calculate_expected_growth
from stockvisualizer.calculations.net_profit_cagr import (
    calculate_net_profit_cagr_4y,
    calculate_net_profit_cagr_max_available,
)
from stockvisualizer.calculations.reported_pe import calculate_reported_pe
from stockvisualizer.calculations.revenue_cagr import (
    calculate_revenue_cagr_4y,
    calculate_revenue_cagr_max_available,
)
from stockvisualizer.calculations.valuation_rating import calculate_valuation_rating


def build_watchlist_metrics(
    observations: list[dict[str, Any]],
    current_price: float | None,
    company_name: str,
    saved_metrics: dict[str, Any],
    expected_growth_override: float | None = None,
    live_market_data: dict[str, Any] | None = None,
) -> dict[str, float | int | str | None]:
    annual: dict[str, dict[str, float | None]] = {}
    balance_sheet: dict[str, dict[str, float | None]] = {}
    seen_metrics: dict[tuple[str, str, str], bool] = {}
    for item in observations:
        period = str(item["period"])
        target = (
            annual
            if item.get("statement") == "annual"
            else balance_sheet
            if item.get("statement") == "balance_sheet"
            else None
        )
        if target is None:
            continue
        metric = str(item["metric"])
        key = (item.get("statement", ""), period, metric)
        period_metrics = target.setdefault(period, {})
        if seen_metrics.get(key):
            period_metrics[metric] = None
        else:
            period_metrics[metric] = item.get("value")
            seen_metrics[key] = True

    periods = sorted(annual)
    years = [date.fromisoformat(period).year for period in periods]
    revenue = [annual[period].get("revenue") for period in periods]
    profit = [annual[period].get("net_profit") for period in periods]
    revenue_growth, revenue_years = calculate_revenue_cagr_max_available(
        revenue, years
    )
    profit_growth, profit_years = calculate_net_profit_cagr_max_available(
        profit, years
    )
    revenue_4y = calculate_revenue_cagr_4y(revenue, years)
    profit_4y = calculate_net_profit_cagr_4y(profit, years)

    growth_components = []
    if revenue_growth is not None:
        growth_components.append(revenue_growth)
    if revenue_4y is not None and revenue_years != 4:
        growth_components.append(revenue_4y)
    if profit_growth is not None:
        growth_components.append(profit_growth)
    if profit_4y is not None and profit_years != 4:
        growth_components.append(profit_4y)
    calculated_expected_growth = calculate_expected_growth(
        growth_components[0] if len(growth_components) > 0 else None,
        growth_components[1] if len(growth_components) > 1 else None,
        growth_components[2] if len(growth_components) > 2 else None,
        growth_components[3] if len(growth_components) > 3 else None,
    )
    if calculated_expected_growth is None:
        saved_expected_growth = saved_metrics.get("expected_growth")
        if saved_expected_growth is not None:
            try:
                candidate = float(saved_expected_growth)
                calculated_expected_growth = (
                    candidate if math.isfinite(candidate) else None
                )
            except (TypeError, ValueError, OverflowError):
                calculated_expected_growth = None
    expected_growth = (
        expected_growth_override
        if expected_growth_override is not None
        else calculated_expected_growth
    )

    latest = annual[periods[-1]] if periods else {}
    if live_market_data is not None:
        eps = live_market_data.get("eps_inr")
    else:
        eps = latest.get("eps_reported")
        if eps is None:
            eps = latest.get("eps_derived")
        if eps is None:
            eps = saved_metrics.get("latest_eps")
    if eps is not None:
        try:
            eps = float(eps)
            if not math.isfinite(eps):
                eps = None
        except (TypeError, ValueError, OverflowError):
            eps = None
    if live_market_data is not None:
        calculated_pe = live_market_data.get("pe")
    else:
        calculated_pe = (
            calculate_reported_pe(current_price, eps)
            if current_price is not None and eps is not None
            else None
        )

    payback = (
        calculate_cumulative_eps_payback(
            current_price, eps, expected_growth
        )
        if current_price is not None
        and eps is not None
        and expected_growth is not None
        else None
    )
    rating = calculate_valuation_rating(calculated_pe, expected_growth)
    if live_market_data is not None:
        try:
            raw_debt_to_equity = live_market_data.get("debt_to_equity")
            debt_to_equity = (
                float(raw_debt_to_equity)
                if raw_debt_to_equity is not None
                and math.isfinite(float(raw_debt_to_equity))
                and float(raw_debt_to_equity) >= 0
                else None
            )
        except (TypeError, ValueError, OverflowError):
            debt_to_equity = None
    else:
        debt_to_equity = None

    if live_market_data is not None:
        try:
            yahoo_market_cap = live_market_data.get("market_cap_inr")
            market_cap = (
                float(yahoo_market_cap) / 10_000_000
                if yahoo_market_cap is not None
                and math.isfinite(float(yahoo_market_cap))
                and float(yahoo_market_cap) > 0
                else None
            )
        except (TypeError, ValueError, OverflowError):
            market_cap = None
    else:
        market_cap = saved_metrics.get("market_cap_cr")
    if live_market_data is None and market_cap is None and current_price is not None:
        shares = latest.get("adjusted_shares_cr")
        try:
            candidate = float(current_price) * float(shares)
            market_cap = candidate if math.isfinite(candidate) and candidate > 0 else None
        except (TypeError, ValueError, OverflowError):
            market_cap = None

    latest_balance_period = max(balance_sheet) if balance_sheet else None
    latest_balance = (
        balance_sheet[latest_balance_period] if latest_balance_period else {}
    )
    borrowings = latest_balance.get("borrowings")
    is_bank = (
        "bank" in company_name.casefold()
        or (latest_balance.get("deposits") or 0) > 0
    )
    debt_ebitda = None
    latest_debt_annual = annual.get(latest_balance_period, {})
    ebitda_inputs = (
        latest_debt_annual.get("profit_before_tax"),
        latest_debt_annual.get("interest"),
        latest_debt_annual.get("depreciation"),
        latest_debt_annual.get("other_income"),
    )
    if not is_bank and latest_balance_period is not None:
        try:
            debt = float(borrowings)
            profit_before_tax, interest, depreciation, other_income = (
                float(value) for value in ebitda_inputs
            )
            ebitda = profit_before_tax + interest + depreciation - other_income
            ratio = debt / ebitda
            if (
                all(
                    math.isfinite(value)
                    for value in (
                        debt,
                        profit_before_tax,
                        interest,
                        depreciation,
                        other_income,
                    )
                )
                and debt >= 0
                and math.isfinite(ebitda)
                and ebitda > 0
                and math.isfinite(ratio)
            ):
                debt_ebitda = ratio
        except (TypeError, ValueError, OverflowError, ZeroDivisionError):
            debt_ebitda = None

    return {
        "revenue_growth": revenue_growth,
        "revenue_growth_years": revenue_years,
        "revenue_growth_4y": revenue_4y,
        "profit_growth": profit_growth,
        "profit_growth_years": profit_years,
        "profit_growth_4y": profit_4y,
        "expected_growth": expected_growth,
        "expected_growth_override": expected_growth_override,
        "calculated_pe": calculated_pe,
        "rating": rating,
        "normalized_pe": saved_metrics.get("normalized_core_pe"),
        "eps": eps,
        "eps_payback": payback,
        "market_cap_cr": market_cap,
        "debt_ebitda": debt_ebitda,
        "debt_to_equity": debt_to_equity,
    }


def format_growth(value: float | None, years: int | None = None) -> str:
    if value is None:
        return "—"
    return f"{value:.1%} ({years}Y)" if years is not None else f"{value:.1%}"


def format_multiple(value: float | None) -> str:
    return f"{value:.2f}x" if value is not None else "—"


def format_debt_ebitda(value: float | None) -> str:
    if value is None:
        return "—"
    precision = 4 if abs(value) < 0.01 else 2
    return f"{value:.{precision}f}x"


def format_number(value: float | None, suffix: str = "") -> str:
    return f"{value:,.2f}{suffix}" if value is not None else "—"


def format_payback_years(value: float | None) -> str:
    return f"{value:.0f} years" if value is not None else "—"


def format_price(value: float | None) -> str:
    return f"₹{value:,.2f}" if value is not None else "—"


def format_percent(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "—"


def format_anomaly_status(status: str | None) -> str:
    indicators = {
        "green": "🟢 Green",
        "orange": "🟠 Orange",
        "red": "🔴 Red",
    }
    if status is None:
        return "⚪ Not assessed"
    return indicators.get(status.casefold(), "⚪ Not assessed")
