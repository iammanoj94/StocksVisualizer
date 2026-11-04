import sqlite3

from stockvisualizer.database import (
    fetch_financials,
    fetch_expected_growth_overrides,
    fetch_screener_observations,
    fetch_screener_snapshots,
    fetch_watchlist_members,
    fetch_watchlist_snapshots,
    fetch_watchlist_column_order,
    fetch_yahoo_market_data,
    add_to_watchlist,
    find_screener_imports_by_hash,
    initialize_database,
    remove_from_watchlist,
    save_watchlist_snapshot,
    save_watchlist_column_order,
    save_expected_growth_override,
    save_yahoo_market_data,
    save_screener_snapshot,
    fetch_watchlist,
)
from stockvisualizer.stock_data import load_stock_detail


def test_database_initialization_is_idempotent(tmp_path):
    db_path = tmp_path / "stocks.sqlite3"
    initialize_database(db_path)
    initialize_database(db_path)

    watchlist = fetch_watchlist(db_path)
    assert watchlist["ticker"].tolist() == [
        "HDFCBANK.NS",
        "MARUTI.NS",
        "CIPLA.NS",
    ]
    assert set(watchlist["data_label"]) == {"Illustrative sample data"}
    assert len(fetch_financials("HDFCBANK.NS", db_path)) == 5
    assert len(fetch_watchlist_members(db_path)) == 3


def test_watchlist_add_remove_duplicate_prevention_and_restart_persistence(tmp_path):
    db_path = tmp_path / "stocks.sqlite3"
    initialize_database(db_path)

    assert add_to_watchlist("TEST.NS", "Test Limited", db_path) is True
    assert add_to_watchlist("test.ns", "Test Limited", db_path) is False
    assert len(fetch_watchlist_members(db_path)) == 4

    initialize_database(db_path)
    assert any(
        item["ticker"] == "TEST.NS"
        for item in fetch_watchlist_members(db_path)
    )
    assert remove_from_watchlist("TEST.NS", db_path) is True
    assert remove_from_watchlist("TEST.NS", db_path) is False
    initialize_database(db_path)
    assert all(
        item["ticker"] != "TEST.NS"
        for item in fetch_watchlist_members(db_path)
    )
    assert len(fetch_watchlist_members(db_path)) == 3


def test_removed_seeded_stock_stays_removed_after_restart(tmp_path):
    db_path = tmp_path / "stocks.sqlite3"
    initialize_database(db_path)

    assert remove_from_watchlist("HDFCBANK.NS", db_path)
    initialize_database(db_path)

    assert {
        item["ticker"] for item in fetch_watchlist_members(db_path)
    } == {"MARUTI.NS", "CIPLA.NS"}


def test_watchlist_snapshot_persists_unique_selected_tickers(tmp_path):
    db_path = tmp_path / "stocks.sqlite3"
    initialize_database(db_path)

    snapshot_id = save_watchlist_snapshot(
        ["TEST.NS", "CIPLA.NS", "TEST.NS"], db_path
    )
    saved = fetch_watchlist_snapshots(db_path)

    assert saved[0]["snapshot_id"] == snapshot_id
    assert saved[0]["tickers"] == ["TEST.NS", "CIPLA.NS"]


def test_watchlist_column_order_persists_across_database_initialization(tmp_path):
    db_path = tmp_path / "stocks.sqlite3"
    initialize_database(db_path)
    order = ["EPS", "Name", "Price", "Source"]

    assert fetch_watchlist_column_order(db_path) is None
    save_watchlist_column_order(order, db_path)
    initialize_database(db_path)

    assert fetch_watchlist_column_order(db_path) == order


def test_watchlist_column_order_rejects_duplicate_columns(tmp_path):
    db_path = tmp_path / "stocks.sqlite3"
    initialize_database(db_path)

    try:
        save_watchlist_column_order(["Name", "Name"], db_path)
    except ValueError as error:
        assert "unique" in str(error)
    else:
        raise AssertionError("Expected duplicate column names to be rejected")


def test_expected_growth_override_persists_and_can_be_cleared(tmp_path):
    db_path = tmp_path / "stocks.sqlite3"
    initialize_database(db_path)

    save_expected_growth_override("test.ns", 0.125, db_path)
    initialize_database(db_path)
    assert fetch_expected_growth_overrides(db_path) == {"TEST.NS": 0.125}

    save_expected_growth_override("TEST.NS", None, db_path)
    assert fetch_expected_growth_overrides(db_path) == {}


def test_expected_growth_override_rejects_invalid_growth(tmp_path):
    db_path = tmp_path / "stocks.sqlite3"
    initialize_database(db_path)

    for invalid in (-1, float("inf"), float("nan")):
        try:
            save_expected_growth_override("TEST.NS", invalid, db_path)
        except ValueError:
            continue
        raise AssertionError(f"Expected invalid growth {invalid!r} to be rejected")


def test_reimport_clears_growth_override_without_changing_snapshot_history(tmp_path):
    db_path = tmp_path / "stocks.sqlite3"
    initialize_database(db_path)
    analysis = {
        "metrics": {},
        "findings": [],
        "financial_status": "Green",
        "reporting_metadata_status": "Unknown",
        "anomaly_config": {"lookback": 5},
    }

    save_expected_growth_override("TEST.NS", 0.2, db_path)
    first_snapshot = save_screener_snapshot(
        ticker="TEST.NS",
        company_name="Test Limited",
        filename="first.xlsx",
        content_sha256="first-hash",
        observations=[],
        analysis=analysis,
        current_price=100,
        db_path=db_path,
    )
    save_expected_growth_override("TEST.NS", 0.3, db_path)
    second_snapshot = save_screener_snapshot(
        ticker="TEST.NS",
        company_name="Test Limited",
        filename="second.xlsx",
        content_sha256="second-hash",
        observations=[],
        analysis=analysis,
        current_price=101,
        db_path=db_path,
    )

    assert first_snapshot != second_snapshot
    assert fetch_expected_growth_overrides(db_path) == {}
    assert len(fetch_screener_snapshots("TEST.NS", db_path)) == 2


def test_yahoo_market_data_persists_until_screener_reimport(tmp_path):
    db_path = tmp_path / "stocks.sqlite3"
    initialize_database(db_path)
    quote = {
        "yahoo_symbol": "TEST.NS",
        "price_inr": 123.4,
        "price_type": "regularMarketPrice",
        "market_cap_inr": 1_000_000_000,
        "pe": 12.3,
        "eps_inr": 10.0,
        "debt_to_equity": 2.5,
        "currency": "INR",
        "quote_timestamp": "2026-01-01T10:00:00+00:00",
        "fetched_at": "2026-01-01T10:01:00+00:00",
    }
    save_yahoo_market_data("test.ns", quote, db_path)
    initialize_database(db_path)

    saved = fetch_yahoo_market_data(db_path)["TEST.NS"]
    assert saved["price_inr"] == 123.4
    assert saved["price_type"] == "regularMarketPrice"
    assert saved["debt_to_equity"] == 2.5
    assert saved["fetched_at"] == quote["fetched_at"]

    analysis = {
        "metrics": {},
        "findings": [],
        "financial_status": "Green",
        "reporting_metadata_status": "Unknown",
        "anomaly_config": {"lookback": 5},
    }
    save_screener_snapshot(
        ticker="TEST.NS",
        company_name="Test Limited",
        filename="test.xlsx",
        content_sha256="yahoo-reset-hash",
        observations=[],
        analysis=analysis,
        current_price=100,
        db_path=db_path,
    )
    assert "TEST.NS" not in fetch_yahoo_market_data(db_path)


def test_initialize_database_migrates_yahoo_debt_to_equity_column(tmp_path):
    db_path = tmp_path / "stocks.sqlite3"
    initialize_database(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("ALTER TABLE yahoo_market_data DROP COLUMN debt_to_equity")

    initialize_database(db_path)

    quote = {
        "yahoo_symbol": "TEST.NS",
        "price_inr": 100,
        "market_cap_inr": 1_000_000_000,
        "pe": 10,
        "eps_inr": 10,
        "debt_to_equity": 0.75,
        "currency": "INR",
        "fetched_at": "2026-01-01T10:00:00+00:00",
    }
    save_yahoo_market_data("TEST.NS", quote, db_path)

    assert fetch_yahoo_market_data(db_path)["TEST.NS"]["debt_to_equity"] == 0.75


def test_watchlist_actions_do_not_modify_financials_or_saved_analysis(tmp_path):
    db_path = tmp_path / "stocks.sqlite3"
    initialize_database(db_path)
    financials_before = fetch_financials("HDFCBANK.NS", db_path)
    analysis = {
        "metrics": {"current_price": 123.0},
        "findings": [],
        "financial_status": "Green",
        "reporting_metadata_status": "Unknown",
        "anomaly_config": {"lookback": 5},
    }
    snapshot_id = save_screener_snapshot(
        ticker="HDFCBANK.NS",
        company_name="HDFC Bank",
        filename="hdfc.xlsx",
        content_sha256="immutable-price-hash",
        observations=[
            {
                "statement": "annual",
                "period": "2025-03-31",
                "metric": "revenue",
                "value": 100,
                "unit": "INR Crore",
            }
        ],
        analysis=analysis,
        current_price=123,
        db_path=db_path,
    )

    remove_from_watchlist("HDFCBANK.NS", db_path)
    add_to_watchlist("TEST.NS", "Test Limited", db_path)

    financials_after = fetch_financials("HDFCBANK.NS", db_path)
    saved_snapshot = fetch_screener_snapshots("HDFCBANK.NS", db_path)[0]
    saved_observations = fetch_screener_observations(snapshot_id, db_path)
    assert financials_after.equals(financials_before)
    assert saved_snapshot["current_price"] == 123
    assert saved_snapshot["metrics"]["current_price"] == 123
    assert saved_observations[0]["value"] == 100


def test_database_adds_reporting_basis_to_legacy_snapshots_without_data_loss(tmp_path):
    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE screener_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                company_name TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_filename TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                unit_policy TEXT NOT NULL,
                reporting_metadata_status TEXT NOT NULL,
                financial_status TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                findings_json TEXT NOT NULL,
                analysis_config_json TEXT NOT NULL,
                current_price REAL,
                UNIQUE(snapshot_id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO screener_snapshots (
                snapshot_id, ticker, company_name, source_name, source_filename,
                content_sha256, imported_at, parser_version, unit_policy,
                reporting_metadata_status, financial_status, metrics_json,
                findings_json, analysis_config_json, current_price
            ) VALUES (
                'legacy-id', 'TEST.NS', 'Test Ltd', 'Screener export',
                'test.xlsx', 'legacy-hash', '2026-01-01T00:00:00+00:00',
                '1.0', 'INR Crore confirmed', 'Unknown', 'Green',
                '{}', '[]', '{}', 100
            )
            """
        )

    initialize_database(db_path)

    saved = fetch_screener_snapshots("TEST.NS", db_path)
    assert len(saved) == 1
    assert saved[0]["snapshot_id"] == "legacy-id"
    assert saved[0]["reporting_basis"] == "Unknown"


def test_stock_detail_loads_company_and_history(tmp_path):
    db_path = tmp_path / "stocks.sqlite3"
    company, financials = load_stock_detail("CIPLA.NS", db_path)

    assert company["name"] == "Cipla"
    assert len(financials) == 5


def test_stock_detail_rejects_unknown_ticker(tmp_path):
    try:
        load_stock_detail("UNKNOWN.NS", tmp_path / "stocks.sqlite3")
    except ValueError as error:
        assert "not present" in str(error)
    else:
        raise AssertionError("Expected unknown ticker to raise ValueError")


def test_screener_import_snapshot_retains_data_and_duplicate_provenance(tmp_path):
    db_path = tmp_path / "stocks.sqlite3"
    initialize_database(db_path)
    analysis = {
        "metrics": {"revenue_cagr_4y": 0.1},
        "findings": [],
        "financial_status": "Green",
        "reporting_metadata_status": "Unknown",
        "anomaly_config": {"lookback": 5},
    }
    observations = [
        {
            "statement": "annual",
            "period": "2025-03-31",
            "metric": "revenue",
            "value": 123.0,
            "unit": "INR Crore",
            "value_source": "screener_export",
            "raw_value": "123",
        },
        {
            "statement": "annual",
            "period": "2025-03-31",
            "metric": "net_profit",
            "value": None,
            "unit": "INR Crore",
            "value_source": "screener_export",
        },
    ]
    snapshot_id = save_screener_snapshot(
        ticker="TEST.NS",
        company_name="Test Limited",
        filename="test.xlsx",
        content_sha256="hash-value",
        observations=observations,
        analysis=analysis,
        current_price=100,
        db_path=db_path,
    )

    saved = fetch_screener_snapshots("TEST.NS", db_path)
    stored = fetch_screener_observations(snapshot_id, db_path)
    duplicates = find_screener_imports_by_hash("hash-value", db_path)

    assert len(saved) == 1
    assert saved[0]["financial_status"] == "Green"
    assert len(stored) == 2
    assert stored[1]["value"] is None or stored[0]["value"] is None
    assert duplicates[0]["snapshot_id"] == snapshot_id
