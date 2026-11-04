from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "fincrux_test"
COMPANIES = ("HDFCBANK", "MARUTI", "CIPLA")
ENDPOINT = "https://api.fincrux.org/api/financials/{company_symbol}"
TIMEOUT_SECONDS = 30


def _sanitize(message: str, api_key: str) -> str:
    """Redact credentials and API-key query parameters from untrusted text."""
    sanitized = message
    for secret in {api_key, quote(api_key, safe=""), quote_plus(api_key)}:
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    return re.sub(
        r"(?i)(api_key=)[^&\s]+",
        r"\1[REDACTED]",
        sanitized,
    )


def fetch_responses(api_key: str) -> dict[str, dict[str, Any]]:
    """Make exactly one non-forced GET per company and save each response body."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}
    for symbol in COMPANIES:
        url = ENDPOINT.format(company_symbol=symbol)
        try:
            response = requests.get(
                url,
                params={"api_key": api_key},
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            results[symbol] = {
                "status_code": None,
                "error": _sanitize(
                    f"Network error ({type(error).__name__}): {error}", api_key
                ),
                "response_file": None,
                "payload": None,
            }
            continue

        try:
            payload = response.json()
        except (requests.JSONDecodeError, json.JSONDecodeError):
            payload = None

        extension = "json" if payload is not None else "txt"
        response_path = OUTPUT_DIR / f"{symbol}.{extension}"
        response_path.write_bytes(response.content)
        results[symbol] = {
            "status_code": response.status_code,
            "error": None,
            "response_file": response_path.name,
            "payload": payload,
        }
        if not response.ok:
            results[symbol]["error"] = _sanitize(
                _provider_error(payload, response.status_code), api_key
            )
        elif payload is None:
            results[symbol]["error"] = (
                "Successful HTTP response did not contain valid JSON."
            )
    return results


def _provider_error(payload: Any, status_code: int) -> str:
    if isinstance(payload, dict):
        for key in ("message", "error", "detail"):
            message = payload.get(key)
            if isinstance(message, str) and message.strip():
                return f"HTTP {status_code}: {message.strip()}"
    return f"HTTP {status_code}: request was not successful."


def _load_saved_responses() -> dict[str, dict[str, Any]]:
    status_path = OUTPUT_DIR / "fetch_status.json"
    saved_status = (
        json.loads(status_path.read_text(encoding="utf-8"))
        if status_path.exists()
        else {}
    )
    results = {}
    for symbol in COMPANIES:
        json_path = OUTPUT_DIR / f"{symbol}.json"
        text_path = OUTPUT_DIR / f"{symbol}.txt"
        path = json_path if json_path.exists() else text_path
        if not path.exists():
            results[symbol] = {
                "status_code": None,
                "error": "No saved response was found.",
                "response_file": None,
                "payload": None,
            }
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        results[symbol] = {
            "status_code": saved_status.get(symbol, {}).get("status_code"),
            "error": (
                saved_status.get(symbol, {}).get("error")
                or (None if payload is not None else "Saved response is not valid JSON.")
            ),
            "response_file": path.name,
            "payload": payload,
        }
    return results


def _save_fetch_status(results: dict[str, dict[str, Any]]) -> None:
    status = {
        symbol: {
            "status_code": result.get("status_code"),
            "error": result.get("error"),
            "response_file": result.get("response_file"),
        }
        for symbol, result in results.items()
    }
    (OUTPUT_DIR / "fetch_status.json").write_text(
        json.dumps(status, indent=2), encoding="utf-8"
    )


def _print_fetch_results(results: dict[str, dict[str, Any]]) -> None:
    for symbol, result in results.items():
        status = result.get("status_code")
        status_text = f"HTTP {status}" if status is not None else "No HTTP response"
        print(f"{symbol}: {status_text}; saved={result.get('response_file') or 'no'}")
        if result.get("error"):
            print(f"  {result['error']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch or analyze Fincrux company-financial coverage."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--analyze-only",
        action="store_true",
        help="Analyze saved responses without making any network requests.",
    )
    mode.add_argument(
        "--fetch-only",
        action="store_true",
        help="Fetch once per company and save responses without analyzing.",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.analyze_only:
        results = _load_saved_responses()
    else:
        load_dotenv(PROJECT_ROOT / ".env")
        api_key = os.getenv("FINCRUX_API_KEY")
        if not api_key or not api_key.strip():
            raise SystemExit(
                "FINCRUX_API_KEY is not configured in the environment or project .env."
            )
        results = fetch_responses(api_key.strip())
        _save_fetch_status(results)
        if args.fetch_only:
            _print_fetch_results(results)
            return
    report = build_report(results)
    report_path = OUTPUT_DIR / "coverage_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Coverage report: {report_path}")
    _print_fetch_results(results)


def build_report(results: dict[str, dict[str, Any]]) -> str:
    """Build the coverage report from observed response fields."""
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Fincrux Historical Financial Data Coverage",
        "",
        f"Generated: {generated}",
        "",
        "> Data coverage only. No CAGR or other growth calculation is performed. "
        "Fincrux output is not assumed to be consolidated unless the response "
        "explicitly identifies the reporting basis.",
        "",
        "Requests: one GET per symbol; `force_update` was not sent. API keys are "
        "not included in this report.",
        "",
        "Observed response structure: JSON object with `company`, `trading_symbol`, "
        "and `data`; statements are category-by-period arrays whose first row is "
        "the column header. Annual P&L observations below use `Mar YYYY` columns; "
        "the `TTM` column is excluded. The response uses the field spelling "
        "`quaterly_results`. Values are reproduced as returned; no unit conversion "
        "or imputation is applied.",
        "",
    ]
    for symbol in COMPANIES:
        result = results[symbol]
        status = result.get("status_code")
        lines.extend(
            [
                f"## {symbol}",
                "",
                f"- HTTP status: {status if status is not None else 'No response'}",
                f"- Saved response: `{result.get('response_file') or 'not available'}`",
            ]
        )
        if result.get("error"):
            lines.extend(["- Error: " + _markdown_escape(str(result["error"])), ""])
            continue
        payload = result.get("payload")
        if not isinstance(payload, dict):
            lines.extend(["- Error: Response is not a JSON object.", ""])
            continue
        lines.extend(_company_report_lines(payload))
    return "\n".join(lines).rstrip() + "\n"


def _company_report_lines(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return ["- Error: Response has no `data` object.", ""]

    company = payload.get("company", "not identified")
    returned_symbol = payload.get("trading_symbol", "not identified")
    pnl = _statement_table(data.get("profit_and_loss"))
    annual_periods = _period_columns(pnl, annual_only=True)
    years = [period["year"] for period in annual_periods]
    unique_years = sorted(set(years))
    duplicate_years = sorted({year for year in years if years.count(year) > 1})
    missing_years = (
        sorted(set(range(unique_years[0], unique_years[-1] + 1)) - set(unique_years))
        if unique_years
        else []
    )

    sales_row = _find_row(pnl, {"revenue", "sales"})
    profit_row = _find_row(pnl, {"net profit"})
    eps_row = _find_row(pnl, {"eps in rs", "eps"})
    metric_rows = {
        "Revenue/sales": sales_row,
        "Net profit": profit_row,
        "EPS": eps_row,
    }

    complete_years = []
    for period in annual_periods:
        if all(
            _numeric_value(_value_at(row, period["index"])) is not None
            for row in metric_rows.values()
        ):
            complete_years.append(period["year"])
    longest_streak = _longest_consecutive_streak(complete_years)
    first_period = annual_periods[0]["label"] if annual_periods else "not identified"
    latest_period = annual_periods[-1]["label"] if annual_periods else "not identified"

    lines = [
        f"- Company name: {_markdown_escape(str(company))}",
        f"- Company symbol: {_markdown_escape(str(returned_symbol))}",
        f"- Latest financial update timestamp: "
        f"{_markdown_escape(str(data.get('last_updated_at') or 'not identified'))}",
        f"- Annual P&L observations: {len(annual_periods)} "
        f"({len(unique_years)} distinct fiscal years)",
        f"- First / latest annual financial periods: {first_period} / {latest_period}",
        f"- At least 11 consecutive annual observations: "
        f"{'Yes' if longest_streak >= 11 else 'No'} "
        f"(longest complete Revenue/Net profit/EPS streak: {longest_streak})",
        f"- At least 5 consecutive annual observations: "
        f"{'Yes' if longest_streak >= 5 else 'No'}",
        "- Reporting basis (consolidated/standalone): "
        + _reporting_basis(payload),
        "",
        "### Annual revenue, net profit, and EPS",
        "",
        "| Financial year | Revenue/sales (as returned) | Net profit (as returned) | EPS (as returned) |",
        "|---|---:|---:|---:|",
    ]
    if not annual_periods:
        lines.append("| No annual fiscal-year columns identified | — | — | — |")
    else:
        for period in annual_periods:
            values = [
                _format_cell(_value_at(metric_rows[label], period["index"]))
                for label in metric_rows
            ]
            lines.append(
                f"| {period['label']} | {values[0]} | {values[1]} | {values[2]} |"
            )
    lines.extend(["", "### Coverage and data-quality checks", ""])
    lines.append(
        "- Missing annual years: "
        + (", ".join(map(str, missing_years)) if missing_years else "None identified")
    )
    lines.append(
        "- Duplicate annual years: "
        + (", ".join(map(str, duplicate_years)) if duplicate_years else "None identified")
    )
    gaps = [
        f"{earlier} to {later} ({later - earlier} years apart)"
        for earlier, later in zip(unique_years, unique_years[1:])
        if later - earlier > 1
    ]
    lines.append(
        "- Unusual gaps in annual periods: "
        + ("; ".join(gaps) if gaps else "None identified")
    )
    for label, row in metric_rows.items():
        if row is None:
            lines.append(f"- {label}: matching P&L row not found.")
            continue
        zeros = []
        nulls = []
        for period in annual_periods:
            raw_value = _value_at(row, period["index"])
            numeric_value = _numeric_value(raw_value)
            if _is_null_value(raw_value):
                nulls.append(period["label"])
            elif numeric_value == 0:
                zeros.append(period["label"])
            elif numeric_value is None:
                nulls.append(f"{period['label']} (non-numeric: {raw_value})")
        lines.append(
            f"- {label} zero values: "
            + (", ".join(zeros) if zeros else "None identified")
        )
        lines.append(
            f"- {label} null/blank/non-numeric values: "
            + (", ".join(nulls) if nulls else "None identified")
        )

    balance_sheet = _statement_table(data.get("balance_sheet"))
    balance_periods = _period_columns(balance_sheet)
    balance_fields = [
        str(row[0]).strip()
        for row in balance_sheet["rows"]
        if row and any(
            term in str(row[0]).casefold()
        for term in (
            "debt",
            "borrow",
            "liabilit",
            "equity",
            "reserve",
            "capital",
            "deposit",
        )
        )
    ]
    cash_periods = _period_columns(_statement_table(data.get("cash_flows")))
    quarterly = _statement_table(data.get("quaterly_results"))
    quarter_periods = _period_columns(quarterly)
    lines.extend(
        [
            "",
            "### Other statements",
            "",
            f"- Balance-sheet observation count: {len(balance_periods)} "
            f"({', '.join(period['label'] for period in balance_periods) or 'no dated periods'})",
            "- Available debt/liability/equity-related fields: "
            + (", ".join(balance_fields) if balance_fields else "None identified"),
            f"- Cash-flow observation count: {len(cash_periods)} "
            f"({', '.join(period['label'] for period in cash_periods) or 'no dated periods'})",
            f"- Quarterly results available: {'Yes' if quarter_periods else 'No'} "
            f"({len(quarter_periods)} dated periods; response field "
            "`quaterly_results`)" if quarter_periods else
            "- Quarterly results available: No (no dated periods in response field `quaterly_results`)",
            "",
        ]
    )
    return lines


def _statement_table(value: Any) -> dict[str, Any]:
    """Normalize the observed category-by-period array response shape."""
    if not isinstance(value, list) or not value:
        return {"header": [], "rows": []}
    header = value[0] if isinstance(value[0], list) else []
    rows = [row for row in value[1:] if isinstance(row, list)]
    return {"header": header, "rows": rows}


def _period_columns(
    table: dict[str, Any], annual_only: bool = False
) -> list[dict[str, Any]]:
    periods = []
    for index, raw_label in enumerate(table["header"][1:], start=1):
        label = str(raw_label).strip()
        match = re.fullmatch(r"([A-Za-z]{3})\s+(\d{4})", label)
        if not match:
            continue
        month, year_text = match.groups()
        if annual_only and month.casefold() != "mar":
            continue
        periods.append(
            {"label": label, "year": int(year_text), "month": month, "index": index}
        )
    return periods


def _find_row(table: dict[str, Any], accepted_labels: set[str]) -> list[Any] | None:
    for row in table["rows"]:
        if row and " ".join(str(row[0]).casefold().split()) in accepted_labels:
            return row
    return None


def _value_at(row: list[Any] | None, index: int) -> Any:
    return row[index] if row is not None and index < len(row) else None


def _numeric_value(value: Any) -> float | None:
    if _is_null_value(value) or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    text = str(value).strip()
    text = text.replace(",", "").replace("₹", "").replace("%", "").strip()
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        numeric = float(text)
    except ValueError:
        return None
    return numeric if math.isfinite(numeric) else None


def _is_null_value(value: Any) -> bool:
    return value is None or (
        isinstance(value, str)
        and value.strip().casefold()
        in {"", "-", "—", "–", "na", "n/a", "null", "none"}
    )


def _longest_consecutive_streak(years: list[int]) -> int:
    longest = current = 0
    previous_year = None
    for year in sorted(set(years)):
        current = (
            current + 1
            if previous_year is not None and year == previous_year + 1
            else 1
        )
        longest = max(longest, current)
        previous_year = year
    return longest


def _format_cell(value: Any) -> str:
    return _markdown_escape("not available" if value is None else str(value))


def _reporting_basis(payload: dict[str, Any]) -> str:
    matches: list[str] = []

    def inspect(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                inspect(key, f"{path} key" if path else "key")
                inspect(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                inspect(child, f"{path}[{index}]")
        elif isinstance(value, str):
            lowered = value.casefold()
            for term in ("consolidated", "standalone"):
                if term in lowered:
                    matches.append(f"{term} indication at `{path}`")

    inspect(payload, "")
    return "; ".join(dict.fromkeys(matches)) if matches else "not identified"


def _markdown_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


if __name__ == "__main__":
    main()
