from datetime import datetime, timezone

import pandas as pd
import pytest

from stockvisualizer.stock_catalog import build_stock_rows
from stockvisualizer.watchlist_ui import build_watchlist_table_frame
from stockvisualizer.yahoo_market_data import (
    fetch_yahoo_quote,
    refresh_yahoo_market_data,
    yahoo_symbol_for_ticker,
)


def test_yahoo_symbol_mapping_requires_nse_ticker():
    assert yahoo_symbol_for_ticker("abc") == "ABC.NS"
    assert yahoo_symbol_for_ticker("abc.ns") == "ABC.NS"

    with pytest.raises(ValueError, match="BSE ticker"):
        yahoo_symbol_for_ticker("ABC.BO")
    with pytest.raises(ValueError, match="not a supported"):
        yahoo_symbol_for_ticker("ABC.L")


def test_yahoo_quote_maps_inr_market_fields_and_source_price_type():
    timestamp = 1_800_000_000
    requested_symbols = []

    quote = fetch_yahoo_quote(
        "TEST",
        info_loader=lambda symbol: (
            requested_symbols.append(symbol)
            or {
                "currency": "INR",
                "regularMarketPrice": 123.45,
                "regularMarketTime": timestamp,
                "marketCap": 125_000_000,
                "trailingPE": 12.5,
                "trailingEps": 9.88,
                "debtToEquity": 250,
            }
        ),
    )

    assert requested_symbols == ["TEST.NS"]
    assert quote["price_inr"] == 123.45
    assert quote["price_type"] == "regularMarketPrice"
    assert quote["market_cap_inr"] == 125_000_000
    assert quote["pe"] == 12.5
    assert quote["eps_inr"] == 9.88
    assert quote["debt_to_equity"] == 2.5
    assert quote["quote_timestamp"] == datetime.fromtimestamp(
        timestamp, timezone.utc
    ).isoformat(timespec="seconds")


def test_yahoo_quote_derives_debt_equity_from_balance_sheet_when_ratio_missing():
    balance_sheet = pd.DataFrame(
        {
            "2025-03-31": [300, 400],
            "2024-03-31": [250, 350],
        },
        index=["TotalDebt", "StockholdersEquity"],
    )
    requested_symbols = []

    quote = fetch_yahoo_quote(
        "TEST",
        info_loader=lambda _: {
            "currency": "INR",
            "regularMarketPrice": 100,
        },
        balance_sheet_loader=lambda symbol: (
            requested_symbols.append(symbol) or balance_sheet
        ),
    )

    assert requested_symbols == ["TEST.NS"]
    assert quote["debt_to_equity"] == pytest.approx(0.75)


def test_yahoo_quote_uses_debt_and_equity_components_when_total_debt_missing():
    balance_sheet = pd.DataFrame(
        {"2025-03-31": [200, 100, 400]},
        index=[
            "LongTermDebt",
            "CurrentDebt",
            "CommonStockEquity",
        ],
    )

    quote = fetch_yahoo_quote(
        "TEST",
        info_loader=lambda _: {"currency": "INR", "regularMarketPrice": 100},
        balance_sheet_loader=lambda _: balance_sheet,
    )

    assert quote["debt_to_equity"] == pytest.approx(0.75)


def test_yahoo_quote_keeps_debt_equity_unavailable_for_invalid_balance_sheet():
    balance_sheet = pd.DataFrame(
        {"2025-03-31": [300, 0]},
        index=["TotalDebt", "StockholdersEquity"],
    )

    quote = fetch_yahoo_quote(
        "TEST",
        info_loader=lambda _: {"currency": "INR", "regularMarketPrice": 100},
        balance_sheet_loader=lambda _: balance_sheet,
    )

    assert quote["debt_to_equity"] is None


def test_yahoo_quote_keeps_quote_data_when_balance_sheet_lookup_fails():
    quote = fetch_yahoo_quote(
        "TEST",
        info_loader=lambda _: {
            "currency": "INR",
            "regularMarketPrice": 100,
        },
        balance_sheet_loader=lambda _: (_ for _ in ()).throw(
            RuntimeError("Yahoo statement unavailable")
        ),
    )

    assert quote["price_inr"] == 100
    assert quote["debt_to_equity"] is None
    assert quote["debt_to_equity_error"] == (
        "Yahoo balance sheet lookup failed: RuntimeError"
    )
    results = refresh_yahoo_market_data(
        ["TEST.NS"], fetcher=lambda _: quote, saver=lambda *_: None
    )
    assert results[0]["status"] == "partial"
    assert "Debt/Equity (Yahoo balance sheet lookup failed: RuntimeError)" in results[0][
        "message"
    ]


def test_yahoo_quote_rejects_unconfirmed_currency():
    with pytest.raises(ValueError, match="did not confirm INR"):
        fetch_yahoo_quote("TEST", info_loader=lambda _: {"currency": "USD"})


def test_refresh_continues_after_failure_and_reports_partial_quotes():
    saved = []
    progress = []

    def fetcher(ticker):
        if ticker == "FAIL.NS":
            raise RuntimeError("provider unavailable")
        return {
            "price_inr": 100.0,
            "market_cap_inr": None,
            "pe": 10.0,
            "eps_inr": 10.0,
            "debt_to_equity": 0.75,
        }

    results = refresh_yahoo_market_data(
        ["OK.NS", "FAIL.NS", "PARTIAL.NS"],
        fetcher=fetcher,
        saver=lambda ticker, quote: saved.append(ticker),
        progress_callback=lambda index, total, ticker: progress.append(
            (index, total, ticker)
        ),
    )

    assert saved == ["OK.NS", "PARTIAL.NS"]
    assert [result["status"] for result in results] == [
        "partial",
        "failed",
        "partial",
    ]
    assert "provider unavailable" in results[1]["message"]
    assert progress == [
        (1, 3, "OK.NS"),
        (2, 3, "FAIL.NS"),
        (3, 3, "PARTIAL.NS"),
    ]


def test_yahoo_quote_overrides_live_metrics_without_changing_snapshot():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshot = {
        "current_price": 80,
        "imported_at": "2025-01-01T00:00:00+00:00",
        "financial_status": "Green",
        "metrics": {"expected_growth": 0.1},
    }
    catalog = [
        {
            "ticker": "TEST.NS",
            "company_name": "Test Limited",
            "sector": "Unknown",
            "data_label": "Screener export snapshot",
            "snapshot": snapshot,
        }
    ]
    quote = {
        "yahoo_symbol": "TEST.NS",
        "price_inr": 100.0,
        "price_type": "regularMarketPrice",
        "market_cap_inr": 125_000_000,
        "pe": 12.0,
        "eps_inr": 10.0,
        "debt_to_equity": 0.75,
        "currency": "INR",
        "quote_timestamp": now,
        "fetched_at": now,
    }

    rows = build_stock_rows(
        catalog=catalog,
        financials_loader=lambda _: pd.DataFrame(),
        expected_growth_overrides={"TEST.NS": 0.1},
        yahoo_market_data_records={"TEST.NS": quote},
    )
    row = rows[0]
    table = build_watchlist_table_frame(rows, {})

    assert row["current_price"] == 100.0
    assert row["price_source"] == "Yahoo Finance"
    assert row["watchlist_metrics"]["market_cap_cr"] == 12.5
    assert row["watchlist_metrics"]["calculated_pe"] == 12.0
    assert row["watchlist_metrics"]["eps"] == 10.0
    assert row["watchlist_metrics"]["debt_to_equity"] == 0.75
    assert row["watchlist_metrics"]["eps_payback"] is not None
    assert snapshot["current_price"] == 80
    assert table.loc["TEST.NS", "Price"] == 100.0
    assert table.loc["TEST.NS", "Source"] == "Yahoo"


def test_cached_yahoo_null_fields_do_not_fall_back_to_screener_values():
    catalog = [
        {
            "ticker": "TEST.NS",
            "company_name": "Test Limited",
            "sector": "Unknown",
            "snapshot": {
                "current_price": 80,
                "imported_at": "2025-01-01T00:00:00+00:00",
                "financial_status": "Green",
                "metrics": {"latest_eps": 8, "market_cap_cr": 100},
            },
        }
    ]
    quote = {
        "price_inr": None,
        "market_cap_inr": None,
        "pe": None,
        "eps_inr": None,
        "debt_to_equity": None,
        "quote_timestamp": None,
        "fetched_at": "2026-01-01T00:00:00+00:00",
    }

    row = build_stock_rows(
        catalog=catalog,
        expected_growth_overrides={},
        yahoo_market_data_records={"TEST.NS": quote},
    )[0]

    assert row["current_price"] is None
    assert row["price_display"] == "Unavailable"
    assert row["watchlist_metrics"]["eps"] is None
    assert row["watchlist_metrics"]["calculated_pe"] is None
    assert row["watchlist_metrics"]["market_cap_cr"] is None
    assert row["watchlist_metrics"]["debt_to_equity"] is None
    table = build_watchlist_table_frame([row], {})
    assert table.loc["TEST.NS", "Source"] == "Yahoo"
    assert pd.isna(table.loc["TEST.NS", "Debt/Equity"])
