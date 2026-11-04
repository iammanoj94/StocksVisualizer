import pandas as pd
from pandas.api.types import is_numeric_dtype

from stockvisualizer.watchlist_ui import (
    build_watchlist_table_frame,
    filter_and_sort_stocks,
    move_watchlist_column,
    normalize_watchlist_column_order,
    persist_growth_edits,
    resolve_selected_tickers,
    screener_company_url,
    screener_symbols_for_tickers,
    selection_state_for_all,
)


def test_individual_selection_returns_only_checked_tickers():
    rows = [
        {"ticker": "AAA.NS"},
        {"ticker": "BBB.NS"},
        {"ticker": "CCC.NS"},
    ]

    selected = resolve_selected_tickers(
        rows,
        {"AAA.NS": True, "BBB.NS": False, "CCC.NS": True},
    )

    assert selected == ["AAA.NS", "CCC.NS"]


def test_select_all_and_deselect_all_state_is_scoped_to_available_rows():
    rows = [{"ticker": "AAA.NS"}, {"ticker": "BBB.NS"}]

    assert resolve_selected_tickers(
        rows, selection_state_for_all([row["ticker"] for row in rows], True)
    ) == ["AAA.NS", "BBB.NS"]
    assert resolve_selected_tickers(
        rows, selection_state_for_all([row["ticker"] for row in rows], False)
    ) == []


def test_watchlist_column_order_moves_left_and_right_and_normalizes():
    initial = ["Name", "Price", "Source", "EPS"]

    assert move_watchlist_column(initial, "EPS", -1) == [
        "Name",
        "Price",
        "EPS",
        "Source",
    ]
    assert move_watchlist_column(initial, "Price", 1) == [
        "Name",
        "Source",
        "Price",
        "EPS",
    ]
    assert move_watchlist_column(initial, "Name", -1) == initial
    assert normalize_watchlist_column_order(
        ["EPS", "Old Column", "EPS", "Name"],
        ["Name", "Price", "Source", "EPS"],
    ) == ["EPS", "Name", "Price", "Source"]
    assert normalize_watchlist_column_order(
        ["Name", "Price", "P/E", "EPS", "Screener"],
        ["Name", "Price", "P/E", "Rating", "EPS", "Screener"],
    ) == ["Name", "Price", "P/E", "Rating", "EPS", "Screener"]


def test_stale_selection_for_a_nonvisible_stock_is_not_an_action_target():
    rows = [{"ticker": "AAA.NS"}]

    assert resolve_selected_tickers(rows, {"AAA.NS": True, "NOT-IN-LIST": True}) == [
        "AAA.NS"
    ]


def test_bulk_download_converts_only_selected_exchange_symbols():
    selected = ["MARUTI.NS", "TEST.BO", "M&M.NS"]

    assert screener_symbols_for_tickers(selected) == ["MARUTI", "TEST", "M&M"]


def test_screener_company_url_uses_encoded_screener_symbol():
    assert screener_company_url("MARUTI.NS") == (
        "https://www.screener.in/company/MARUTI/"
    )
    assert screener_company_url("M&M.NS") == (
        "https://www.screener.in/company/M%26M/"
    )


def test_growth_editor_persists_only_changed_stock_values(monkeypatch):
    saved = []
    monkeypatch.setattr(
        "stockvisualizer.watchlist_ui.save_expected_growth_override",
        lambda ticker, value: saved.append((ticker, value)),
    )
    rows = [
        {"ticker": "AAA.NS", "watchlist_metrics": {"expected_growth": 0.1}},
        {"ticker": "BBB.NS", "watchlist_metrics": {"expected_growth": 0.2}},
    ]
    edited = pd.DataFrame(
        {
            "Select": [False, False],
            "Exp Growth": [0.15, 0.2],
        },
        index=["AAA.NS", "BBB.NS"],
    )

    assert persist_growth_edits(rows, edited)
    assert saved == [("AAA.NS", 0.15)]


def test_growth_editor_clear_removes_manual_override(monkeypatch):
    saved = []
    monkeypatch.setattr(
        "stockvisualizer.watchlist_ui.save_expected_growth_override",
        lambda ticker, value: saved.append((ticker, value)),
    )
    rows = [
        {"ticker": "AAA.NS", "watchlist_metrics": {"expected_growth": 0.15}},
    ]
    edited = pd.DataFrame(
        {"Select": [False], "Exp Growth": [None]}, index=["AAA.NS"]
    )

    assert persist_growth_edits(rows, edited)
    assert saved == [("AAA.NS", None)]


def test_watchlist_search_and_sort_operate_on_company_and_ticker():
    rows = [
        {"company_name": "Cipla", "ticker": "CIPLA.NS", "expected_growth": 0.1},
        {"company_name": "Maruti Suzuki", "ticker": "MARUTI.NS", "expected_growth": 0.2},
        {"company_name": "HDFC Bank", "ticker": "HDFCBANK.NS", "expected_growth": 0.15},
    ]

    searched = filter_and_sort_stocks(rows, search="hdfc")
    sorted_rows = filter_and_sort_stocks(
        rows, sort_by="expected_growth", ascending=False
    )

    assert [row["ticker"] for row in searched] == ["HDFCBANK.NS"]
    assert [row["ticker"] for row in sorted_rows] == [
        "MARUTI.NS",
        "HDFCBANK.NS",
        "CIPLA.NS",
    ]


def test_watchlist_table_keeps_numeric_sort_fields_numeric_and_ticker_indexed():
    rows = [
        {
            "ticker": "AAA.NS",
            "company_name": "Company A",
            "current_price": 99.9,
            "is_imported": True,
            "financial_status": "Green",
            "watchlist_metrics": {
                "expected_growth": 0.1,
                "market_cap_cr": 900.4,
                "calculated_pe": 10.1,
                "rating": "Good Buy (Undervalued)",
                "revenue_growth": 0.2,
                "revenue_growth_years": 5,
                "revenue_growth_4y": 0.15,
                "profit_growth": 0.3,
                "profit_growth_years": 5,
                "profit_growth_4y": 0.25,
                "eps": 9.9,
                "eps_payback": 7.8,
                "debt_to_equity": 1.25,
            },
        },
        {
            "ticker": "BBB.NS",
            "company_name": "Company B",
            "current_price": 1000.1,
            "is_imported": True,
            "financial_status": "Orange",
            "watchlist_metrics": {
                "expected_growth": 0.2,
                "market_cap_cr": 100.2,
                "calculated_pe": 20.2,
                "rating": "Fair Value (Hold / Neutral)",
                "revenue_growth": 0.3,
                "revenue_growth_years": 5,
                "revenue_growth_4y": 0.25,
                "profit_growth": 0.4,
                "profit_growth_years": 5,
                "profit_growth_4y": 0.35,
                "eps": 50.1,
                "eps_payback": 11.2,
                "debt_to_equity": 0.75,
            },
        },
    ]

    frame = build_watchlist_table_frame(rows, {})

    assert frame.index.tolist() == ["AAA.NS", "BBB.NS"]
    assert frame.sort_values("Price").index.tolist() == ["AAA.NS", "BBB.NS"]
    assert frame.sort_values("Market Cap").index.tolist() == ["BBB.NS", "AAA.NS"]
    assert frame.sort_values("EPS Payback").index.tolist() == ["AAA.NS", "BBB.NS"]
    assert frame.loc["AAA.NS", "Price"] == 99.9
    assert frame.loc["AAA.NS", "Market Cap"] == 900.4
    assert frame.loc["AAA.NS", "EPS Payback"] == 7.8
    assert frame.loc["AAA.NS", "Rating"] == "Good Buy (Undervalued)"
    assert frame.loc["BBB.NS", "Rating"] == "Fair Value (Hold / Neutral)"
    assert frame.loc["AAA.NS", "Debt/Equity"] == 1.25
    assert frame.loc["BBB.NS", "Debt/Equity"] == 0.75
    assert "Debt/EBITDA" not in frame.columns
    assert set(frame["Source"]) == {"Screener"}
    assert "Price Source / As of" not in frame.columns
    assert is_numeric_dtype(frame["Price"])
    assert is_numeric_dtype(frame["Market Cap"])
    assert is_numeric_dtype(frame["EPS Payback"])


def test_watchlist_table_uses_numeric_nulls_for_unavailable_values():
    row = {
        "ticker": "AAA.NS",
        "company_name": "Company A",
        "current_price": None,
        "is_imported": False,
        "financial_status": "Sample data · not anomaly-validated",
        "watchlist_metrics": {
            "expected_growth": None,
            "market_cap_cr": None,
            "calculated_pe": None,
            "revenue_growth": None,
            "revenue_growth_years": None,
            "revenue_growth_4y": None,
            "profit_growth": None,
            "profit_growth_years": None,
            "profit_growth_4y": None,
            "eps": None,
            "eps_payback": None,
            "debt_to_equity": None,
        },
    }

    frame = build_watchlist_table_frame([row], {})

    assert is_numeric_dtype(frame["Price"])
    assert is_numeric_dtype(frame["Market Cap"])
    assert pd.isna(frame.loc["AAA.NS", "Price"])
    assert pd.isna(frame.loc["AAA.NS", "Market Cap"])
