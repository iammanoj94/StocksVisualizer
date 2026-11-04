from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from stockvisualizer.price_data import assess_price, exchange_from_symbol
from stockvisualizer.stock_catalog import build_stock_rows


def test_price_status_requires_source_asof_not_import_timestamp():
    now = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)

    status = assess_price(
        ticker="HDFCBANK.NS",
        value=1000,
        source="Screener Data Sheet",
        as_of=None,
        recorded_at=now,
        now=now,
    )

    assert status.value == 1000
    assert status.freshness == "Stale"
    assert status.as_of is None
    assert status.recorded_at == now
    assert status.exchange.startswith("NSE")


@pytest.mark.parametrize(
    ("age", "expected"),
    (
        (timedelta(minutes=5), "Fresh"),
        (timedelta(minutes=30), "Delayed"),
        (timedelta(days=2), "Stale"),
    ),
)
def test_price_freshness_uses_asof_timestamp(age, expected):
    now = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
    status = assess_price(
        ticker="CIPLA.BO",
        value=100,
        source="Test provider",
        as_of=now - age,
        recorded_at=now,
        now=now,
    )

    assert status.freshness == expected


@pytest.mark.parametrize("value", (None, 0, -1, float("nan"), float("inf")))
def test_missing_or_invalid_price_is_unavailable(value):
    status = assess_price(
        ticker="MARUTI.NS",
        value=value,
        source="Screener",
        as_of=datetime.now(timezone.utc),
        recorded_at=None,
    )

    assert status.value is None
    assert status.freshness == "Unavailable"


def test_exchange_mapping_is_inferred_only_from_recognized_ticker_suffix():
    assert exchange_from_symbol("HDFCBANK.NS").startswith("NSE")
    assert exchange_from_symbol("CIPLA.BO").startswith("BSE")
    assert exchange_from_symbol("CIPLA") == "Unknown"
    assert "unverified" in exchange_from_symbol("CIPLA.NS")


def test_stock_catalog_does_not_promote_sample_prices_to_market_prices():
    catalog = [
        {
            "ticker": "HDFCBANK.NS",
            "company_name": "HDFC Bank",
            "sector": "Financial Services",
            "sample_price": 1680,
            "sample_market_cap": 1234,
            "data_label": "Illustrative sample data",
            "snapshot": None,
        }
    ]
    financials = pd.DataFrame(
        {
            "fiscal_year": [2022, 2023, 2024],
            "revenue_cr": [100, 110, 121],
            "net_profit_cr": [10, 11, 12.1],
            "eps": [1, 1.1, 1.21],
        }
    )
    rows = build_stock_rows(catalog, lambda _: financials)

    assert rows[0]["price_display"] == "Unavailable"
    assert rows[0]["freshness"] == "Unavailable"
    assert rows[0]["price_as_of"] == "Unknown"
    assert rows[0]["market_cap_display"] == "Unavailable"


def test_imported_price_is_current_spreadsheet_value_with_import_time():
    catalog = [
        {
            "ticker": "CIPLA.NS",
            "company_name": "Cipla",
            "sector": "Unknown",
            "sample_price": None,
            "sample_market_cap": None,
            "data_label": None,
            "snapshot": {
                "current_price": 1234.5,
                "imported_at": "2026-11-03T18:00:00+00:00",
                "financial_status": "Green",
                "metrics": {
                    "expected_growth": 0.12,
                    "cumulative_eps_payback_years": 7.5,
                },
            },
        }
    ]

    row = build_stock_rows(catalog)[0]

    assert row["price_display"] == "INR 1,234.50"
    assert row["price_source"] == "Screener Excel/CSV Data Sheet · Current Price"
    assert row["freshness"] == "Stale"
    assert row["price_as_of"] == "Unknown"
    assert row["last_updated"] == "Screener import: 2026-11-03T18:00:00+00:00"
    assert row["financial_status"] == "Green"
    assert row["market_cap_display"] == "Unavailable"
