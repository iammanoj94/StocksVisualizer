from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd
import yfinance as yf

from stockvisualizer.database import save_yahoo_market_data


YAHOO_SOURCE = "Yahoo Finance"
QUOTE_FIELDS = (
    "price_inr",
    "market_cap_inr",
    "pe",
    "eps_inr",
    "debt_to_equity",
)


def yahoo_symbol_for_ticker(ticker: str) -> str:
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("Ticker cannot be empty.")
    if symbol.endswith(".BO"):
        raise ValueError(f"{ticker} is a BSE ticker; Yahoo NSE data requires an .NS ticker.")
    if "." in symbol and not symbol.endswith(".NS"):
        raise ValueError(f"{ticker} is not a supported Yahoo NSE ticker.")
    return symbol if symbol.endswith(".NS") else f"{symbol}.NS"


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _quote_timestamp(value: Any) -> str | None:
    timestamp = _finite_number(value)
    if timestamp is None or timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(
            timespec="seconds"
        )
    except (OverflowError, OSError, ValueError):
        return None


def _balance_sheet_debt_to_equity(balance_sheet: pd.DataFrame) -> float | None:
    if not isinstance(balance_sheet, pd.DataFrame) or balance_sheet.empty:
        return None

    def first_available(names: tuple[str, ...]) -> float | None:
        for name in names:
            if name not in balance_sheet.index:
                continue
            value = _finite_number(balance_sheet.loc[name].iloc[0])
            if value is not None:
                return value
        return None

    total_debt = first_available(("TotalDebt",))
    if total_debt is None:
        long_term_debt = first_available(
            ("LongTermDebtAndCapitalLeaseObligation", "LongTermDebt")
        )
        current_debt = first_available(
            ("CurrentDebtAndCapitalLeaseObligation", "CurrentDebt")
        )
        if long_term_debt is None and current_debt is None:
            return None
        total_debt = (long_term_debt or 0.0) + (current_debt or 0.0)

    equity = first_available(
        (
            "StockholdersEquity",
            "CommonStockEquity",
            "TotalEquityGrossMinorityInterest",
        )
    )
    if (
        total_debt < 0
        or equity is None
        or equity <= 0
    ):
        return None
    ratio = total_debt / equity
    return ratio if math.isfinite(ratio) else None


def fetch_yahoo_quote(
    ticker: str,
    info_loader: Callable[[str], dict[str, Any]] | None = None,
    balance_sheet_loader: Callable[[str], pd.DataFrame] | None = None,
) -> dict[str, Any]:
    yahoo_symbol = yahoo_symbol_for_ticker(ticker)
    yahoo_ticker = yf.Ticker(yahoo_symbol)
    info = info_loader(yahoo_symbol) if info_loader is not None else yahoo_ticker.get_info()
    if not isinstance(info, dict):
        raise ValueError("Yahoo Finance returned an invalid quote response.")
    currency = str(info.get("currency") or "").strip().upper()
    if currency != "INR":
        raise ValueError(
            f"Yahoo Finance did not confirm INR currency for {yahoo_symbol}."
        )
    price = _finite_number(info.get("regularMarketPrice"))
    price_type = "regularMarketPrice"
    if price is None:
        price = _finite_number(info.get("currentPrice"))
        price_type = "currentPrice"
    yahoo_debt_to_equity_pct = _finite_number(info.get("debtToEquity"))
    if yahoo_debt_to_equity_pct is not None:
        debt_to_equity = yahoo_debt_to_equity_pct / 100
        debt_to_equity_error = None
    else:
        try:
            balance_sheet = (
                balance_sheet_loader(yahoo_symbol)
                if balance_sheet_loader is not None
                else yahoo_ticker.get_balance_sheet()
            )
        except Exception as error:
            balance_sheet = pd.DataFrame()
            debt_to_equity_error = (
                f"Yahoo balance sheet lookup failed: {type(error).__name__}"
            )
        else:
            debt_to_equity_error = None
        debt_to_equity = _balance_sheet_debt_to_equity(balance_sheet)
    quote = {
        "yahoo_symbol": yahoo_symbol,
        "price_inr": price if price is not None and price > 0 else None,
        "price_type": price_type if price is not None and price > 0 else None,
        "market_cap_inr": _finite_number(info.get("marketCap")),
        "pe": _finite_number(info.get("trailingPE")),
        "eps_inr": _finite_number(info.get("trailingEps")),
        "debt_to_equity": debt_to_equity,
        "debt_to_equity_error": debt_to_equity_error,
        "currency": currency,
        "quote_timestamp": _quote_timestamp(info.get("regularMarketTime")),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if all(quote[field] is None for field in QUOTE_FIELDS):
        raise ValueError(
            f"Yahoo Finance returned no usable price, market cap, P/E, EPS, or debt-to-equity value for {yahoo_symbol}."
        )
    return quote


def refresh_yahoo_market_data(
    tickers: list[str],
    *,
    fetcher: Callable[[str], dict[str, Any]] | None = None,
    saver: Callable[[str, dict[str, Any]], None] | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[dict[str, str]]:
    quote_fetcher = fetcher or fetch_yahoo_quote
    quote_saver = saver or save_yahoo_market_data
    results: list[dict[str, str]] = []
    for index, ticker in enumerate(tickers, start=1):
        try:
            quote = quote_fetcher(ticker)
            quote_saver(ticker, quote)
        except Exception as error:
            message = re.sub(r"\s+", " ", str(error)).strip()
            results.append(
                {
                    "ticker": ticker,
                    "status": "failed",
                    "message": f"{type(error).__name__}: {message[:240]}",
                }
            )
            if progress_callback is not None:
                progress_callback(index, len(tickers), ticker)
            continue
        missing_fields = [
            label
            for key, label in (
                ("price_inr", "Price"),
                ("market_cap_inr", "Market cap"),
                ("pe", "P/E"),
                ("eps_inr", "EPS"),
                ("debt_to_equity", "Debt/Equity"),
            )
            if quote.get(key) is None
        ]
        debt_to_equity_error = quote.get("debt_to_equity_error")
        if debt_to_equity_error:
            missing_fields[-1] = f"Debt/Equity ({debt_to_equity_error})"
        results.append(
            {
                "ticker": ticker,
                "status": "partial" if missing_fields else "success",
                "message": (
                    "Missing: " + ", ".join(missing_fields)
                    if missing_fields
                    else "Updated"
                ),
            }
        )
        if progress_callback is not None:
            progress_callback(index, len(tickers), ticker)
    return results
