from __future__ import annotations

from typing import Any
from urllib.parse import quote

import pandas as pd
import streamlit as st

from stockvisualizer.database import (
    add_to_watchlist,
    fetch_watchlist_column_order,
    fetch_watchlist_members,
    remove_from_watchlist,
    save_expected_growth_override,
    save_watchlist_column_order,
    save_watchlist_snapshot,
)
from stockvisualizer.watchlist_metrics import (
    format_anomaly_status,
    format_growth,
    format_percent,
)
from stockvisualizer.yahoo_market_data import refresh_yahoo_market_data


def resolve_selected_tickers(
    rows: list[dict[str, Any]], selections: dict[str, bool]
) -> list[str]:
    available = {str(row["ticker"]) for row in rows}
    return sorted(
        ticker
        for ticker, selected in selections.items()
        if selected and ticker in available
    )


def selection_state_for_all(
    tickers: list[str], selected: bool
) -> dict[str, bool]:
    return {ticker: selected for ticker in tickers}


def filter_and_sort_stocks(
    rows: list[dict[str, Any]],
    search: str = "",
    sort_by: str = "company_name",
    ascending: bool = True,
) -> list[dict[str, Any]]:
    allowed_fields = {
        "company_name",
        "ticker",
        "last_updated",
        "expected_growth",
    }
    if sort_by not in allowed_fields:
        raise ValueError(f"Unsupported stock sort field: {sort_by}")
    query = search.strip().casefold()
    filtered = [
        row
        for row in rows
        if not query
        or query in str(row["company_name"]).casefold()
        or query in str(row["ticker"]).casefold()
    ]
    return sorted(
        filtered,
        key=lambda row: (
            row.get(sort_by) is None,
            str(row.get(sort_by, "")).casefold()
            if isinstance(row.get(sort_by), str)
            else row.get(sort_by, 0)
            if row.get(sort_by) is not None
            else 0,
        ),
        reverse=not ascending,
    )


def screener_symbols_for_tickers(tickers: list[str]) -> list[str]:
    result = []
    for ticker in tickers:
        symbol, separator, suffix = ticker.rpartition(".")
        result.append(
            symbol if separator and suffix.upper() in {"NS", "BO"} else ticker
        )
    return result


def screener_company_url(ticker: str) -> str:
    symbol = screener_symbols_for_tickers([ticker])[0]
    return f"https://www.screener.in/company/{quote(symbol)}/"


def persist_growth_edits(
    rows: list[dict[str, Any]], edited: pd.DataFrame
) -> bool:
    changed = False
    for row in rows:
        ticker = str(row["ticker"])
        edited_value = edited.loc[ticker, "Exp Growth"]
        if pd.isna(edited_value):
            edited_growth = None
        else:
            edited_growth = float(edited_value)
        current_growth = row["watchlist_metrics"]["expected_growth"]
        if current_growth is None and edited_growth is None:
            continue
        if (
            current_growth is not None
            and edited_growth is not None
            and abs(float(current_growth) - edited_growth) < 1e-9
        ):
            continue
        save_expected_growth_override(ticker, edited_growth)
        changed = True
    return changed


def build_watchlist_table_frame(
    rows: list[dict[str, Any]],
    selected_state: dict[str, bool],
) -> pd.DataFrame:
    table_rows = []
    for row in rows:
        metrics = row["watchlist_metrics"]
        ticker = str(row["ticker"])
        table_rows.append(
            {
                "Select": bool(selected_state.get(ticker, False)),
                "Name": row["company_name"],
                "Price": row["current_price"],
                "Source": (
                    "Yahoo"
                    if row.get("price_source") == "Yahoo Finance"
                    else "Screener"
                ),
                "Exp Growth": metrics["expected_growth"],
                "Anomaly": format_anomaly_status(row["financial_status"]),
                "Market Cap": metrics["market_cap_cr"],
                "P/E": metrics["calculated_pe"],
                "Rating": metrics.get("rating", "Unavailable"),
                "Revenue Growth (Years)": format_growth(
                    metrics["revenue_growth"],
                    metrics["revenue_growth_years"],
                ),
                "Revenue Growth (4Y)": metrics["revenue_growth_4y"],
                "Profit Growth (Years)": format_growth(
                    metrics["profit_growth"],
                    metrics["profit_growth_years"],
                ),
                "Profit Growth (4Y)": metrics["profit_growth_4y"],
                "EPS": metrics["eps"],
                "EPS Payback": metrics["eps_payback"],
                "Debt/Equity": metrics.get("debt_to_equity"),
                "Screener": screener_company_url(ticker),
            }
        )
    frame = pd.DataFrame(
        table_rows, index=[str(row["ticker"]) for row in rows]
    )
    numeric_columns = (
        "Price",
        "Exp Growth",
        "Market Cap",
        "P/E",
        "Revenue Growth (4Y)",
        "Profit Growth (4Y)",
        "EPS",
        "EPS Payback",
        "Debt/Equity",
    )
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
    return frame


def normalize_watchlist_column_order(
    saved_order: list[str] | None, available_columns: list[str]
) -> list[str]:
    available = set(available_columns)
    order: list[str] = []
    for column in saved_order or []:
        if column in available and column not in order:
            order.append(column)
    for index, column in enumerate(available_columns):
        if column in order:
            continue
        previous = next(
            (
                candidate
                for candidate in reversed(available_columns[:index])
                if candidate in order
            ),
            None,
        )
        following = next(
            (
                candidate
                for candidate in available_columns[index + 1 :]
                if candidate in order
            ),
            None,
        )
        if previous is not None:
            order.insert(order.index(previous) + 1, column)
        elif following is not None:
            order.insert(order.index(following), column)
        else:
            order.append(column)
    return order


def move_watchlist_column(
    order: list[str], column: str, direction: int
) -> list[str]:
    if direction not in {-1, 1}:
        raise ValueError("Column move direction must be -1 or 1.")
    if column not in order:
        raise ValueError(f"Unknown watchlist column: {column}")
    index = order.index(column)
    destination = index + direction
    if destination < 0 or destination >= len(order):
        return list(order)
    moved = list(order)
    moved[index], moved[destination] = moved[destination], moved[index]
    return moved


def render_stock_selection(
    rows: list[dict[str, Any]],
    *,
    key: str,
    searchable: bool = True,
    sortable: bool = True,
) -> list[str]:
    if not rows:
        st.info("No stocks to display.")
        return []

    all_rows = list(rows)
    ticker_list = [str(row["ticker"]) for row in all_rows]
    search = ""
    if searchable:
        search = st.text_input(
            "Search stocks",
            key=f"{key}_search",
            placeholder="Search company or ticker",
        ).strip().casefold()
    sort_options = {
        "Company": "company_name",
        "Ticker": "ticker",
        "Last updated": "last_updated",
        "Expected growth": "expected_growth",
    }
    if sortable:
        selected_sort = st.selectbox(
            "Sort watchlist by" if key == "watchlist" else "Sort stocks by",
            list(sort_options),
            key=f"{key}_sort",
        )
        ascending = st.checkbox(
            "Ascending order", value=True, key=f"{key}_ascending"
        )
        sort_field = sort_options[selected_sort]
        rows = filter_and_sort_stocks(
            rows, search, sort_field, ascending
        )
    elif searchable and search:
        rows = filter_and_sort_stocks(rows, search)
    visible_tickers = [str(row["ticker"]) for row in rows]

    select_all_col, deselect_col = st.columns(2)
    if select_all_col.button("Select All", key=f"{key}_select_all"):
        for ticker, selected in selection_state_for_all(ticker_list, True).items():
            st.session_state[f"{key}_selected_{ticker}"] = selected
    if deselect_col.button("Deselect All", key=f"{key}_deselect_all"):
        for ticker, selected in selection_state_for_all(ticker_list, False).items():
            st.session_state[f"{key}_selected_{ticker}"] = selected

    selections: dict[str, bool] = {
        ticker: bool(st.session_state.get(f"{key}_selected_{ticker}", False))
        for ticker in ticker_list
    }
    member_tickers = {
        item["ticker"] for item in fetch_watchlist_members()
    }
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Company": row["company_name"],
                    "Ticker": row["ticker"],
                    "Current Price (INR)": row["price_display"],
                    "Market cap (Cr)": row["market_cap_display"],
                    "Expected growth": row["expected_growth_display"],
                    "Cumulative EPS Payback Years": row["payback_display"],
                    "Financial status": row["financial_status"],
                    "Last updated": row["last_updated"],
                }
                for row in rows
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "Current Price is the value in the latest Screener spreadsheet import. "
        "The export does not identify its quote timestamp; sample-data prices "
        "are not market prices. Use the per-stock controls below for selection "
        "and watchlist membership."
    )

    for row in rows:
        ticker = str(row["ticker"])
        checkbox_col, name_col, action_col = st.columns([1, 5, 2])
        selections[ticker] = checkbox_col.checkbox(
            f"Select {ticker}",
            key=f"{key}_selected_{ticker}",
            label_visibility="collapsed",
        )
        name_col.write(f"**{row['company_name']}** · `{ticker}`")
        if ticker in member_tickers:
            if action_col.button(
                "Remove from Watchlist", key=f"{key}_remove_{ticker}"
            ):
                remove_from_watchlist(ticker)
                st.rerun()
        elif action_col.button("Add to Watchlist", key=f"{key}_add_{ticker}"):
            add_to_watchlist(ticker, str(row["company_name"]))
            st.rerun()

    selected = resolve_selected_tickers(all_rows, selections)
    st.caption(f"Selected stocks: {len(selected)}")
    return selected


def render_watchlist_page(rows: list[dict[str, Any]]) -> None:
    if not rows:
        st.info("Your watchlist is empty. Add a stock to get started.")
        return

    fetch_previous_results = st.session_state.pop("yahoo_fetch_results", None)
    if fetch_previous_results is not None:
        _render_yahoo_fetch_results(fetch_previous_results)

    add_col, select_all_col, deselect_all_col, fetch_col, _ = st.columns(
        [1.4, 1, 1, 1.4, 4.6]
    )
    if add_col.button("Add stock", type="primary", use_container_width=True):
        st.session_state["navigate_to_add_stocks"] = True
        st.rerun()

    selected_state = st.session_state.setdefault("watchlist_selected_tickers", {})
    tickers = [str(row["ticker"]) for row in rows]
    if select_all_col.button("Select all", key="watchlist_select_all"):
        st.session_state["watchlist_selected_tickers"] = {
            ticker: True for ticker in tickers
        }
        st.session_state["watchlist_editor_revision"] = (
            st.session_state.get("watchlist_editor_revision", 0) + 1
        )
        st.rerun()
    if deselect_all_col.button("Deselect all", key="watchlist_deselect_all"):
        st.session_state["watchlist_selected_tickers"] = {
            ticker: False for ticker in tickers
        }
        st.session_state["watchlist_editor_revision"] = (
            st.session_state.get("watchlist_editor_revision", 0) + 1
        )
        st.rerun()
    if fetch_col.button(
        "Fetch Live Data",
        key="watchlist_fetch_live_data",
        help="Fetch Yahoo Finance quote fields for all stocks in this watchlist.",
        use_container_width=True,
    ):
        progress = st.progress(0, text="Starting Yahoo Finance refresh")

        def update_progress(index: int, total: int, ticker: str) -> None:
            progress.progress(
                index / total,
                text=f"Fetched {index} of {total}: {ticker}",
            )

        results = refresh_yahoo_market_data(
            tickers,
            progress_callback=update_progress,
        )
        st.session_state["yahoo_fetch_results"] = results
        st.rerun()

    frame = build_watchlist_table_frame(rows, selected_state)
    if "watchlist_column_order" not in st.session_state:
        st.session_state["watchlist_column_order"] = normalize_watchlist_column_order(
            fetch_watchlist_column_order(), list(frame.columns)
        )
    else:
        st.session_state["watchlist_column_order"] = normalize_watchlist_column_order(
            st.session_state["watchlist_column_order"], list(frame.columns)
        )
    with st.expander("Arrange watchlist columns"):
        column_order = st.session_state["watchlist_column_order"]
        selected_column = st.selectbox(
            "Column to move",
            column_order,
            key="watchlist_column_to_move",
        )
        selected_index = column_order.index(selected_column)
        left_col, right_col, save_col = st.columns([1, 1, 1.4])
        if left_col.button(
            "Move left",
            key="watchlist_move_column_left",
            disabled=selected_index == 0,
            use_container_width=True,
        ):
            st.session_state["watchlist_column_order"] = move_watchlist_column(
                column_order, selected_column, -1
            )
            st.session_state["watchlist_editor_revision"] = (
                st.session_state.get("watchlist_editor_revision", 0) + 1
            )
            st.rerun()
        if right_col.button(
            "Move right",
            key="watchlist_move_column_right",
            disabled=selected_index == len(column_order) - 1,
            use_container_width=True,
        ):
            st.session_state["watchlist_column_order"] = move_watchlist_column(
                column_order, selected_column, 1
            )
            st.session_state["watchlist_editor_revision"] = (
                st.session_state.get("watchlist_editor_revision", 0) + 1
            )
            st.rerun()
        if save_col.button(
            "Save column order",
            key="watchlist_save_column_order",
            type="primary",
            use_container_width=True,
        ):
            save_watchlist_column_order(column_order)
            st.success("Watchlist column order saved.")
        st.caption("Current order: " + " | ".join(column_order))
    frame = frame.loc[:, st.session_state["watchlist_column_order"]]
    revision = st.session_state.get("watchlist_editor_revision", 0)
    edited = st.data_editor(
        frame,
        key=f"watchlist_table_v2_{revision}",
        hide_index=True,
        num_rows="fixed",
        width="stretch",
        disabled=[
            column for column in frame.columns if column not in {"Select", "Exp Growth"}
        ],
        column_config={
            "Select": st.column_config.CheckboxColumn("Select", width="small"),
            "Name": st.column_config.TextColumn("Name", width=120),
            "Price": st.column_config.NumberColumn(
                "Price",
                width=75,
                format="₹%.0f",
                help=(
                    "Yahoo Finance price after Fetch Live Data; otherwise uses "
                    "the last Screener spreadsheet import."
                ),
            ),
            "Source": st.column_config.TextColumn("Source", width=85),
            "Anomaly": st.column_config.TextColumn(
                "Anomaly",
                width=100,
                help=(
                    "Saved financial anomaly status: Green, Orange, or Red. "
                    "Sample or unassessed stocks are marked Not assessed."
                ),
            ),
            "Market Cap": st.column_config.NumberColumn(
                "Market Cap",
                width=95,
                format="%.0f Cr",
                help="Market capitalization in crore, rounded to a whole crore.",
            ),
            "P/E": st.column_config.NumberColumn(
                "P/E",
                width=65,
                format="%.2fx",
                help=(
                    "Yahoo trailing P/E after Fetch Live Data; otherwise "
                    "calculated from the spreadsheet price and latest EPS."
                ),
            ),
            "Rating": st.column_config.TextColumn(
                "Rating",
                width=190,
                help=(
                    "Growth-adjusted valuation score using actual P/E and "
                    "Expected Growth. Positive Expected Growth is required."
                ),
            ),
            "Revenue Growth (4Y)": st.column_config.NumberColumn(
                "Revenue Growth (4Y)", width=120, format="percent"
            ),
            "Revenue Growth (Years)": st.column_config.TextColumn(
                "Revenue Growth (Years)", width=171
            ),
            "Exp Growth": st.column_config.NumberColumn(
                "Exp Growth",
                width=105,
                format="percent",
                min_value=-0.999999,
                step=0.01,
                help=(
                    "Calculated average. Enter a decimal fraction when editing "
                    "(0.15 means 15%). Clear to restore the calculation. "
                    "Reimporting data clears overrides."
                ),
            ),
            "Profit Growth (Years)": st.column_config.TextColumn(
                "Profit Growth (Years)", width=171
            ),
            "Profit Growth (4Y)": st.column_config.NumberColumn(
                "Profit Growth (4Y)", width=120, format="percent"
            ),
            "EPS": st.column_config.NumberColumn(
                "EPS", width=65, format="%.2f"
            ),
            "EPS Payback": st.column_config.NumberColumn(
                "EPS Payback",
                width=100,
                format="%.0f years",
                help="Payback estimate displayed rounded to a whole year.",
            ),
            "Debt/Equity": st.column_config.NumberColumn(
                "Debt/Equity",
                width=100,
                format="%.4fx",
                help=(
                    "Yahoo Finance debt-to-equity ratio. Uses Yahoo's ratio "
                    "field or derives total debt ÷ stockholders' equity from "
                    "Yahoo's balance sheet when needed."
                ),
            ),
            "Screener": st.column_config.LinkColumn(
                "Screener",
                width=70,
                display_text="Open",
                help="Open this company's Screener.in page.",
            ),
        },
    )
    selected_state = {
        ticker: bool(edited.loc[ticker, "Select"])
        for ticker in tickers
    }
    st.session_state["watchlist_selected_tickers"] = selected_state
    if persist_growth_edits(rows, edited):
        st.session_state["watchlist_editor_revision"] = revision + 1
        st.rerun()

    selected_tickers = [
        ticker for ticker in tickers if selected_state.get(ticker, False)
    ]
    action_col, count_col = st.columns([1, 5])
    if action_col.button(
        "Refresh selected",
        disabled=not selected_tickers,
        use_container_width=True,
    ):
        _queue_screener_action(selected_tickers, "refresh")
    count_col.caption(f"{len(selected_tickers)} stock(s) selected")
    st.caption(
        "Exp Growth averages available revenue and profit CAGR metrics. "
        "You can edit Exp Growth per stock; reimporting clears the override. "
        "Fetch Live Data stores Yahoo Finance price, market cap, trailing P/E and "
        "EPS, and debt-to-equity until reimport."
    )


def _render_yahoo_fetch_results(results: list[dict[str, str]]) -> None:
    succeeded = sum(result["status"] == "success" for result in results)
    partial = sum(result["status"] == "partial" for result in results)
    failed = sum(result["status"] == "failed" for result in results)
    st.info(
        f"Yahoo Finance refresh complete: {succeeded} complete, "
        f"{partial} partial, {failed} failed."
    )
    with st.expander("Yahoo Finance fetch details"):
        for result in results:
            message = f"{result['ticker']}: {result['message']}"
            if result["status"] == "success":
                st.success(message)
            elif result["status"] == "partial":
                st.warning(message)
            else:
                st.error(message)


def render_bulk_actions(selected_tickers: list[str], key: str) -> None:
    if not selected_tickers:
        return
    st.subheader("Bulk actions")
    st.caption("Actions below apply only to: " + ", ".join(selected_tickers))
    download_col, refresh_col, remove_col, snapshot_col = st.columns(4)
    if download_col.button(
        "Bulk Download from Screener",
        key=f"{key}_bulk_download",
        use_container_width=True,
    ):
        _queue_screener_action(selected_tickers, "download")
    if refresh_col.button(
        "Bulk Refresh Data",
        key=f"{key}_bulk_refresh",
        use_container_width=True,
        help="Fetches a new Screener export; preview and explicit import confirmation are still required.",
    ):
        _queue_screener_action(selected_tickers, "refresh")
    if remove_col.button(
        "Remove selected from Watchlist",
        key=f"{key}_bulk_remove",
        use_container_width=True,
    ):
        st.session_state[f"{key}_confirm_remove"] = True
        st.session_state[f"{key}_remove_confirmation_version"] = (
            st.session_state.get(f"{key}_remove_confirmation_version", 0) + 1
        )
    if snapshot_col.button(
        "Save selected as Watchlist Snapshot",
        key=f"{key}_bulk_snapshot",
        use_container_width=True,
    ):
        st.session_state[f"{key}_confirm_snapshot"] = True
        st.session_state[f"{key}_snapshot_confirmation_version"] = (
            st.session_state.get(f"{key}_snapshot_confirmation_version", 0) + 1
        )

    if st.session_state.get(f"{key}_confirm_remove"):
        confirmation_key = (
            f"{key}_confirm_remove_checkbox_"
            f"{st.session_state[f'{key}_remove_confirmation_version']}"
        )
        confirmed = st.checkbox(
            f"Confirm removing these {len(selected_tickers)} selected stock(s).",
            key=confirmation_key,
        )
        if st.button(
            "Confirm removal",
            key=f"{key}_confirm_remove_submit_"
            f"{st.session_state[f'{key}_remove_confirmation_version']}",
            disabled=not confirmed,
        ):
            removed = sum(
                remove_from_watchlist(ticker) for ticker in selected_tickers
            )
            st.session_state.pop(f"{key}_confirm_remove", None)
            st.success(f"Removed {removed} selected stock(s) from the watchlist.")
            st.rerun()

    if st.session_state.get(f"{key}_confirm_snapshot"):
        confirmation_key = (
            f"{key}_confirm_snapshot_checkbox_"
            f"{st.session_state[f'{key}_snapshot_confirmation_version']}"
        )
        confirmed = st.checkbox(
            f"Confirm saving a snapshot of these {len(selected_tickers)} selected stock(s).",
            key=confirmation_key,
        )
        if st.button(
            "Confirm snapshot",
            key=f"{key}_confirm_snapshot_submit_"
            f"{st.session_state[f'{key}_snapshot_confirmation_version']}",
            disabled=not confirmed,
        ):
            snapshot_id = save_watchlist_snapshot(selected_tickers)
            st.session_state.pop(f"{key}_confirm_snapshot", None)
            st.success(f"Watchlist snapshot saved: {snapshot_id[:8]}")


def _queue_screener_action(tickers: list[str], action: str) -> None:
    symbols = screener_symbols_for_tickers(tickers)
    st.session_state["pending_bulk_download_symbols"] = symbols
    st.session_state["screener_browser_action"] = action
    st.session_state["navigate_to_screener_imports"] = True
    st.rerun()
