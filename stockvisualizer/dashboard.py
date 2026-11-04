from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from stockvisualizer.database import (
    add_to_watchlist,
    fetch_financials,
    fetch_watchlist_members,
    remove_from_watchlist,
)
from stockvisualizer.calculations.cumulative_eps_payback import (
    calculate_cumulative_eps_payback,
)
from stockvisualizer.calculations.expected_growth import calculate_expected_growth
from stockvisualizer.calculations.net_profit_cagr import (
    calculate_net_profit_cagr_max_available,
    calculate_net_profit_cagr_4y,
)
from stockvisualizer.calculations.payback_sensitivity import (
    calculate_payback_sensitivity,
)
from stockvisualizer.calculations.reported_pe import calculate_reported_pe
from stockvisualizer.calculations.revenue_cagr import (
    calculate_revenue_cagr_max_available,
    calculate_revenue_cagr_4y,
)
from stockvisualizer.calculations.stock_rating import calculate_stock_rating
from stockvisualizer.stock_data import (
    load_stock_detail,
    load_watchlist,
)
from stockvisualizer.screener_browser import parse_symbol_queue
from stockvisualizer.screener_pages import render_screener_page
from stockvisualizer.stock_catalog import build_stock_rows
from stockvisualizer.watchlist_ui import (
    render_bulk_actions,
    render_stock_selection,
    render_watchlist_page,
    screener_symbols_for_tickers,
)


def _format_percent(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "N/A"


def _format_multiple(value: float | None) -> str:
    return f"{value:.1f}x" if value is not None else "N/A"


def _calculate_metrics(company: dict, financials):
    revenues = financials["revenue_cr"].tolist()
    profits = financials["net_profit_cr"].tolist()
    eps_values = financials["eps"].tolist()
    fiscal_years = financials["fiscal_year"].tolist()
    revenue_growth, revenue_period = calculate_revenue_cagr_max_available(
        revenues, fiscal_years
    )
    revenue_growth_4y = calculate_revenue_cagr_4y(revenues, fiscal_years)
    profit_growth, profit_period = calculate_net_profit_cagr_max_available(
        profits, fiscal_years
    )
    profit_growth_4y = calculate_net_profit_cagr_4y(profits, fiscal_years)
    expected_components = []
    if revenue_growth is not None:
        expected_components.append(
            (f"Revenue CAGR ({revenue_period}Y)", revenue_growth, revenue_period)
        )
    if revenue_growth_4y is not None and revenue_period != 4:
        expected_components.append(("Revenue CAGR (4Y)", revenue_growth_4y, 4))
    if profit_growth is not None:
        expected_components.append(
            (f"Net profit CAGR ({profit_period}Y)", profit_growth, profit_period)
        )
    if profit_growth_4y is not None and profit_period != 4:
        expected_components.append(("Net profit CAGR (4Y)", profit_growth_4y, 4))
    expected_growth = calculate_expected_growth(
        *(component[1] for component in expected_components)
    )
    reported_pe = calculate_reported_pe(float(company["price_inr"]), eps_values[-1])
    normalized_core_pe = None
    payback = (
        calculate_cumulative_eps_payback(
            float(company["price_inr"]), float(eps_values[-1]), expected_growth
        )
        if expected_growth is not None
        else None
    )
    rating = calculate_stock_rating(normalized_core_pe, expected_growth, payback)
    return {
        "revenue_growth": revenue_growth,
        "revenue_period": revenue_period,
        "revenue_growth_4y": revenue_growth_4y,
        "profit_growth": profit_growth,
        "profit_period": profit_period,
        "profit_growth_4y": profit_growth_4y,
        "expected_growth": expected_growth,
        "expected_growth_contributors": expected_components,
        "reported_pe": reported_pe,
        "normalized_core_pe": normalized_core_pe,
        "payback": payback,
        "rating": rating,
    }


def _apply_style() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: #f5f7fb; color: #17243b; }
        [data-testid="stSidebar"] { background: #111d33; }
        [data-testid="stSidebar"] * { color: #e7edf7; }
        .block-container { max-width: 1900px; padding: 2rem 0.5rem 3rem; }
        div[data-testid="stMetric"] {
            background: #ffffff; border: 1px solid #e6eaf1;
            border-radius: 12px; padding: 16px 18px;
        }
        [data-testid="stDataEditor"] {
            border: 1px solid #e5eaf2; border-radius: 12px;
            box-shadow: 0 2px 10px rgba(27, 46, 79, 0.05);
        }
        div[data-testid="stButton"] > button[kind="primary"] {
            background: #2457c5; border-color: #2457c5; border-radius: 8px;
        }
        h1 { letter-spacing: -0.035em; }
        .sample-banner {
            background: #fff6df; border: 1px solid #f2d89a; color: #75530d;
            border-radius: 10px; padding: 12px 16px; margin: 8px 0 20px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _format_watchlist(watchlist):
    rows = []
    for _, row in watchlist.iterrows():
        metrics = _calculate_metrics(
            row.to_dict(),
            load_stock_detail(row["ticker"])[1],
        )
        rows.append(
            {
                "Company": row["name"],
                "Ticker": row["ticker"],
                "Sector": row["sector"],
                "Sample price (INR)": row["price_inr"],
                "Day change (sample)": row["day_change_pct"],
                "Market cap (sample, Cr)": row["market_cap_cr"],
                f"Revenue CAGR ({metrics['revenue_period']}Y)"
                if metrics["revenue_period"] is not None
                else "Revenue CAGR (max 9Y)": _format_percent(metrics["revenue_growth"]),
                "Revenue CAGR 4Y": _format_percent(metrics["revenue_growth_4y"]),
                f"Net profit CAGR ({metrics['profit_period']}Y)"
                if metrics["profit_period"] is not None
                else "Net profit CAGR (max 9Y)": _format_percent(metrics["profit_growth"]),
                "Net profit CAGR 4Y": _format_percent(metrics["profit_growth_4y"]),
                "Expected growth": _format_percent(metrics["expected_growth"]),
                "Reported P/E": _format_multiple(metrics["reported_pe"]),
                "Normalized Core P/E": _format_multiple(metrics["normalized_core_pe"]),
                "EPS payback (years)": (
                    f"{metrics['payback']:.1f}"
                    if metrics["payback"] is not None
                    else "N/A"
                ),
                "Screen": metrics["rating"],
            }
        )
    return rows


def _show_overview(watchlist) -> None:
    st.title("Indian Equities | Stock List")
    st.caption("A local research workspace for a focused Indian equities watchlist.")
    st.markdown(
        '<div class="sample-banner"><strong>Illustrative sample data</strong> '
        "— prices and financials are synthetic. Refresh reloads the local sample "
        "dataset and does not fetch live market data.</div>",
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns(3)
    col1.metric("Companies tracked", len(watchlist))
    col2.metric("Data source", "Local sample")
    col3.metric("Currency", "INR")
    rows = build_stock_rows()
    selected = render_stock_selection(rows, key="stock_list")
    render_bulk_actions(selected, "stock_list")
    st.caption(
        "All numbers and derived screens are synthetic examples for education; "
        "they are not investment recommendations."
    )


def _show_watchlist() -> None:
    st.title("My Watchlist")
    members = fetch_watchlist_members()
    if not members:
        st.info("Your watchlist is empty. Add a stock to get started.")
        if st.button("Add stock", type="primary"):
            st.session_state["navigate_to_add_stocks"] = True
            st.rerun()
        return
    member_tickers = {item["ticker"] for item in members}
    rows = [
        row for row in build_stock_rows() if row["ticker"] in member_tickers
    ]
    render_watchlist_page(rows)


def _show_add_stocks() -> None:
    st.title("Add stocks")
    st.caption(
        "Enter NSE symbols separated by commas or new lines. Sign in to Screener "
        "manually; credentials are not requested or stored."
    )
    with st.form("add_stocks_form"):
        symbols_text = st.text_area(
            "NSE symbol(s)",
            placeholder="HDFCBANK\nM&M\nBAJAJ-AUTO",
            height=110,
        )
        submit = st.form_submit_button(
            "Continue to Screener sign-in",
            type="primary",
        )
    if not submit:
        return
    try:
        queue = parse_symbol_queue(
            symbols_text.replace(",", "\n").replace(";", "\n")
        )
    except ValueError as error:
        st.error(str(error))
        return

    try:
        normalized_queue = parse_symbol_queue(
            "\n".join(screener_symbols_for_tickers(list(queue.symbols)))
        )
    except ValueError as error:
        st.error(str(error))
        return
    st.session_state["pending_bulk_download_symbols"] = list(
        normalized_queue.symbols
    )
    st.session_state["screener_browser_action"] = "add"
    st.session_state["navigate_to_screener_imports"] = True
    st.rerun()


def _show_stock_detail(ticker: str) -> None:
    company, financials = load_stock_detail(ticker)
    metrics = _calculate_metrics(company, financials)
    st.title(company["name"])
    st.caption(f"{ticker} · {company['sector']} · Illustrative sample data")

    members = {item["ticker"] for item in fetch_watchlist_members()}
    if ticker in members:
        if st.button("Remove from Watchlist", key=f"detail_remove_{ticker}"):
            remove_from_watchlist(ticker)
            st.rerun()
    elif st.button("Add to Watchlist", key=f"detail_add_{ticker}"):
        add_to_watchlist(ticker, company["name"])
        st.rerun()

    metric_columns = st.columns(4)
    metric_columns[0].metric("Current market price", "Unavailable")
    metric_columns[1].metric(
        "Illustrative sample price", f"₹{company['price_inr']:,.2f}"
    )
    metric_columns[2].metric(
        "Sample P/E (synthetic inputs)", _format_multiple(metrics["reported_pe"])
    )
    metric_columns[3].metric(
        "Normalized Core P/E", _format_multiple(metrics["normalized_core_pe"])
    )
    st.caption(
        "Price source: illustrative sample database · Exchange: "
        f"{'NSE inferred from .NS ticker; unverified' if ticker.endswith('.NS') else 'Unknown'} "
        "· Price type: synthetic, not LTP/close · As of: unknown · "
        "Freshness: Unavailable. This is not a market quote."
    )

    growth_columns = st.columns(4)
    growth_columns[0].metric(
        (
            f"Revenue CAGR ({metrics['revenue_period']}Y)"
            if metrics["revenue_period"] is not None
            else "Revenue CAGR (max 9Y)"
        ),
        _format_percent(metrics["revenue_growth"]),
    )
    growth_columns[1].metric(
        "Revenue CAGR 4Y", _format_percent(metrics["revenue_growth_4y"])
    )
    growth_columns[2].metric(
        (
            f"Net profit CAGR ({metrics['profit_period']}Y)"
            if metrics["profit_period"] is not None
            else "Net profit CAGR (max 9Y)"
        ),
        _format_percent(metrics["profit_growth"]),
    )
    growth_columns[3].metric(
        "Net profit CAGR 4Y", _format_percent(metrics["profit_growth_4y"])
    )
    secondary_columns = st.columns(3)
    secondary_columns[0].metric(
        "Expected growth", _format_percent(metrics["expected_growth"])
    )
    secondary_columns[1].metric(
        "Cumulative EPS payback",
        (
            f"{metrics['payback']:.1f} years"
            if metrics["payback"] is not None
            else "N/A"
        ),
    )
    secondary_columns[2].metric("Educational screen", metrics["rating"])
    contributors = metrics["expected_growth_contributors"]
    st.caption(
        "Expected Growth averages: "
        + (
            ", ".join(
                f"{label} {_format_percent(value)}"
                for label, value, _ in contributors
            )
            if contributors
            else "no valid CAGR metrics"
        )
    )

    st.caption(
        "Sample P/E and payback use synthetic sample price/EPS values and are "
        "educational only. Normalized Core P/E is "
        "unavailable because the sample history does not identify exceptional "
        "income/expenses or normalize cyclical margins; no normalized earnings "
        "are inferred."
    )

    chart = go.Figure()
    years = financials["fiscal_year"].astype(str)
    chart.add_trace(
        go.Bar(
            x=years,
            y=financials["revenue_cr"],
            name="Revenue (sample, ₹ Cr)",
            marker_color="#5b8def",
        )
    )
    chart.add_trace(
        go.Bar(
            x=years,
            y=financials["net_profit_cr"],
            name="Net profit (sample, ₹ Cr)",
            marker_color="#37b897",
        )
    )
    chart.add_trace(
        go.Scatter(
            x=years,
            y=np.array(financials["eps"], dtype=float),
            name="EPS (sample, ₹)",
            mode="lines+markers",
            yaxis="y2",
            line={"color": "#f0a44b", "width": 3},
        )
    )
    chart.update_layout(
        title="Illustrative annual financial history",
        barmode="group",
        height=430,
        margin={"l": 10, "r": 10, "t": 55, "b": 10},
        paper_bgcolor="white",
        plot_bgcolor="white",
        legend={"orientation": "h", "y": -0.2},
        yaxis={"title": "₹ Crore", "gridcolor": "#edf0f5"},
        yaxis2={
            "title": "EPS (₹)",
            "overlaying": "y",
            "side": "right",
            "showgrid": False,
        },
    )
    st.plotly_chart(chart, width="stretch")
    with st.expander("Annual sample financials"):
        st.dataframe(
            financials.rename(
                columns={
                    "fiscal_year": "Fiscal year",
                    "revenue_cr": "Revenue (sample, ₹ Cr)",
                    "net_profit_cr": "Net profit (sample, ₹ Cr)",
                    "eps": "EPS (sample, ₹)",
                }
            ),
            hide_index=True,
            width="stretch",
        )

    st.subheader("Cumulative EPS payback sensitivity")
    st.caption(
        "Year 1 starts with the latest reported EPS. Each scenario grows EPS at "
        "the stated rate; fractional payback interpolates within the final year."
    )
    sensitivity = calculate_payback_sensitivity(
        float(company["price_inr"]), float(financials["eps"].iloc[-1])
    )
    summary_rows = []
    schedule_rows = []
    for growth, analysis in sensitivity.items():
        summary_rows.append(
            {
                "EPS growth assumption": _format_percent(growth),
                "First full year reaching price": (
                    analysis.first_full_year
                    if analysis is not None and analysis.first_full_year is not None
                    else "Not reached"
                ),
                "Estimated payback (years)": (
                    round(analysis.estimated_payback_years, 2)
                    if analysis is not None
                    and analysis.estimated_payback_years is not None
                    else "Not reached"
                ),
            }
        )
        if analysis is not None:
            schedule_rows.extend(
                {
                    "EPS growth assumption": _format_percent(growth),
                    "Year": year.year,
                    "Annual EPS (₹)": year.annual_eps,
                    "Cumulative EPS (₹)": year.cumulative_eps,
                    "Reached sample price": year.cumulative_eps >= company["price_inr"],
                }
                for year in analysis.schedule
            )
    st.dataframe(summary_rows, hide_index=True, width="stretch")
    with st.expander("Annual EPS and cumulative EPS by scenario"):
        st.dataframe(schedule_rows, hide_index=True, width="stretch")

    st.info(
        "Metrics are calculated from synthetic sample data. The screen is "
        "educational, is not personalized financial advice, and must not be "
        "treated as a buy or sell recommendation."
    )


def main() -> None:
    st.set_page_config(
        page_title="StockVisualizer | Indian Equities",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _apply_style()
    try:
        load_watchlist()
    except Exception as error:
        st.error(f"Could not initialize the local stock database: {error}")
        st.stop()

    with st.sidebar:
        st.title("StockVisualizer")
        st.caption("Indian equity research")
        pages = ["Watchlist", "Add stocks", "Screener imports"]
        if st.session_state.pop("navigate_to_add_stocks", False):
            st.session_state["navigation_page"] = "Add stocks"
        if st.session_state.pop("navigate_to_screener_imports", False):
            st.session_state["navigation_page"] = "Screener imports"
        st.session_state.setdefault("navigation_page", "Watchlist")
        if st.session_state.get("navigation_page") not in pages:
            st.session_state["navigation_page"] = "Watchlist"
        selected_page = st.radio(
            "Navigate",
            pages,
            key="navigation_page",
            label_visibility="collapsed",
        )
        st.caption("Manual Screener spreadsheet imports")

    if selected_page == "Watchlist":
        _show_watchlist()
    elif selected_page == "Add stocks":
        _show_add_stocks()
    elif selected_page == "Screener imports" or selected_page.startswith("Imported: "):
        render_screener_page(selected_page)
    else:
        try:
            _show_stock_detail(selected_page)
        except (ValueError, KeyError) as error:
            st.error(f"Unable to load {selected_page}: {error}")
