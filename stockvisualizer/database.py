from __future__ import annotations

import os
import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "stockvisualizer.db"

SAMPLE_COMPANIES = (
    ("HDFCBANK.NS", "HDFC Bank", "Financial Services"),
    ("MARUTI.NS", "Maruti Suzuki India", "Automobile"),
    ("CIPLA.NS", "Cipla", "Pharmaceuticals"),
)

SAMPLE_FINANCIALS = {
    "HDFCBANK.NS": (
        (2021, 154000.0, 31100.0, 56.0),
        (2022, 182000.0, 36900.0, 66.0),
        (2023, 224000.0, 45900.0, 82.0),
        (2024, 278000.0, 60800.0, 108.0),
        (2025, 328000.0, 73500.0, 130.0),
    ),
    "MARUTI.NS": (
        (2021, 66500.0, 4420.0, 146.0),
        (2022, 88000.0, 3770.0, 125.0),
        (2023, 118500.0, 8200.0, 272.0),
        (2024, 140000.0, 13200.0, 438.0),
        (2025, 155000.0, 14500.0, 482.0),
    ),
    "CIPLA.NS": (
        (2021, 19400.0, 2400.0, 29.0),
        (2022, 21800.0, 2600.0, 32.0),
        (2023, 22500.0, 2800.0, 35.0),
        (2024, 25400.0, 4100.0, 51.0),
        (2025, 27800.0, 4700.0, 58.0),
    ),
}

SAMPLE_QUOTES = (
    ("HDFCBANK.NS", 1680.0, 0.62, 1280000.0),
    ("MARUTI.NS", 12450.0, -0.35, 392000.0),
    ("CIPLA.NS", 1510.0, 0.88, 122000.0),
)


def get_db_path() -> Path:
    """Resolve the database location, allowing an optional local override."""
    override = os.environ.get("STOCKVISUALIZER_DB")
    return Path(override).expanduser() if override else DEFAULT_DB_PATH


@contextmanager
def get_connection(
    db_path: str | Path | None = None,
) -> Iterator[sqlite3.Connection]:
    """Yield a row-aware SQLite connection and always close it."""
    path = Path(db_path) if db_path else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(db_path: str | Path | None = None) -> None:
    """Create the schema and idempotently seed the illustrative sample data."""
    with get_connection(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS companies (
                ticker TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                sector TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS annual_financials (
                ticker TEXT NOT NULL REFERENCES companies(ticker),
                fiscal_year INTEGER NOT NULL,
                revenue_cr REAL NOT NULL,
                net_profit_cr REAL NOT NULL,
                eps REAL NOT NULL,
                PRIMARY KEY (ticker, fiscal_year)
            );
            CREATE TABLE IF NOT EXISTS market_snapshots (
                ticker TEXT PRIMARY KEY REFERENCES companies(ticker),
                price_inr REAL NOT NULL,
                day_change_pct REAL NOT NULL,
                market_cap_cr REAL NOT NULL,
                data_label TEXT NOT NULL DEFAULT 'Illustrative sample data'
            );
            CREATE TABLE IF NOT EXISTS screener_company_mappings (
                ticker TEXT PRIMARY KEY,
                company_name TEXT NOT NULL,
                confirmed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS watchlist_members (
                ticker TEXT PRIMARY KEY,
                company_name TEXT NOT NULL,
                added_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS watchlist_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                tickers_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS watchlist_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS expected_growth_overrides (
                ticker TEXT PRIMARY KEY,
                growth_rate REAL NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS yahoo_market_data (
                ticker TEXT PRIMARY KEY,
                yahoo_symbol TEXT NOT NULL,
                price_inr REAL,
                price_type TEXT,
                market_cap_inr REAL,
                pe REAL,
                eps_inr REAL,
                debt_to_equity REAL,
                currency TEXT,
                quote_timestamp TEXT,
                fetched_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS screener_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                company_name TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_filename TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                unit_policy TEXT NOT NULL,
                reporting_basis TEXT NOT NULL DEFAULT 'Unknown',
                reporting_metadata_status TEXT NOT NULL,
                financial_status TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                findings_json TEXT NOT NULL,
                analysis_config_json TEXT NOT NULL,
                current_price REAL,
                UNIQUE(snapshot_id)
            );
            CREATE INDEX IF NOT EXISTS idx_screener_snapshots_ticker_time
                ON screener_snapshots(ticker, imported_at);
            CREATE INDEX IF NOT EXISTS idx_screener_snapshots_hash
                ON screener_snapshots(content_sha256);
            CREATE TABLE IF NOT EXISTS screener_observations (
                observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id TEXT NOT NULL
                    REFERENCES screener_snapshots(snapshot_id),
                statement TEXT NOT NULL,
                period TEXT NOT NULL,
                metric TEXT NOT NULL,
                value REAL,
                unit TEXT NOT NULL,
                value_source TEXT NOT NULL,
                raw_value TEXT,
                invalid_value INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_screener_observations_snapshot
                ON screener_observations(snapshot_id, period, statement, metric);
            """
        )
        snapshot_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(screener_snapshots)")
        }
        if "reporting_basis" not in snapshot_columns:
            connection.execute(
                """
                ALTER TABLE screener_snapshots
                ADD COLUMN reporting_basis TEXT NOT NULL DEFAULT 'Unknown'
                """
            )
        yahoo_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(yahoo_market_data)")
        }
        if "price_type" not in yahoo_columns:
            connection.execute(
                "ALTER TABLE yahoo_market_data ADD COLUMN price_type TEXT"
            )
        if "debt_to_equity" not in yahoo_columns:
            connection.execute(
                "ALTER TABLE yahoo_market_data ADD COLUMN debt_to_equity REAL"
            )
        connection.executemany(
            "INSERT OR IGNORE INTO companies (ticker, name, sector) VALUES (?, ?, ?)",
            SAMPLE_COMPANIES,
        )
        seeded = connection.execute(
            "SELECT value FROM watchlist_metadata WHERE key = 'sample_seeded'"
        ).fetchone()
        if seeded is None:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            connection.executemany(
                """
                INSERT OR IGNORE INTO watchlist_members
                    (ticker, company_name, added_at)
                VALUES (?, ?, ?)
                """,
                ((ticker, name, now) for ticker, name, _ in SAMPLE_COMPANIES),
            )
            connection.execute(
                """
                INSERT INTO watchlist_metadata (key, value)
                VALUES ('sample_seeded', '1')
                """
            )
        connection.executemany(
            """
            INSERT OR IGNORE INTO annual_financials
                (ticker, fiscal_year, revenue_cr, net_profit_cr, eps)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                (ticker, year, revenue, profit, eps)
                for ticker, records in SAMPLE_FINANCIALS.items()
                for year, revenue, profit, eps in records
            ),
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO market_snapshots
                (ticker, price_inr, day_change_pct, market_cap_cr, data_label)
            VALUES (?, ?, ?, ?, 'Illustrative sample data')
            """,
            SAMPLE_QUOTES,
        )


def fetch_watchlist(db_path: str | Path | None = None) -> pd.DataFrame:
    """Load watchlist metadata and the latest stored illustrative quote."""
    with get_connection(db_path) as connection:
        return pd.read_sql_query(
            """
            SELECT c.ticker, c.name, c.sector, m.price_inr, m.day_change_pct,
                   m.market_cap_cr, m.data_label
            FROM companies AS c
            JOIN market_snapshots AS m ON m.ticker = c.ticker
            ORDER BY CASE c.ticker
                WHEN 'HDFCBANK.NS' THEN 1
                WHEN 'MARUTI.NS' THEN 2
                WHEN 'CIPLA.NS' THEN 3
                ELSE 4
            END, c.ticker
            """,
            connection,
        )


def fetch_watchlist_column_order(
    db_path: str | Path | None = None,
) -> list[str] | None:
    with get_connection(db_path) as connection:
        row = connection.execute(
            "SELECT value FROM watchlist_metadata WHERE key = 'column_order'"
        ).fetchone()
    if row is None:
        return None
    order = json.loads(row["value"])
    if not isinstance(order, list) or not all(
        isinstance(column, str) for column in order
    ):
        raise ValueError("Saved watchlist column order is invalid.")
    return order


def save_watchlist_column_order(
    order: list[str], db_path: str | Path | None = None
) -> None:
    if (
        not order
        or any(not isinstance(column, str) or not column for column in order)
        or len(order) != len(set(order))
    ):
        raise ValueError("Watchlist column order must contain unique column names.")
    with get_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO watchlist_metadata (key, value)
            VALUES ('column_order', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (json.dumps(order),),
        )


def fetch_financials(
    ticker: str, db_path: str | Path | None = None
) -> pd.DataFrame:
    """Load annual illustrative financials for a watchlist ticker."""
    with get_connection(db_path) as connection:
        return pd.read_sql_query(
            """
            SELECT fiscal_year, revenue_cr, net_profit_cr, eps
            FROM annual_financials
            WHERE ticker = ?
            ORDER BY fiscal_year
            """,
            connection,
            params=(ticker,),
        )


def fetch_company(
    ticker: str, db_path: str | Path | None = None
) -> dict[str, Any] | None:
    """Load company and quote details, returning None for unknown tickers."""
    with get_connection(db_path) as connection:
        row = connection.execute(
            """
            SELECT c.ticker, c.name, c.sector, m.price_inr, m.day_change_pct,
                   m.market_cap_cr, m.data_label
            FROM companies AS c
            JOIN market_snapshots AS m ON m.ticker = c.ticker
            WHERE c.ticker = ?
            """,
            (ticker,),
        ).fetchone()
    return dict(row) if row else None


def find_screener_imports_by_hash(
    content_sha256: str, db_path: str | Path | None = None
) -> list[dict[str, Any]]:
    """Return prior snapshots for duplicate detection without mutating them."""
    with get_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT snapshot_id, ticker, company_name, source_filename, imported_at
            FROM screener_snapshots
            WHERE content_sha256 = ?
            ORDER BY imported_at DESC
            """,
            (content_sha256,),
        ).fetchall()
    return [dict(row) for row in rows]


def save_screener_snapshot(
    *,
    ticker: str,
    company_name: str,
    filename: str,
    content_sha256: str,
    observations: list[dict[str, Any]],
    analysis: dict[str, Any],
    current_price: float | None,
    db_path: str | Path | None = None,
) -> str:
    """Persist an immutable normalized data and analysis snapshot."""
    from stockvisualizer.screener_analysis import serialize_analysis
    from stockvisualizer.screener_import import PARSER_VERSION

    snapshot_id = str(uuid.uuid4())
    imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    metrics_json, findings_json, financial_status_value = serialize_analysis(analysis)
    with get_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO screener_company_mappings (ticker, company_name, confirmed_at)
            VALUES (?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                company_name = excluded.company_name,
                confirmed_at = excluded.confirmed_at
            """,
            (ticker, company_name, imported_at),
        )
        connection.execute(
            """
            INSERT INTO screener_snapshots (
                snapshot_id, ticker, company_name, source_name, source_filename,
                content_sha256, imported_at, parser_version, unit_policy, reporting_basis,
                reporting_metadata_status, financial_status, metrics_json,
                findings_json, analysis_config_json, current_price
            ) VALUES (?, ?, ?, 'Screener export', ?, ?, ?, ?, 'INR Crore confirmed',
                      ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                ticker,
                company_name,
                filename,
                content_sha256,
                imported_at,
                PARSER_VERSION,
                analysis.get("reporting_basis", "Unknown"),
                analysis["reporting_metadata_status"],
                financial_status_value,
                metrics_json,
                findings_json,
                json.dumps(analysis["anomaly_config"], sort_keys=True),
                current_price,
            ),
        )
        connection.execute(
            "DELETE FROM expected_growth_overrides WHERE ticker = ?",
            (ticker.strip().upper(),),
        )
        connection.execute(
            "DELETE FROM yahoo_market_data WHERE ticker = ?",
            (ticker.strip().upper(),),
        )
        connection.executemany(
            """
            INSERT INTO screener_observations (
                snapshot_id, statement, period, metric, value, unit, value_source,
                raw_value, invalid_value
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    snapshot_id,
                    item["statement"],
                    item["period"],
                    item["metric"],
                    item.get("value"),
                    item.get("unit", ""),
                    item.get("value_source", "screener_export"),
                    item.get("raw_value"),
                    int(bool(item.get("invalid_value", False))),
                )
                for item in observations
            ),
        )
    return snapshot_id


def fetch_screener_snapshots(
    ticker: str | None = None, db_path: str | Path | None = None
) -> list[dict[str, Any]]:
    """Load snapshot metadata and persisted analysis, newest first."""
    query = """
        SELECT snapshot_id, ticker, company_name, source_filename, imported_at,
               content_sha256, financial_status, reporting_metadata_status,
               reporting_basis, current_price, metrics_json, findings_json,
               analysis_config_json
        FROM screener_snapshots
    """
    params: tuple[str, ...] = ()
    if ticker:
        query += " WHERE ticker = ?"
        params = (ticker,)
    query += " ORDER BY imported_at DESC, snapshot_id"
    with get_connection(db_path) as connection:
        rows = connection.execute(query, params).fetchall()
    snapshots = []
    for row in rows:
        item = dict(row)
        item["metrics"] = json.loads(item.pop("metrics_json"))
        item["findings"] = json.loads(item.pop("findings_json"))
        item["analysis_config"] = json.loads(item.pop("analysis_config_json"))
        snapshots.append(item)
    return snapshots


def fetch_screener_observations(
    snapshot_id: str, db_path: str | Path | None = None
) -> list[dict[str, Any]]:
    with get_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT statement, period, metric, value, unit, value_source,
                   raw_value, invalid_value
            FROM screener_observations
            WHERE snapshot_id = ?
            ORDER BY period, statement, metric
            """,
            (snapshot_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def fetch_screener_companies(
    db_path: str | Path | None = None,
) -> list[dict[str, str]]:
    with get_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT ticker, company_name
            FROM screener_company_mappings
            ORDER BY company_name, ticker
            """
        ).fetchall()
    return [dict(row) for row in rows]


def fetch_watchlist_members(
    db_path: str | Path | None = None,
) -> list[dict[str, str]]:
    with get_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT ticker, company_name, added_at
            FROM watchlist_members
            ORDER BY company_name COLLATE NOCASE, ticker
            """
        ).fetchall()
    return [dict(row) for row in rows]


def fetch_expected_growth_overrides(
    db_path: str | Path | None = None,
) -> dict[str, float]:
    with get_connection(db_path) as connection:
        rows = connection.execute(
            "SELECT ticker, growth_rate FROM expected_growth_overrides"
        ).fetchall()
    return {str(row["ticker"]): float(row["growth_rate"]) for row in rows}


def save_expected_growth_override(
    ticker: str,
    growth_rate: float | None,
    db_path: str | Path | None = None,
) -> None:
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("A ticker is required for an expected growth override.")
    if growth_rate is None:
        with get_connection(db_path) as connection:
            connection.execute(
                "DELETE FROM expected_growth_overrides WHERE ticker = ?",
                (ticker,),
            )
        return
    if isinstance(growth_rate, bool):
        raise ValueError("Expected growth must be a finite percentage above -100%.")
    try:
        value = float(growth_rate)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(
            "Expected growth must be a finite percentage above -100%."
        ) from error
    if not math.isfinite(value) or value <= -1:
        raise ValueError("Expected growth must be a finite percentage above -100%.")
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO expected_growth_overrides (ticker, growth_rate, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                growth_rate = excluded.growth_rate,
                updated_at = excluded.updated_at
            """,
            (ticker, value, updated_at),
        )


def fetch_yahoo_market_data(
    db_path: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    with get_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT ticker, yahoo_symbol, price_inr, price_type, market_cap_inr, pe,
                   eps_inr, debt_to_equity,
                   currency, quote_timestamp, fetched_at
            FROM yahoo_market_data
            """
        ).fetchall()
    return {str(row["ticker"]): dict(row) for row in rows}


def save_yahoo_market_data(
    ticker: str,
    quote: dict[str, Any],
    db_path: str | Path | None = None,
) -> None:
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("A ticker is required for Yahoo market data.")
    yahoo_symbol = str(quote.get("yahoo_symbol") or "").strip().upper()
    currency = str(quote.get("currency") or "").strip().upper()
    fetched_at = str(quote.get("fetched_at") or "").strip()
    if not yahoo_symbol.endswith(".NS") or currency != "INR" or not fetched_at:
        raise ValueError("Yahoo market data must have an NSE symbol, INR currency, and fetch time.")
    values: dict[str, float | None] = {}
    for field in (
        "price_inr",
        "market_cap_inr",
        "pe",
        "eps_inr",
        "debt_to_equity",
    ):
        raw_value = quote.get(field)
        if raw_value is None:
            values[field] = None
            continue
        if isinstance(raw_value, bool):
            raise ValueError(f"Yahoo market data field {field} must be numeric.")
        try:
            value = float(raw_value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(
                f"Yahoo market data field {field} must be numeric."
            ) from error
        if not math.isfinite(value):
            raise ValueError(f"Yahoo market data field {field} must be finite.")
        values[field] = value
    if all(value is None for value in values.values()):
        raise ValueError(
            "Yahoo returned no usable price, market cap, P/E, EPS, or debt-to-equity value."
        )
    with get_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO yahoo_market_data (
                ticker, yahoo_symbol, price_inr, price_type, market_cap_inr, pe, eps_inr,
                debt_to_equity, currency, quote_timestamp, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                yahoo_symbol = excluded.yahoo_symbol,
                price_inr = excluded.price_inr,
                price_type = excluded.price_type,
                market_cap_inr = excluded.market_cap_inr,
                pe = excluded.pe,
                eps_inr = excluded.eps_inr,
                debt_to_equity = excluded.debt_to_equity,
                currency = excluded.currency,
                quote_timestamp = excluded.quote_timestamp,
                fetched_at = excluded.fetched_at
            """,
            (
                ticker,
                yahoo_symbol,
                values["price_inr"],
                quote.get("price_type"),
                values["market_cap_inr"],
                values["pe"],
                values["eps_inr"],
                values["debt_to_equity"],
                currency,
                quote.get("quote_timestamp"),
                fetched_at,
            ),
        )


def add_to_watchlist(
    ticker: str, company_name: str, db_path: str | Path | None = None
) -> bool:
    ticker = ticker.strip().upper()
    company_name = company_name.strip()
    if not ticker or not company_name:
        raise ValueError("Both ticker and company name are required.")
    added_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO watchlist_members (ticker, company_name, added_at)
            VALUES (?, ?, ?)
            """,
            (ticker, company_name, added_at),
        )
    return cursor.rowcount == 1


def remove_from_watchlist(
    ticker: str, db_path: str | Path | None = None
) -> bool:
    with get_connection(db_path) as connection:
        cursor = connection.execute(
            "DELETE FROM watchlist_members WHERE ticker = ?",
            (ticker.strip().upper(),),
        )
    return cursor.rowcount == 1


def save_watchlist_snapshot(
    tickers: list[str], db_path: str | Path | None = None
) -> str:
    normalized = list(dict.fromkeys(ticker.strip().upper() for ticker in tickers))
    if not normalized or any(not ticker for ticker in normalized):
        raise ValueError("Select at least one valid ticker for the snapshot.")
    snapshot_id = str(uuid.uuid4())
    with get_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO watchlist_snapshots (snapshot_id, created_at, tickers_json)
            VALUES (?, ?, ?)
            """,
            (
                snapshot_id,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                json.dumps(normalized),
            ),
        )
    return snapshot_id


def fetch_watchlist_snapshots(
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    with get_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT snapshot_id, created_at, tickers_json
            FROM watchlist_snapshots
            ORDER BY created_at DESC, snapshot_id
            """
        ).fetchall()
    return [
        {
            "snapshot_id": row["snapshot_id"],
            "created_at": row["created_at"],
            "tickers": json.loads(row["tickers_json"]),
        }
        for row in rows
    ]


def fetch_stock_catalog(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Combine known sample and imported symbols without conflating price sources."""
    catalog: dict[str, dict[str, Any]] = {}
    for _, sample in fetch_watchlist(db_path).iterrows():
        item = sample.to_dict()
        catalog[item["ticker"]] = {
            "ticker": item["ticker"],
            "company_name": item["name"],
            "sector": item["sector"],
            "sample_price": item["price_inr"],
            "sample_market_cap": item["market_cap_cr"],
            "data_label": item["data_label"],
            "snapshot": None,
        }

    for mapping in fetch_screener_companies(db_path):
        catalog.setdefault(
            mapping["ticker"],
            {
                "ticker": mapping["ticker"],
                "company_name": mapping["company_name"],
                "sector": "Unknown",
                "sample_price": None,
                "sample_market_cap": None,
                "data_label": None,
                "snapshot": None,
            },
        )

    for snapshot in fetch_screener_snapshots(db_path):
        item = catalog.setdefault(
            snapshot["ticker"],
            {
                "ticker": snapshot["ticker"],
                "company_name": snapshot["company_name"],
                "sector": "Unknown",
                "sample_price": None,
                "sample_market_cap": None,
                "data_label": None,
                "snapshot": None,
            },
        )
        if item["snapshot"] is None:
            item["company_name"] = snapshot["company_name"]
            item["snapshot"] = snapshot
    return sorted(
        catalog.values(),
        key=lambda item: (item["company_name"].casefold(), item["ticker"]),
    )
