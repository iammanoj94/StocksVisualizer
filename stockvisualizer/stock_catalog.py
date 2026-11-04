from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd
from stockvisualizer.calculations.expected_growth import calculate_expected_growth
from stockvisualizer.calculations.net_profit_cagr import (
    calculate_net_profit_cagr_4y,
    calculate_net_profit_cagr_max_available,
)
from stockvisualizer.calculations.revenue_cagr import (
    calculate_revenue_cagr_4y,
    calculate_revenue_cagr_max_available,
)
from stockvisualizer.database import (
    fetch_expected_growth_overrides,
    fetch_financials,
    fetch_screener_observations,
    fetch_stock_catalog,
    fetch_yahoo_market_data,
)
from stockvisualizer.price_data import assess_price
from stockvisualizer.watchlist_metrics import build_watchlist_metrics


def build_stock_rows(
    catalog: list[dict[str, Any]] | None = None,
    financials_loader: Callable[[str], pd.DataFrame] = fetch_financials,
    expected_growth_overrides: dict[str, float] | None = None,
    yahoo_market_data_records: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    if expected_growth_overrides is not None:
        growth_overrides = expected_growth_overrides
    elif catalog is None:
        growth_overrides = fetch_expected_growth_overrides()
    else:
        growth_overrides = {}
    if yahoo_market_data_records is not None:
        live_quotes = yahoo_market_data_records
    elif catalog is None:
        live_quotes = fetch_yahoo_market_data()
    else:
        live_quotes = {}
    for stock in (
        catalog if catalog is not None else fetch_stock_catalog()
    ):
        snapshot = stock["snapshot"]
        expected_growth_override = growth_overrides.get(stock["ticker"])
        live_quote = live_quotes.get(stock["ticker"])
        if snapshot is not None:
            metrics = snapshot["metrics"]
            imported_at = snapshot["imported_at"]
            observations = (
                fetch_screener_observations(snapshot["snapshot_id"])
                if snapshot.get("snapshot_id")
                else []
            )
            if live_quote is not None:
                price = assess_price(
                    ticker=stock["ticker"],
                    value=live_quote["price_inr"],
                    source="Yahoo Finance",
                    as_of=live_quote["quote_timestamp"],
                    recorded_at=live_quote["fetched_at"],
                )
            else:
                price = assess_price(
                    ticker=stock["ticker"],
                    value=snapshot["current_price"],
                    source="Screener Excel/CSV Data Sheet · Current Price",
                    as_of=None,
                    recorded_at=imported_at,
                )
            price_display = (
                f"INR {price.value:,.2f}" if price.value is not None else "Unavailable"
            )
            expected_growth = metrics.get("expected_growth")
            payback = metrics.get("cumulative_eps_payback_years")
            payback_display = (
                f"{payback:.2f} · archived analysis"
                if payback is not None
                else "Unavailable"
            )
            financial_status = snapshot["financial_status"]
            market_cap = "Unavailable"
            last_updated = (
                f"Yahoo fetch: {live_quote['fetched_at']}; Screener import: {imported_at}"
                if live_quote is not None
                else f"Screener import: {imported_at}"
            )
            data_label = "Screener export snapshot"
            watchlist_metrics = build_watchlist_metrics(
                observations,
                price.value,
                stock["company_name"],
                metrics,
                expected_growth_override,
                live_quote,
            )
        else:
            expected_growth = _sample_expected_growth(
                stock["ticker"], financials_loader
            )
            if live_quote is not None:
                price = assess_price(
                    ticker=stock["ticker"],
                    value=live_quote["price_inr"],
                    source="Yahoo Finance",
                    as_of=live_quote["quote_timestamp"],
                    recorded_at=live_quote["fetched_at"],
                )
                price_display = (
                    f"INR {price.value:,.2f}" if price.value is not None else "Unavailable"
                )
                last_updated = f"Yahoo fetch: {live_quote['fetched_at']}"
            else:
                price = assess_price(
                    ticker=stock["ticker"],
                    value=None,
                    source="Illustrative sample only; not a market quote",
                    as_of=None,
                    recorded_at=None,
                )
                price_display = "Unavailable"
                last_updated = "Unknown · sample rows have no source timestamp"
            payback_display = "Unavailable · no reliable market price"
            financial_status = "Sample data · not anomaly-validated"
            market_cap = "Unavailable"
            data_label = stock["data_label"] or "Imported company mapping"
            watchlist_metrics = build_watchlist_metrics(
                [],
                price.value,
                stock["company_name"],
                {"expected_growth": expected_growth},
                expected_growth_override,
                live_quote,
            )
        if watchlist_metrics["market_cap_cr"] is not None:
            market_cap = f"{watchlist_metrics['market_cap_cr']:,.0f} Cr"

        rows.append(
            {
                "ticker": stock["ticker"],
                "company_name": stock["company_name"],
                "sector": stock["sector"],
                "current_price": price.value,
                "price_display": price_display,
                "price_source": price.source,
                "price_type": (
                    "Yahoo Finance · " + str(live_quote.get("price_type") or "unknown")
                    if live_quote is not None
                    else "Unknown · Screener export does not identify LTP/close"
                    if snapshot is not None
                    else "Not applicable · illustrative sample only"
                ),
                "exchange": price.exchange,
                "price_as_of": (
                    price.as_of.isoformat() if price.as_of is not None else "Unknown"
                ),
                "price_recorded_at": (
                    price.recorded_at.isoformat()
                    if price.recorded_at is not None
                    else "Unknown"
                ),
                "freshness": price.freshness,
                "market_cap_display": market_cap,
                "expected_growth": expected_growth,
                "expected_growth_display": (
                    f"{expected_growth:.1%}"
                    if expected_growth is not None
                    else "Unavailable"
                ),
                "payback_display": payback_display,
                "financial_status": financial_status,
                "last_updated": last_updated,
                "data_label": data_label,
                "is_imported": snapshot is not None,
                "watchlist_metrics": watchlist_metrics,
            }
        )
    return rows


def _sample_expected_growth(
    ticker: str,
    financials_loader: Callable[[str], pd.DataFrame],
) -> float | None:
    financials = financials_loader(ticker)
    if financials.empty:
        return None
    revenues = financials["revenue_cr"].tolist()
    profits = financials["net_profit_cr"].tolist()
    years = financials["fiscal_year"].tolist()
    revenue_max, revenue_period = calculate_revenue_cagr_max_available(
        revenues, years
    )
    profit_max, profit_period = calculate_net_profit_cagr_max_available(
        profits, years
    )
    revenue_4y = calculate_revenue_cagr_4y(revenues, years)
    profit_4y = calculate_net_profit_cagr_4y(profits, years)
    values = []
    if revenue_max is not None:
        values.append(revenue_max)
    if revenue_4y is not None and revenue_period != 4:
        values.append(revenue_4y)
    if profit_max is not None:
        values.append(profit_max)
    if profit_4y is not None and profit_period != 4:
        values.append(profit_4y)
    return calculate_expected_growth(*values)
