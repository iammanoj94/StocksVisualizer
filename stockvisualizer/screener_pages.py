from __future__ import annotations

import io
import re
import sqlite3
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import pandas as pd
import streamlit as st

from stockvisualizer.calculations.anomaly_detection import AnomalyConfig
from stockvisualizer.screener_browser import (
    ScreenerBrowserSession,
    iter_download_results,
    parse_symbol_queue,
)
from stockvisualizer.database import (
    add_to_watchlist,
    fetch_screener_companies,
    fetch_screener_observations,
    fetch_screener_snapshots,
    fetch_watchlist_members,
    find_screener_imports_by_hash,
    remove_from_watchlist,
    save_screener_snapshot,
)
from stockvisualizer.screener_analysis import build_screener_analysis
from stockvisualizer.screener_import import ScreenerPreview, parse_screener_file
from stockvisualizer.price_data import exchange_from_symbol
from stockvisualizer.stock_catalog import build_stock_rows
from stockvisualizer.watchlist_ui import render_bulk_actions, render_stock_selection


_TICKER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._&-]{0,30}$")


@dataclass(frozen=True)
class _PendingExport:
    name: str
    content: bytes
    symbol: str

    def getvalue(self) -> bytes:
        return self.content


def _company_mapping(name: str | None) -> str:
    if not name:
        return ""
    normalized = " ".join(name.casefold().split())
    return next(
        (
            item["ticker"]
            for item in fetch_screener_companies()
            if " ".join(item["company_name"].casefold().split()) == normalized
        ),
        "",
    )


def _preview_frame(preview: ScreenerPreview) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Statement": item.statement.replace("_", " ").title(),
                "Period": item.period,
                "Metric": item.metric.replace("_", " ").title(),
                "Value": item.value,
                "Unit": item.unit,
                "Source": item.value_source,
                "Raw source value": item.raw_value,
                "Invalid source value": item.invalid_value,
            }
            for item in preview.observations
        ]
    )


def _current_config() -> AnomalyConfig:
    with st.expander("Anomaly threshold settings", expanded=False):
        lookback = st.number_input("Historical lookback (annual growth rates)", 3, 10, 5)
        minimum = st.number_input("Minimum prior observations", 3, int(lookback), 3)
        cutoff = st.number_input(
            "Robust deviation cutoff (scaled MAD)", 1.0, 6.0, 3.0, step=0.5
        )
        tolerance = st.number_input(
            "Zero-MAD rounding tolerance (growth/log fraction)",
            0.0,
            0.2,
            0.02,
            step=0.01,
            format="%.2f",
        )
        period_tolerance = st.number_input(
            "Annual period interval tolerance (days)", 0, 60, 14
        )
    return AnomalyConfig(
        lookback=int(lookback),
        minimum_history=int(minimum),
        robust_scale_cutoff=float(cutoff),
        zero_mad_tolerance=float(tolerance),
        period_tolerance_days=int(period_tolerance),
    )


def _cagr_value(metrics: dict[str, Any], metric: str) -> float | None:
    legacy_key = (
        "revenue_cagr_10y"
        if metric == "revenue"
        else "net_profit_cagr_10y"
    )
    return metrics.get(f"{metric}_cagr", metrics.get(legacy_key))


def _cagr_period(metrics: dict[str, Any], metric: str) -> int | None:
    current_period = metrics.get(f"{metric}_cagr_period")
    if current_period is not None:
        return int(current_period)
    legacy_key = (
        "revenue_cagr_10y"
        if metric == "revenue"
        else "net_profit_cagr_10y"
    )
    return 10 if metrics.get(legacy_key) is not None else None


def _cagr_label(metrics: dict[str, Any], metric: str) -> str:
    label = "Revenue" if metric == "revenue" else "Net profit"
    period = _cagr_period(metrics, metric)
    return (
        f"{label} CAGR ({period}Y)"
        if period is not None
        else f"{label} CAGR (max 9Y)"
    )


def _exchange_label(ticker: str) -> str:
    exchange = exchange_from_symbol(ticker)
    if "inferred" in exchange:
        return exchange
    return "Unknown (not supplied by Screener export)"


def _render_assisted_browser_downloads() -> None:
    pending_symbols = st.session_state.pop("pending_bulk_download_symbols", None)
    if pending_symbols:
        st.session_state["screener_browser_symbols"] = "\n".join(pending_symbols)
        st.session_state["screener_browser_workflow_active"] = True
    st.session_state.setdefault(
        "screener_browser_symbols", "HDFCBANK\nMARUTI\nCIPLA"
    )
    with st.expander(
        "Screener sign-in and downloads",
        expanded=bool(st.session_state.get("screener_browser_workflow_active")),
    ):
        st.caption(
            "Uses the visible Screener company page and Export to Excel control. "
            "The browser opens on the machine running Streamlit. Sign in manually; "
            "StockVisualizer never reads or saves your password. The temporary "
            "browser profile and its login session are destroyed when it closes."
        )
        st.warning(
            "Use this only if your Screener account permits automated use of its "
            "normal export control. CAPTCHA, login restrictions, and unexpected "
            "page changes stop the queue; none are bypassed."
        )
        symbols_text = st.text_area(
            "Screener company symbols (one per line; maximum 100)",
            key="screener_browser_symbols",
        )
        delay_seconds = st.number_input(
            "Minimum delay between company pages (seconds)",
            min_value=3,
            max_value=30,
            value=3,
            step=1,
            key="screener_browser_delay",
        )
        queue = None
        try:
            queue = parse_symbol_queue(symbols_text)
            st.caption(
                f"Queue: {len(queue.symbols)} unique symbols"
                + (
                    f" · duplicate entries ignored: {', '.join(queue.duplicates)}"
                    if queue.duplicates
                    else ""
                )
            )
        except ValueError as error:
            st.error(str(error))
        if st.session_state.get("screener_browser_action") == "refresh":
            st.caption(
                "Bulk Refresh uses the existing Screener export/import workflow. "
                "New files still require preview, ticker confirmation, and explicit import."
            )

        pending = st.session_state.setdefault("screener_pending_downloads", [])
        if pending:
            st.info(
                f"{len(pending)} downloaded file(s) are awaiting preview and "
                "confirmation below."
            )
            if st.button("Discard pending browser downloads"):
                st.session_state["screener_pending_downloads"] = []
                st.session_state["screener_browser_workflow_active"] = False
                st.rerun()

        browser = st.session_state.get("screener_browser_session")
        if browser is None:
            if st.button("Open temporary browser for manual sign-in"):
                try:
                    browser = ScreenerBrowserSession()
                except RuntimeError as error:
                    st.error(str(error))
                else:
                    st.session_state["screener_browser_session"] = browser
                    st.rerun()
        else:
            st.info(
                "The temporary browser is open. Complete sign-in manually in that "
                "window before starting the queue."
            )
            confirmed_login = st.checkbox(
                "I signed in manually in the temporary browser and authorize this queue.",
                key="screener_browser_login_confirmed",
            )
            if st.button("Close temporary browser"):
                browser.close()
                st.session_state.pop("screener_browser_session", None)
                st.session_state.pop("screener_browser_login_confirmed", None)
                st.rerun()
            if st.button(
                "Download queued exports",
                type="primary",
                disabled=queue is None or not confirmed_login,
            ):
                existing_exports = {
                    (item["symbol"], item["content_sha256"])
                    for item in pending
                    if item.get("symbol") and item.get("content_sha256")
                }
                downloaded_exports: set[tuple[str, str]] = set()
                progress = st.progress(0.0)
                succeeded: list[str] = []
                duplicates: list[str] = []
                failures: list[str] = []
                completed = 0
                stopped = False
                try:
                    for index, result in enumerate(
                        iter_download_results(
                            queue.symbols,
                            lambda symbol: browser.download_one(
                                symbol, int(delay_seconds)
                            ),
                        ),
                        start=1,
                    ):
                        symbol = result.symbol
                        if result.error:
                            failures.append(f"{symbol}: {result.error}")
                            completed += 1
                            progress.progress(
                                index / len(queue.symbols),
                                text=f"Completed {completed}/{len(queue.symbols)}",
                            )
                            stopped = result.stop_queue
                            continue
                        if (
                            result.filename is None
                            or result.content is None
                            or result.content_sha256 is None
                        ):
                            failures.append(
                                f"{symbol}: the browser returned an incomplete "
                                "download result."
                            )
                            completed += 1
                            progress.progress(
                                index / len(queue.symbols),
                                text=f"Completed {completed}/{len(queue.symbols)}",
                            )
                            continue
                        export_key = (symbol, result.content_sha256)
                        if (
                            export_key in existing_exports
                            or export_key in downloaded_exports
                        ):
                            duplicates.append(symbol)
                        else:
                            pending.append(
                                {
                                    "symbol": symbol,
                                    "filename": result.filename,
                                    "content": result.content,
                                    "content_sha256": result.content_sha256,
                                }
                            )
                            succeeded.append(symbol)
                            downloaded_exports.add(export_key)
                            existing_exports.add(export_key)
                        completed += 1
                        progress.progress(
                            index / len(queue.symbols),
                            text=f"Completed {completed}/{len(queue.symbols)}",
                        )
                finally:
                    browser.close()
                    st.session_state.pop("screener_browser_session", None)
                    st.session_state.pop("screener_browser_login_confirmed", None)
                st.session_state["screener_pending_downloads"] = pending
                if succeeded:
                    st.success(
                        f"Downloaded {len(succeeded)} export(s): "
                        + ", ".join(succeeded)
                    )
                if duplicates:
                    st.info("Skipped duplicate exports: " + ", ".join(duplicates))
                for failure in failures:
                    st.error(failure)
                st.caption(
                    f"Download queue: {completed} completed · "
                    f"{len(failures)} failed · {len(succeeded)} new file(s) retained."
                )
                if stopped:
                    st.warning("The queue stopped because a login/access or page safety condition was detected.")
                elif not succeeded and not duplicates and not failures:
                    st.info("No exports were downloaded.")
                if pending:
                    st.caption(
                        "Downloaded files are now parsed and previewed below. "
                        "They are kept in this Streamlit session's memory until "
                        "imported or discarded."
                    )


def _render_import(config: AnomalyConfig) -> None:
    st.title("Import Screener exports")
    st.caption(
        "Imports are local only. No API calls or undocumented endpoints are used. "
        "Browser-assisted export is optional and uses the visible company-page "
        "control; bulk manual upload remains available."
    )
    _render_assisted_browser_downloads()
    manual_files = st.file_uploader(
        "Select one or more Screener Excel or Data Sheet CSV exports",
        type=["xlsx", "csv"],
        accept_multiple_files=True,
    )
    pending_downloads = st.session_state.get("screener_pending_downloads", [])
    files = [
        _PendingExport(item["filename"], item["content"], item["symbol"])
        for item in pending_downloads
    ] + list(manual_files or [])
    if not files:
        return

    previews: list[tuple[Any, ScreenerPreview]] = [
        (uploaded, parse_screener_file(uploaded.name, uploaded.getvalue()))
        for uploaded in files
    ]
    selections: dict[
        str, tuple[Any, ScreenerPreview, str, bool, str, dict[str, Any]]
    ] = {}
    preflight_failures: list[str] = []
    unsupported_count = 0
    missing_summary = [
        f"{preview.filename}: {', '.join(preview.missing_metrics)}"
        for _, preview in previews
        if preview.missing_metrics
    ]
    seen_hashes: set[str] = set()
    for index, (uploaded, preview) in enumerate(previews):
        key = preview.content_sha256[:16]
        selection_key = f"{key}_{index}"
        st.subheader(preview.filename)
        if isinstance(uploaded, _PendingExport):
            st.caption(
                f"Downloaded from Screener company symbol "
                f"{uploaded.symbol}; review and confirm the "
                "exchange ticker below before importing."
            )
        if preview.unsupported_reason:
            st.error(f"Unsupported format: {preview.unsupported_reason}")
            unsupported_count += 1
            continue
        if not preview.company_name:
            st.error("Company identity is missing; this file cannot be committed.")
            preflight_failures.append(f"{preview.filename}: company name is missing.")
            continue
        st.write(
            f"**Company detected:** {preview.company_name} · "
            f"**Annual periods:** {len(preview.periods)} "
            f"({preview.periods[0]} to {preview.periods[-1]})"
            if preview.periods
            else f"**Company detected:** {preview.company_name} · No annual periods"
        )
        if preview.missing_metrics:
            st.warning("Missing metrics: " + ", ".join(preview.missing_metrics))
        for warning in preview.warnings:
            st.warning(warning)
        requires_mapping_review = any(
            warning.startswith("Unmapped statement labels")
            for warning in preview.warnings
        )
        mapping_reviewed = (
            st.checkbox(
                "I reviewed the unmapped statement labels and approve this partial mapping",
                key=f"mapping_{selection_key}",
            )
            if requires_mapping_review
            else True
        )
        st.dataframe(_preview_frame(preview), hide_index=True, width="stretch")
        duplicates = find_screener_imports_by_hash(preview.content_sha256)
        duplicate_choice = "Import as a new snapshot"
        repeated_in_batch = preview.content_sha256 in seen_hashes
        seen_hashes.add(preview.content_sha256)
        if duplicates or repeated_in_batch:
            st.warning(
                (
                    "This exact file also appears more than once in this selection. "
                    if repeated_in_batch
                    else ""
                )
                + (
                    "Exact file content was imported before: "
                    + ", ".join(
                        f"{item['ticker']} ({item['imported_at']})"
                        for item in duplicates
                    )
                    if duplicates
                    else ""
                )
            )
            duplicate_choice = st.radio(
                "Duplicate-file action",
                ("Skip this file", "Re-import as a new permanent snapshot"),
                key=f"duplicate_{selection_key}",
                horizontal=True,
            )
        suggested_ticker = (
            f"{uploaded.symbol}.NS"
            if isinstance(uploaded, _PendingExport)
            else _company_mapping(preview.company_name)
        )
        ticker = st.text_input(
            "Confirm exchange ticker / symbol",
            value=suggested_ticker,
            key=f"ticker_{selection_key}",
            help="The workbook has a company name but no exchange symbol. Confirm the ticker explicitly.",
        ).strip().upper()
        confirmed = st.checkbox(
            f"I confirm {preview.company_name} maps to {ticker or '[ticker required]'}",
            value=bool(suggested_ticker),
            key=f"confirm_{selection_key}",
        )
        valid = (
            bool(_TICKER_PATTERN.fullmatch(ticker))
            and confirmed
            and mapping_reviewed
        )
        if not valid:
            st.info(
                "A valid ticker, company/ticker confirmation, and required mapping "
                "review are needed before import."
            )
        reporting_basis = st.selectbox(
            "Reporting basis (confirm from the source if known)",
            ("Unknown", "Consolidated", "Standalone", "Needs review"),
            key=f"basis_{selection_key}",
            help="The workbook does not identify this basis; leave Unknown unless manually verified.",
        )
        if not preview.observations:
            st.error("No normalized observations were parsed; this file cannot be imported.")
            preflight_failures.append(
                f"{preview.filename}: no normalized observations were parsed."
            )
            continue
        prior_snapshots = fetch_screener_snapshots(ticker) if ticker else []
        previous_reporting_basis = (
            prior_snapshots[0]["reporting_basis"] if prior_snapshots else None
        )
        normalized = [item.to_dict() for item in preview.observations]
        preview_analysis = build_screener_analysis(
            normalized,
            preview.current_price,
            config,
            preview.missing_metrics,
            preview.warnings,
            reporting_basis,
            previous_reporting_basis,
        )
        preview_analysis["metrics"]["market_cap_cr"] = preview.market_cap_cr
        preview_analysis["metrics"]["reported_pe_from_source"] = preview.reported_pe
        st.caption(
            f"Pre-commit financial status: {preview_analysis['financial_status']} · "
            f"Reporting metadata: {preview_analysis['reporting_metadata_status']}"
        )
        metric_columns = st.columns(7)
        for column, label, key in zip(
            metric_columns,
            (
                _cagr_label(preview_analysis["metrics"], "revenue"),
                "Revenue CAGR 4Y",
                _cagr_label(preview_analysis["metrics"], "net_profit"),
                "Net profit CAGR 4Y",
                "Expected growth",
                "P/E (reported EPS)",
                "P/E (derived EPS)",
            ),
            (
                "revenue_cagr",
                "revenue_cagr_4y",
                "net_profit_cagr",
                "net_profit_cagr_4y",
                "expected_growth",
                "reported_pe",
                "derived_eps_pe",
            ),
        ):
            value = preview_analysis["metrics"].get(key)
            is_multiple = key in {"reported_pe", "derived_eps_pe"}
            column.metric(
                label,
                f"{value:.1f}x"
                if value is not None and is_multiple
                else f"{value:.1%}"
                if value is not None
                else "N/A",
            )
        st.caption(
            f"Latest EPS: {preview_analysis['metrics']['latest_eps']} "
            f"({preview_analysis['metrics']['latest_eps_source'] or 'unavailable'}) · "
            f"Educational screen: {preview_analysis['metrics']['rating']} · "
            "Normalized Core P/E: unavailable"
        )
        st.caption(
            (
                f"Current Price from spreadsheet: INR {preview.current_price:,.2f}"
                if preview.current_price is not None
                else "Current Price from spreadsheet: unavailable"
            )
            + " · Quote timestamp is not provided by the export."
        )
        contributors = preview_analysis["metrics"]["expected_growth_contributors"]
        st.caption(
            "Expected Growth contributors: "
            + (
                ", ".join(
                    f"{item['metric']} {item['value']:.1%}"
                    for item in contributors
                )
                if contributors
                else "none"
            )
        )
        if preview_analysis["findings"]:
            st.dataframe(
                pd.DataFrame(preview_analysis["findings"]),
                hide_index=True,
                width="stretch",
            )
        selections[selection_key] = (
            uploaded,
            preview,
            ticker,
            valid,
            duplicate_choice,
            preview_analysis,
        )

    if not selections:
        st.info(
            f"Import summary: successful 0 · failed {len(preflight_failures)} · "
            f"unsupported {unsupported_count}."
        )
        for failure in preflight_failures:
            st.error(failure)
        return
    if st.button("Import selected files", type="primary"):
        succeeded: list[str] = []
        skipped: list[str] = []
        failed: list[str] = list(preflight_failures)
        consumed_pending_exports: set[tuple[str, str]] = set()
        for (
            uploaded,
            preview,
            ticker,
            valid,
            duplicate_choice,
            analysis,
        ) in selections.values():
            if duplicate_choice == "Skip this file":
                skipped.append(preview.filename)
                if isinstance(uploaded, _PendingExport):
                    if valid:
                        add_to_watchlist(ticker, preview.company_name)
                    consumed_pending_exports.add(
                        (uploaded.symbol, preview.content_sha256)
                    )
                continue
            if not valid:
                failed.append(f"{preview.filename}: ticker confirmation is incomplete.")
                continue
            try:
                snapshot_id = save_screener_snapshot(
                    ticker=ticker,
                    company_name=preview.company_name or ticker,
                    filename=preview.filename,
                    content_sha256=preview.content_sha256,
                    observations=[item.to_dict() for item in preview.observations],
                    analysis=analysis,
                    current_price=preview.current_price,
                )
                if isinstance(uploaded, _PendingExport):
                    add_to_watchlist(ticker, preview.company_name or ticker)
                succeeded.append(f"{preview.filename} → {ticker} ({snapshot_id[:8]})")
                if isinstance(uploaded, _PendingExport):
                    consumed_pending_exports.add(
                        (uploaded.symbol, preview.content_sha256)
                    )
            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                sqlite3.Error,
            ) as error:
                failed.append(f"{preview.filename}: {error}")
        if consumed_pending_exports:
            st.session_state["screener_pending_downloads"] = [
                item
                for item in st.session_state.get("screener_pending_downloads", [])
                if (item["symbol"], item["content_sha256"])
                not in consumed_pending_exports
            ]
            if not st.session_state["screener_pending_downloads"]:
                st.session_state["screener_browser_workflow_active"] = False
        st.subheader("Import summary")
        st.write(
            f"Successful: {len(succeeded)} · Skipped duplicates: {len(skipped)} · "
            f"Failed: {len(failed)} · Unsupported files: {unsupported_count}"
        )
        for missing in missing_summary:
            st.warning(f"Missing metrics — {missing}")
        for item in succeeded:
            st.success(item)
        for item in skipped:
            st.info(f"Skipped duplicate: {item}")
        for item in failed:
            st.error(item)


def _snapshot_label(item: dict[str, Any]) -> str:
    return (
        f"{item['ticker']} · {item['imported_at']} · "
        f"{item['source_filename']} · {item['snapshot_id'][:8]}"
    )


def _snapshot_observation_frame(snapshot_id: str) -> pd.DataFrame:
    return pd.DataFrame(fetch_screener_observations(snapshot_id))


def _render_comparison(snapshots: list[dict[str, Any]]) -> None:
    st.subheader("Snapshot comparison")
    tickers = sorted({item["ticker"] for item in snapshots})
    ticker = st.selectbox("Company", tickers, key="compare_ticker")
    same_company = [item for item in snapshots if item["ticker"] == ticker]
    labels = {_snapshot_label(item): item for item in same_company}
    mode = st.radio(
        "Compare",
        ("Two snapshots", "Snapshot against latest saved import"),
        horizontal=True,
    )
    if len(same_company) < 2:
        st.info("Import a second snapshot for this ticker to compare versions.")
        return
    if mode == "Two snapshots":
        left_label = st.selectbox(
            "Select snapshots",
            list(labels),
            index=0,
            key="compare_pair",
        )
        right_label = st.selectbox(
            "Against",
            [label for label in labels if label != left_label],
            key="compare_pair_right",
        )
        older, newer = sorted(
            (labels[left_label], labels[right_label]),
            key=lambda item: item["imported_at"],
        )
    else:
        base = st.selectbox(
            "Snapshot to compare",
            [item for item in same_company if item["snapshot_id"] != same_company[0]["snapshot_id"]],
            format_func=_snapshot_label,
        )
        older, newer = base, same_company[0]

    first = _snapshot_observation_frame(older["snapshot_id"])
    second = _snapshot_observation_frame(newer["snapshot_id"])
    join_keys = ["statement", "period", "metric"]
    comparison = first.merge(
        second,
        on=join_keys,
        how="outer",
        suffixes=("_previous", "_current"),
        indicator=True,
    )
    comparison["Change"] = comparison.apply(
        lambda row: (
            "Added"
            if row["_merge"] == "right_only"
            else "Removed"
            if row["_merge"] == "left_only"
            else "Changed"
            if row["value_previous"] != row["value_current"]
            else "Unchanged"
        ),
        axis=1,
    )
    st.dataframe(
        comparison[
            [
                "statement",
                "period",
                "metric",
                "value_previous",
                "value_current",
                "unit_current",
                "Change",
            ]
        ],
        hide_index=True,
        width="stretch",
    )
    metric_keys = (
        "revenue_cagr",
        "revenue_cagr_4y",
        "net_profit_cagr",
        "net_profit_cagr_4y",
        "expected_growth",
        "latest_eps",
        "reported_pe",
        "derived_eps_pe",
        "cumulative_eps_payback_years",
    )
    metric_comparison = [
        {
            "Metric": (
                f"{_cagr_label(older['metrics'], 'revenue')} vs "
                f"{_cagr_label(newer['metrics'], 'revenue')}"
                if key == "revenue_cagr"
                else f"{_cagr_label(older['metrics'], 'net_profit')} vs "
                f"{_cagr_label(newer['metrics'], 'net_profit')}"
                if key == "net_profit_cagr"
                else "Archived export P/E (price as-of unknown)"
                if key == "reported_pe"
                else "Archived P/E (derived EPS; price as-of unknown)"
                if key == "derived_eps_pe"
                else key.replace("_", " ").title()
            ),
            "Earlier snapshot": (
                _cagr_value(older["metrics"], "revenue")
                if key == "revenue_cagr"
                else _cagr_value(older["metrics"], "net_profit")
                if key == "net_profit_cagr"
                else older["metrics"].get(key)
            ),
            "Later/current snapshot": (
                _cagr_value(newer["metrics"], "revenue")
                if key == "revenue_cagr"
                else _cagr_value(newer["metrics"], "net_profit")
                if key == "net_profit_cagr"
                else newer["metrics"].get(key)
            ),
        }
        for key in metric_keys
    ]
    st.subheader("Analysis metric comparison")
    st.dataframe(
        pd.DataFrame(metric_comparison), hide_index=True, width="stretch"
    )
    if older["reporting_basis"] != newer["reporting_basis"]:
        st.warning(
            "Reporting basis differs between these snapshots "
            f"({older['reporting_basis']} vs {newer['reporting_basis']}); "
            "financial comparisons require manual review."
        )
    st.warning(
        "Saved Screener export prices have no source as-of timestamp. Price-based "
        "multiples in these snapshots are archived values and may not be directly "
        "comparable."
    )
    left_status, right_status = st.columns(2)
    left_status.metric("Earlier financial status", older["financial_status"])
    right_status.metric("Later financial status", newer["financial_status"])


def _render_imported_overview(snapshots: list[dict[str, Any]]) -> None:
    latest_by_ticker: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        latest_by_ticker.setdefault(snapshot["ticker"], snapshot)
    if not latest_by_ticker:
        return
    st.info(
        "Current Price below is taken from each company's latest imported "
        "Screener spreadsheet. Screener exports do not include a quote timestamp."
    )
    catalog_rows = [
        row
        for row in build_stock_rows()
        if row["ticker"] in latest_by_ticker
    ]
    st.subheader("Select imported stocks")
    selected = render_stock_selection(catalog_rows, key="imported_stocks")
    render_bulk_actions(selected, "imported_stocks")
    rows = []
    for ticker, snapshot in sorted(
        latest_by_ticker.items(), key=lambda item: item[1]["company_name"].casefold()
    ):
        symbol = ticker.split(".", 1)[0]
        metrics = snapshot["metrics"]
        row_data = next(
            (item for item in catalog_rows if item["ticker"] == ticker), None
        )
        rows.append(
            {
                "Company": snapshot["company_name"],
                "Ticker": ticker,
                "Latest snapshot": snapshot["imported_at"],
                "Financial status": snapshot["financial_status"],
                "Reporting metadata": snapshot["reporting_metadata_status"],
                "Current Price (INR)": row_data["price_display"] if row_data else "Unavailable",
                "Import time": snapshot["imported_at"],
                "Revenue CAGR": (
                    f"{metrics.get('revenue_cagr', metrics.get('revenue_cagr_10y')):.1%} "
                    f"({_cagr_period(metrics, 'revenue')}Y)"
                    if _cagr_value(metrics, "revenue") is not None
                    else "N/A"
                ),
                "Revenue CAGR 4Y": metrics.get("revenue_cagr_4y"),
                "Net profit CAGR": (
                    f"{metrics.get('net_profit_cagr', metrics.get('net_profit_cagr_10y')):.1%} "
                    f"({_cagr_period(metrics, 'net_profit')}Y)"
                    if _cagr_value(metrics, "net_profit") is not None
                    else "N/A"
                ),
                "Net profit CAGR 4Y": metrics.get("net_profit_cagr_4y"),
                "Expected growth": metrics.get("expected_growth"),
                "Screener": f"https://www.screener.in/company/{quote(symbol)}/",
            }
        )
    st.subheader("Imported companies")
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Revenue CAGR": st.column_config.TextColumn(),
            "Revenue CAGR 4Y": st.column_config.NumberColumn(format="%.1%"),
            "Net profit CAGR": st.column_config.TextColumn(),
            "Net profit CAGR 4Y": st.column_config.NumberColumn(format="%.1%"),
            "Expected growth": st.column_config.NumberColumn(format="%.1%"),
            "Screener": st.column_config.LinkColumn("Screener company page"),
        },
    )


def _render_snapshot_detail(snapshot: dict[str, Any]) -> None:
    st.title(f"{snapshot['company_name']} · {snapshot['ticker']}")
    st.caption(
        f"Screener export snapshot · {snapshot['imported_at']} · "
        f"Source file: {snapshot['source_filename']}"
    )
    status_col, metadata_col = st.columns(2)
    status_col.metric("Financial anomaly status", snapshot["financial_status"])
    metadata_col.metric(
        "Reporting metadata",
        snapshot["reporting_metadata_status"],
        delta=snapshot["reporting_basis"],
        help="Confirm this basis from the source; unknown metadata does not change financial status.",
    )
    symbol = snapshot["ticker"].split(".", 1)[0]
    watchlist_tickers = {
        item["ticker"] for item in fetch_watchlist_members()
    }
    if snapshot["ticker"] in watchlist_tickers:
        if st.button(
            "Remove from Watchlist",
            key=f"imported_remove_{snapshot['ticker']}",
        ):
            remove_from_watchlist(snapshot["ticker"])
            st.rerun()
    elif st.button(
        "Add to Watchlist",
        key=f"imported_add_{snapshot['ticker']}",
    ):
        add_to_watchlist(snapshot["ticker"], snapshot["company_name"])
        st.rerun()
    st.link_button(
        "Open Screener company page for manual verification",
        f"https://www.screener.in/company/{quote(symbol)}/",
    )
    st.caption(
        "The URL is constructed from the confirmed ticker symbol; verify the company "
        "and reporting basis on Screener before relying on it."
    )
    metrics = snapshot["metrics"]
    spreadsheet_price = snapshot.get("current_price")
    st.metric(
        "Current Price (from Screener spreadsheet)",
        f"INR {spreadsheet_price:,.2f}" if spreadsheet_price is not None else "Unavailable",
        help="This is the price value in the saved spreadsheet. The export does not include its quote timestamp.",
    )
    st.caption(
        f"Spreadsheet import time: {snapshot['imported_at']} · "
        "Quote timestamp is not specified in the export."
    )
    columns = st.columns(4)
    for column, label, key in zip(
        columns,
        (
            _cagr_label(metrics, "revenue"),
            "Revenue CAGR (4Y)",
            _cagr_label(metrics, "net_profit"),
            "Net profit CAGR (4Y)",
        ),
        (
            "revenue_cagr",
            "revenue_cagr_4y",
            "net_profit_cagr",
            "net_profit_cagr_4y",
        ),
    ):
        value = (
            _cagr_value(metrics, "revenue")
            if key == "revenue_cagr"
            else _cagr_value(metrics, "net_profit")
            if key == "net_profit_cagr"
            else metrics.get(key)
        )
        column.metric(label, f"{value:.1%}" if value is not None else "N/A")
    next_columns = st.columns(5)
    for column, label, key, format_string in (
        (next_columns[0], "Expected growth", "expected_growth", ".1%"),
        (next_columns[1], "Latest EPS", "latest_eps", ",.2f"),
        (
            next_columns[2],
            "P/E (spreadsheet price, reported EPS)",
            "reported_pe",
            ".1f",
        ),
        (
            next_columns[3],
            "P/E (spreadsheet price, derived EPS)",
            "derived_eps_pe",
            ".1f",
        ),
        (next_columns[4], "EPS payback (years)", "cumulative_eps_payback_years", ".2f"),
    ):
        value = metrics.get(key)
        column.metric(label, format(value, format_string) if value is not None else "N/A")
    st.metric("Educational screen", metrics.get("rating", "Insufficient data"))
    contributors = metrics.get("expected_growth_contributors", [])
    st.caption(
        "Expected Growth contributors: "
        + (
            ", ".join(
                f"{item['metric']} {item['value']:.1%}"
                for item in contributors
            )
            if contributors
            else "none"
        )
    )
    st.caption(
        f"EPS source: {metrics.get('latest_eps_source') or 'unavailable'} · "
        f"Normalized Core P/E: unavailable without sufficient historical "
        "exceptional-item and cyclical-margin information."
    )
    if snapshot["reporting_metadata_status"] == "Unknown":
        st.warning(
            "Reporting basis is unknown. This metadata warning is separate from "
            "the financial anomaly status."
        )
    elif snapshot["reporting_metadata_status"] == "Needs review":
        st.warning("Reporting basis requires manual review.")
    else:
        st.success(
            f"Reporting basis was manually confirmed as "
            f"{snapshot['reporting_basis'].lower()}."
        )
    st.subheader("Cumulative EPS payback sensitivity")
    st.dataframe(
        pd.DataFrame(metrics.get("payback_sensitivity", [])),
        hide_index=True,
        width="stretch",
    )
    findings = snapshot["findings"]
    if findings:
        st.subheader("Metric-level data checks")
        st.dataframe(
            pd.DataFrame(findings).rename(
                columns={
                    "metric": "Metric",
                    "period": "Financial period",
                    "severity": "Severity",
                    "code": "Rule",
                    "message": "Explanation",
                }
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.success("No significant financial anomaly was detected.")
    records = _snapshot_observation_frame(snapshot["snapshot_id"])
    st.subheader("Saved normalized financial records")
    st.dataframe(records, hide_index=True, width="stretch")

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        export_metrics = {
            "Current Price (INR; from Screener spreadsheet)": spreadsheet_price,
            "Spreadsheet import time": snapshot["imported_at"],
            "P/E (spreadsheet price, reported EPS)": metrics.get("reported_pe"),
            "P/E (spreadsheet price, derived EPS)": metrics.get(
                "derived_eps_pe"
            ),
            _cagr_label(metrics, "revenue"): _cagr_value(metrics, "revenue"),
            "Revenue CAGR period (years)": _cagr_period(metrics, "revenue"),
            "Revenue CAGR (4Y)": metrics.get("revenue_cagr_4y"),
            _cagr_label(metrics, "net_profit"): _cagr_value(metrics, "net_profit"),
            "Net profit CAGR period (years)": _cagr_period(metrics, "net_profit"),
            "Net profit CAGR (4Y)": metrics.get("net_profit_cagr_4y"),
            "Expected Growth": metrics.get("expected_growth"),
            "Expected Growth Contributors": "; ".join(
                f"{item['metric']}: {item['value']:.2%}"
                for item in metrics.get("expected_growth_contributors", [])
            ),
            **{
                key.replace("_", " ").title(): value
                for key, value in metrics.items()
                if key
                not in {
                    "revenue_cagr",
                    "revenue_cagr_period",
                    "revenue_cagr_4y",
                    "net_profit_cagr",
                    "net_profit_cagr_period",
                    "net_profit_cagr_4y",
                    "expected_growth",
                    "expected_growth_contributors",
                    "current_price",
                    "reported_pe",
                    "derived_eps_pe",
                    "payback_sensitivity",
                    "payback_sensitivity_schedule",
                }
            },
        }
        pd.DataFrame([export_metrics]).to_excel(
            writer, sheet_name="Analysis", index=False
        )
        pd.DataFrame(metrics.get("payback_sensitivity", [])).to_excel(
            writer, sheet_name="Payback Sensitivity", index=False
        )
        pd.DataFrame(metrics.get("payback_sensitivity_schedule", [])).to_excel(
            writer, sheet_name="Payback Schedule", index=False
        )
        records.to_excel(writer, sheet_name="Financials", index=False)
        pd.DataFrame(findings).to_excel(writer, sheet_name="Anomalies", index=False)
    st.download_button(
        "Export saved analysis to Excel",
        data=output.getvalue(),
        file_name=f"{snapshot['ticker']}_{snapshot['snapshot_id'][:8]}_analysis.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def render_screener_page(page: str) -> None:
    config = _current_config()
    if page == "Screener imports":
        _render_import(config)
        snapshots = fetch_screener_snapshots()
        if snapshots:
            _render_imported_overview(snapshots)
            _render_comparison(snapshots)
        return
    snapshots = fetch_screener_snapshots()
    if not snapshots:
        st.info("Import a Screener export to create a saved analysis snapshot.")
        return
    selected = next(
        (item for item in snapshots if page == f"Imported: {item['ticker']}"),
        None,
    )
    if selected:
        _render_snapshot_detail(selected)
