from __future__ import annotations

from pathlib import Path

import pandas as pd

from stockvisualizer.database import (
    fetch_company,
    fetch_financials,
    fetch_watchlist,
    initialize_database,
)


def load_watchlist(db_path: str | Path | None = None) -> pd.DataFrame:
    """Initialize storage if needed, then return the current watchlist."""
    initialize_database(db_path)
    return fetch_watchlist(db_path)


def load_stock_detail(
    ticker: str, db_path: str | Path | None = None
) -> tuple[dict[str, object], pd.DataFrame]:
    """Return a company's quote and financial history or raise for bad symbols."""
    initialize_database(db_path)
    company = fetch_company(ticker, db_path)
    if company is None:
        raise ValueError(f"{ticker!r} is not present in the stock watchlist.")
    financials = fetch_financials(ticker, db_path)
    if financials.empty:
        raise ValueError(f"No financial history is available for {ticker}.")
    return company, financials


def refresh_sample_data(db_path: str | Path | None = None) -> pd.DataFrame:
    """Reload locally stored sample data; this intentionally makes no network call."""
    initialize_database(db_path)
    return fetch_watchlist(db_path)
