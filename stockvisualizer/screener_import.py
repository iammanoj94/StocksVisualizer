from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException


PARSER_VERSION = "1.0"
FINANCIAL_METRICS = {
    "sales": ("annual", "revenue", "INR Crore"),
    "revenue": ("annual", "revenue", "INR Crore"),
    "raw material cost": ("annual", "raw_material_cost", "INR Crore"),
    "change in inventory": ("annual", "change_in_inventory", "INR Crore"),
    "power and fuel": ("annual", "power_and_fuel", "INR Crore"),
    "other mfr. exp": ("annual", "other_manufacturing_expenses", "INR Crore"),
    "employee cost": ("annual", "employee_cost", "INR Crore"),
    "selling and admin": ("annual", "selling_and_admin", "INR Crore"),
    "other expenses": ("annual", "other_expenses", "INR Crore"),
    "other income": ("annual", "other_income", "INR Crore"),
    "depreciation": ("annual", "depreciation", "INR Crore"),
    "interest": ("annual", "interest", "INR Crore"),
    "profit before tax": ("annual", "profit_before_tax", "INR Crore"),
    "tax": ("annual", "tax", "INR Crore"),
    "net profit": ("annual", "net_profit", "INR Crore"),
    "dividend amount": ("annual", "dividend_amount", "INR Crore"),
    "eps": ("annual", "eps_reported", "INR"),
    "earnings per share": ("annual", "eps_reported", "INR"),
    "equity share capital": ("balance_sheet", "equity_share_capital", "INR Crore"),
    "reserves": ("balance_sheet", "reserves", "INR Crore"),
    "borrowings": ("balance_sheet", "borrowings", "INR Crore"),
    "deposits": ("balance_sheet", "deposits", "INR Crore"),
    "other liabilities": ("balance_sheet", "other_liabilities", "INR Crore"),
    "net block": ("balance_sheet", "net_block", "INR Crore"),
    "capital work in progress": ("balance_sheet", "capital_work_in_progress", "INR Crore"),
    "investments": ("balance_sheet", "investments", "INR Crore"),
    "other assets": ("balance_sheet", "other_assets", "INR Crore"),
    "receivables": ("balance_sheet", "receivables", "INR Crore"),
    "inventory": ("balance_sheet", "inventory", "INR Crore"),
    "cash & bank": ("balance_sheet", "cash_and_bank", "INR Crore"),
    "no. of equity shares": ("balance_sheet", "equity_shares", "Crore shares"),
    "new bonus shares": ("balance_sheet", "new_bonus_shares", "Crore shares"),
    "face value": ("balance_sheet", "face_value", "INR"),
    "cash from operating activity": ("cash_flow", "operating_cash_flow", "INR Crore"),
    "cash from investing activity": ("cash_flow", "investing_cash_flow", "INR Crore"),
    "cash from financing activity": ("cash_flow", "financing_cash_flow", "INR Crore"),
    "net cash flow": ("cash_flow", "net_cash_flow", "INR Crore"),
    "adjusted equity shares in cr": ("annual", "adjusted_shares_cr", "Crore shares"),
}

QUARTERLY_METRICS = {
    "sales": "revenue",
    "revenue": "revenue",
    "net profit": "net_profit",
    "eps": "eps_reported",
    "earnings per share": "eps_reported",
    "expenses": "expenses",
    "other income": "other_income",
    "depreciation": "depreciation",
    "interest": "interest",
    "profit before tax": "profit_before_tax",
    "tax": "tax",
    "operating profit": "operating_profit",
}


@dataclass(frozen=True)
class Observation:
    statement: str
    period: str
    metric: str
    value: float | None
    unit: str
    value_source: str = "screener_export"
    raw_value: str | None = None
    invalid_value: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement": self.statement,
            "period": self.period,
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "value_source": self.value_source,
            "raw_value": self.raw_value,
            "invalid_value": self.invalid_value,
        }


@dataclass(frozen=True)
class ScreenerPreview:
    filename: str
    content_sha256: str
    company_name: str | None
    current_price: float | None
    observations: tuple[Observation, ...]
    missing_metrics: tuple[str, ...]
    warnings: tuple[str, ...]
    unsupported_reason: str | None = None
    market_cap_cr: float | None = None
    reported_pe: float | None = None

    @property
    def periods(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.period
                    for item in self.observations
                    if item.statement == "annual"
                }
            )
        )


def _label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _period(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return None
    text = str(value).strip()
    for pattern in (
        "%Y-%m-%d",
        "%d-%b-%Y",
        "%b-%Y",
        "%b %Y",
        "%B %Y",
        "%b-%y",
        "%Y/%m/%d",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("₹", "")
        if not text or text in {"-", "—", "NA", "N/A"}:
            return None
        if text.startswith("(") and text.endswith(")"):
            text = "-" + text[1:-1]
        value = text
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _invalid_source_value(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip().upper()
    return bool(text and text not in {"-", "—", "NA", "N/A"} and _number(value) is None)


def _rows_from_file(filename: str, content: bytes) -> list[list[Any]]:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "xlsx":
        workbook = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        sheet_name = next(
            (name for name in workbook.sheetnames if _label(name) == "data sheet"),
            None,
        )
        if sheet_name is None:
            raise ValueError("Workbook has no Data Sheet tab.")
        return [list(row) for row in workbook[sheet_name].iter_rows(values_only=True)]
    if suffix == "csv":
        text = None
        for encoding in ("utf-8-sig", "utf-8", "cp1252"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ValueError("CSV encoding is not supported.")
        return [list(row) for row in csv.reader(io.StringIO(text))]
    raise ValueError("Unsupported file type; select an .xlsx or .csv file.")


def parse_screener_file(filename: str, content: bytes) -> ScreenerPreview:
    """Parse a Screener Data Sheet grid without guessing unknown layouts."""
    digest = hashlib.sha256(content).hexdigest()
    try:
        rows = _rows_from_file(filename, content)
    except (
        OSError,
        ValueError,
        KeyError,
        InvalidFileException,
        zipfile.BadZipFile,
    ) as error:
        return ScreenerPreview(filename, digest, None, None, (), (), (), str(error))

    if not rows or not any(_label(row[0] if row else None) == "company name" for row in rows):
        return ScreenerPreview(
            filename,
            digest,
            None,
            None,
            (),
            (),
            (),
            "No recognized Screener Data Sheet company-name label was found.",
        )

    company_name: str | None = None
    current_price: float | None = None
    market_cap_cr: float | None = None
    reported_pe: float | None = None
    headers: list[tuple[int, list[tuple[int, str]]]] = []
    unrecognized_periods: list[str] = []
    for row_index, row in enumerate(rows):
        key = _label(row[0] if row else None)
        if key == "company name":
            company_name = str(row[1]).strip() if len(row) > 1 and row[1] else None
        elif key == "current price" and len(row) > 1:
            current_price = _number(row[1])
        elif key in {"market capitalization", "market cap"} and len(row) > 1:
            market_cap_cr = _number(row[1])
        elif key in {"p/e", "pe", "stock p/e", "price to earnings"} and len(row) > 1:
            reported_pe = _number(row[1])
        elif key in {"report date", "period"}:
            dates = []
            for column, cell in enumerate(row[1:], start=1):
                if cell is None or not str(cell).strip():
                    continue
                parsed = _period(cell)
                if parsed is None:
                    unrecognized_periods.append(str(cell))
                else:
                    dates.append((column, parsed))
            if dates:
                headers.append((row_index, dates))

    if unrecognized_periods:
        return ScreenerPreview(
            filename,
            digest,
            company_name,
            current_price,
            (),
            (),
            (),
            "Unrecognized reporting-period values: "
            + ", ".join(sorted(set(unrecognized_periods))),
        )

    observations: list[Observation] = []
    warnings: list[str] = []
    unmapped_labels: set[str] = set()
    used_header_types: set[str] = set()
    for header_index, (row_index, periods) in enumerate(headers):
        end = headers[header_index + 1][0] if header_index + 1 < len(headers) else len(rows)
        block_labels = {_label(rows[index][0] if rows[index] else None) for index in range(row_index + 1, end)}
        if {"cash from operating activity", "cash from investing activity"} & block_labels:
            statement = "cash_flow"
        elif {"equity share capital", "reserves", "borrowings"} & block_labels:
            statement = "balance_sheet"
        else:
            day_spans = []
            parsed_dates = [date.fromisoformat(item[1]) for item in periods]
            day_spans = [(b - a).days for a, b in zip(parsed_dates, parsed_dates[1:])]
            quarterly = bool(day_spans) and statistics_median(day_spans) < 200
            statement = "quarterly" if quarterly else "annual"
        if statement in used_header_types:
            warnings.append(f"Multiple {statement} period blocks were found.")
        used_header_types.add(statement)

        for data_index in range(row_index + 1, end):
            row = rows[data_index]
            key = _label(row[0] if row else None)
            metric_info = (
                (
                    statement,
                    QUARTERLY_METRICS[key],
                    "INR" if QUARTERLY_METRICS[key] == "eps_reported" else "INR Crore",
                )
                if statement == "quarterly" and key in QUARTERLY_METRICS
                else FINANCIAL_METRICS.get(key)
            )
            if metric_info is None:
                if key == "total" and statement == "balance_sheet":
                    total_count = sum(
                        1
                        for item in observations
                        if item.statement == "balance_sheet"
                        and item.metric.startswith("total_")
                    )
                    metric_info = (
                        "balance_sheet",
                        "total_liabilities" if total_count == 0 else "total_assets",
                        "INR Crore",
                    )
                else:
                    if key in {
                        "price:",
                        "derived:",
                        "meta",
                        "profit & loss",
                        "quarters",
                        "balance sheet",
                        "cash flow:",
                    }:
                        continue
                    if key and any(
                        column < len(row) and row[column] not in (None, "")
                        for column, _ in periods
                    ):
                        unmapped_labels.add(str(row[0]).strip())
                    continue
            metric_statement, metric_name, unit = metric_info
            if metric_statement != statement and not (
                statement == "annual" and metric_name == "adjusted_shares_cr"
            ):
                continue
            for column, period in periods:
                value = _number(row[column]) if column < len(row) else None
                raw_value = row[column] if column < len(row) else None
                observations.append(
                    Observation(
                        statement,
                        period,
                        metric_name,
                        value,
                        unit,
                        "screener_export",
                        str(raw_value) if raw_value is not None else None,
                        _invalid_source_value(raw_value),
                    )
                )

    annual_periods = sorted(
        {
            item.period
            for item in observations
            if item.statement == "annual"
        }
    )
    annual_metrics = {
        item.metric
        for item in observations
        if item.statement == "annual" and item.value is not None
    }
    quarterly_by_period: dict[str, dict[str, float | None]] = {}
    for item in observations:
        if item.statement == "quarterly":
            quarterly_by_period.setdefault(item.period, {})[item.metric] = item.value
    for period, values in quarterly_by_period.items():
        revenue = values.get("revenue")
        operating_profit = values.get("operating_profit")
        if revenue is not None and revenue != 0 and operating_profit is not None:
            observations.append(
                Observation(
                    "ratio",
                    period,
                    "operating_margin_pct",
                    operating_profit / revenue * 100,
                    "%",
                    "derived: operating_profit / revenue * 100",
                )
            )

    # Adjusted shares are outside the annual P&L block in the observed exports.
    shares_row = next(
        (
            row_index
            for row_index, row in enumerate(rows)
            if _label(row[0] if row else None) == "adjusted equity shares in cr"
        ),
        None,
    )
    if shares_row is not None:
        annual_header = next(
            (
                (index, periods)
                for index, periods in headers
                if index < shares_row
                and any(
                    item.statement == "annual"
                    and item.period in {period for _, period in periods}
                    for item in observations
                )
            ),
            None,
        )
        if annual_header:
            _, annual_columns = annual_header
            row = rows[shares_row]
            for column, period in annual_columns:
                value = _number(row[column]) if column < len(row) else None
                observations.append(
                    Observation(
                        "annual",
                        period,
                        "adjusted_shares_cr",
                        value,
                        "Crore shares",
                        "screener_export",
                        str(row[column]) if column < len(row) and row[column] is not None else None,
                        _invalid_source_value(row[column]) if column < len(row) else False,
                    )
                )
                has_reported_eps = any(
                    item.statement == "annual"
                    and item.period == period
                    and item.metric == "eps_reported"
                    and (item.value is not None or item.invalid_value)
                    for item in observations
                )
                if value is not None and value > 0 and not has_reported_eps:
                    profit = next(
                        (
                            item.value
                            for item in observations
                            if item.statement == "annual"
                            and item.period == period
                            and item.metric == "net_profit"
                        ),
                        None,
                    )
                    if profit is not None:
                        observations.append(
                            Observation(
                                "annual",
                                period,
                                "eps_derived",
                                profit / value,
                                "INR",
                                "derived: net_profit / adjusted_equity_shares",
                            )
                        )

    available_by_statement: dict[str, set[str]] = {}
    for item in observations:
        if item.value is not None:
            available_by_statement.setdefault(item.statement, set()).add(item.metric)
    if not company_name:
        warnings.append("Company name is empty.")
    if unmapped_labels:
        warnings.append(
            "Unmapped statement labels require review: "
            + ", ".join(sorted(unmapped_labels, key=str.casefold))
        )
    if len(annual_periods) == 0:
        return ScreenerPreview(
            filename,
            digest,
            company_name,
            current_price,
            tuple(observations),
            (),
            tuple(warnings),
            "No annual financial periods were recognized in the Data Sheet.",
            market_cap_cr,
            reported_pe,
        )

    annual_available = available_by_statement.get("annual", set())
    balance_available = available_by_statement.get("balance_sheet", set())
    cash_flow_available = available_by_statement.get("cash_flow", set())
    missing_items = [
        name
        for name, metric in (
            ("Annual revenue", "revenue"),
            ("Annual net profit", "net_profit"),
        )
        if metric not in annual_available
    ]
    if current_price is None:
        missing_items.append("Current price (P/E and payback unavailable)")
    missing_items.extend(
        f"Balance sheet: {label}"
        for label, metric in (
            ("Equity share capital", "equity_share_capital"),
            ("Reserves", "reserves"),
            ("Borrowings", "borrowings"),
            ("Deposits", "deposits"),
            ("Total liabilities", "total_liabilities"),
            ("Total assets", "total_assets"),
        )
        if metric not in balance_available
    )
    missing_items.extend(
        f"Cash flow: {label}"
        for label, metric in (
            ("Operating", "operating_cash_flow"),
            ("Investing", "investing_cash_flow"),
            ("Financing", "financing_cash_flow"),
            ("Net cash flow", "net_cash_flow"),
        )
        if metric not in cash_flow_available
    )
    if "quarterly" not in available_by_statement:
        missing_items.append("Quarterly results")
    if "eps_reported" not in annual_metrics:
        missing_items.append(
            "Reported EPS (derived EPS available)"
            if any(item.metric == "eps_derived" for item in observations)
            else "Reported EPS"
        )
    missing = tuple(missing_items)
    if "eps_reported" not in annual_metrics and any(
        item.metric == "eps_derived" for item in observations
    ):
        warnings.append(
            "Reported EPS was not present; derived EPS is stored separately and "
            "is used only when reported EPS is unavailable."
        )
    if len(annual_periods) < 10:
        warnings.append(
            "Fewer than 10 annual observations are available; the maximum-history "
            "CAGR will use the latest consecutive observations and be labelled "
            "with its actual period."
        )
    blank_periods: dict[tuple[str, str], list[str]] = defaultdict(list)
    for item in observations:
        if item.value is None and not item.invalid_value:
            blank_periods[(item.statement, item.metric)].append(item.period)
    for (statement, metric), periods_with_blanks in sorted(blank_periods.items()):
        distinct_periods = sorted(set(periods_with_blanks))
        warnings.append(
            f"Blank {statement.replace('_', ' ')} values for "
            f"{metric.replace('_', ' ')} in {', '.join(distinct_periods)}; "
            "values remain null and were not filled."
        )
    warnings.append(
        "The Data Sheet has no dedicated raw-ratios block. Formula-only ratio cells "
        "are not treated as source values. Spreadsheet-reported P/E is unavailable "
        "unless an explicit P/E value is present; analytical P/E values are kept "
        "separate."
    )
    return ScreenerPreview(
        filename,
        digest,
        company_name,
        current_price,
        tuple(observations),
        missing,
        tuple(warnings),
        market_cap_cr=market_cap_cr,
        reported_pe=reported_pe,
    )


def statistics_median(values: list[int]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2
