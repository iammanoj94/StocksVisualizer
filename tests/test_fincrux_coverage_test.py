from scripts.fincrux_coverage_test import _company_report_lines, build_report


def _sample_payload():
    return {
        "success": "true",
        "company": "Example Company",
        "trading_symbol": "EXAMPLE",
        "data": {
            "last_updated_at": "2026-01-01T00:00:00",
            "profit_and_loss": [
                ["Category", "Mar 2020", "Mar 2021", "Mar 2021", "Mar 2023", "TTM"],
                ["Sales", "100", "0", "120", "300", "330"],
                ["Net Profit", "10", "20", "22", None, "35"],
                ["EPS in Rs", "1.0", "2.0", "2.2", "invalid", "3.5"],
            ],
            "balance_sheet": [
                ["Category", "Mar 2020", "Mar 2021"],
                ["Equity Capital", "10", "10"],
                ["Borrowings", "20", "21"],
            ],
            "cash_flows": [["Category", "Mar 2020"], ["Net Cash Flow", "5"]],
            "quaterly_results": [
                ["Category", "Jun 2025"],
                ["Sales", "30"],
            ],
            "reporting_basis": "Standalone financial statements",
        },
    }


def test_actual_matrix_shape_and_data_quality_are_reported():
    report = "\n".join(_company_report_lines(_sample_payload()))

    assert "4 (3 distinct fiscal years)" in report
    assert "Duplicate annual years: 2021" in report
    assert "Missing annual years: 2022" in report
    assert "Revenue/sales zero values: Mar 2021" in report
    assert "Net profit null/blank/non-numeric values: Mar 2023" in report
    assert "EPS null/blank/non-numeric values: Mar 2023 (non-numeric: invalid)" in report
    assert "standalone indication" in report
    assert "Balance-sheet observation count: 2" in report
    assert "Borrowings" in report
    assert "Cash-flow observation count: 1" in report
    assert "Quarterly results available: Yes (1 dated periods" in report


def test_report_is_coverage_only_and_missing_structure_is_explicit():
    report = build_report(
        {
            "HDFCBANK": {
                "status_code": 200,
                "response_file": "HDFCBANK.json",
                "payload": _sample_payload(),
            },
            "MARUTI": {
                "status_code": 503,
                "response_file": "MARUTI.json",
                "error": "HTTP 503: temporarily unavailable",
                "payload": None,
            },
            "CIPLA": {
                "status_code": 200,
                "response_file": "CIPLA.json",
                "payload": {"company": "Cipla"},
            },
        }
    )

    assert "No CAGR or other growth calculation is performed" in report
    assert "HTTP 503: temporarily unavailable" in report
    assert "Response has no `data` object." in report
