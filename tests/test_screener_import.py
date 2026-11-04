from datetime import datetime
from io import BytesIO

from openpyxl import Workbook

from stockvisualizer.screener_import import parse_screener_file


def _screener_workbook(
    reported_eps: bool = False, invalid_reported_eps: bool = False
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data Sheet"
    sheet.append(["COMPANY NAME", "Test Company"])
    sheet.append(["Current Price", 100])
    sheet.append(["Market Capitalization", 567.8])
    sheet.append(["P/E", 12.5])
    sheet.append(
        [
            "Report Date",
            *[datetime(year, 3, 31) for year in range(2018, 2023)],
        ]
    )
    sheet.append(["Sales", 100, 110, 121, 133.1, 146.41])
    if reported_eps:
        eps_values = [9.5, 10.5, 11.5, 12.5, 13.5]
        if invalid_reported_eps:
            eps_values[2] = "invalid"
        sheet.append(["EPS", *eps_values])
    sheet.append(["Net profit", 10, 11, 12.1, 13.31, 14.641])
    sheet.append(
        [
            "Report Date",
            datetime(2023, 6, 30),
            datetime(2023, 9, 30),
            datetime(2023, 12, 31),
        ]
    )
    sheet.append(["Sales", 20, 25, 30])
    sheet.append(["Operating Profit", 4, 5, 6])
    sheet.append(["Report Date", *[datetime(year, 3, 31) for year in range(2018, 2023)]])
    sheet.append(["Equity Share Capital", 10, 10, 10, 10, 10])
    sheet.append(["Reserves", 20, 21, 22, 23, 24])
    sheet.append(["Borrowings", 5, 5, 5, 5, 5])
    sheet.append(["Total", 35, 36, 37, 38, 39])
    sheet.append(["Total", 50, 51, 52, 53, 54])
    sheet.append(["Report Date", *[datetime(year, 3, 31) for year in range(2018, 2023)]])
    sheet.append(["Cash from Operating Activity", 4, 5, 6, 7, 8])
    sheet.append(["Cash from Investing Activity", -1, -1, -1, -1, -1])
    sheet.append(["Cash from Financing Activity", 0, 0, 0, 0, 0])
    sheet.append(["Net Cash Flow", 3, 4, 5, 6, 7])
    sheet.append(
        ["Adjusted Equity Shares in Cr", 1, 1, 1, 1, 1]
    )
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_screener_workbook_parser_maps_statements_and_derives_eps():
    preview = parse_screener_file("test.xlsx", _screener_workbook())

    assert preview.unsupported_reason is None
    assert preview.company_name == "Test Company"
    assert len(preview.periods) == 5
    assert preview.current_price == 100
    assert preview.market_cap_cr == 567.8
    assert preview.reported_pe == 12.5
    observations = [item.to_dict() for item in preview.observations]
    assert any(item["statement"] == "balance_sheet" and item["metric"] == "borrowings" for item in observations)
    assert any(item["statement"] == "cash_flow" and item["metric"] == "operating_cash_flow" for item in observations)
    assert any(
        item["statement"] == "ratio"
        and item["metric"] == "operating_margin_pct"
        and item["value"] == 20
        for item in observations
    )
    assert any(
        item["metric"] == "eps_derived"
        and item["value"] == 10
        and item["value_source"].startswith("derived:")
        for item in observations
    )
    assert not any(item["metric"] == "eps_reported" for item in observations)
    assert "Reported EPS (derived EPS available)" in preview.missing_metrics


def test_current_price_parser_handles_currency_commas_and_decimal_precision():
    text = (
        'Company Name,Test Company\n'
        'Current Price,"₹1,234.50"\n'
        "Report Date,2022-03-31,2023-03-31,2024-03-31\n"
        "Sales,100,110,121\n"
        "Net profit,10,11,12.1\n"
    )
    preview = parse_screener_file("test.csv", text.encode("utf-8"))

    assert preview.current_price == 1234.5


def test_reported_eps_is_preserved_and_not_replaced_by_derived_eps():
    preview = parse_screener_file("reported.xlsx", _screener_workbook(True))

    reported = [item for item in preview.observations if item.metric == "eps_reported"]
    derived = [item for item in preview.observations if item.metric == "eps_derived"]
    assert len(reported) == 5
    assert reported[-1].value == 13.5
    assert not derived
    assert not any("Reported EPS" in item for item in preview.missing_metrics)


def test_invalid_reported_eps_is_not_silently_replaced_by_derived_eps():
    preview = parse_screener_file(
        "invalid.xlsx", _screener_workbook(True, invalid_reported_eps=True)
    )
    observations = [
        item for item in preview.observations if item.period == "2020-03-31"
    ]

    reported = next(item for item in observations if item.metric == "eps_reported")
    assert reported.value is None
    assert reported.invalid_value is True
    assert not any(item.metric == "eps_derived" for item in observations)


def test_screener_csv_accepts_data_sheet_grid_and_rejects_unknown_shapes():
    csv_grid = (
        "COMPANY NAME,Test CSV\n"
        "Current Price,25\n"
        "Report Date,2022-03-31,2023-03-31,2024-03-31,2025-03-31,2026-03-31\n"
        "Sales,10,11,12,13,14\n"
        "Net profit,1,1.1,1.2,1.3,1.4\n"
    ).encode()
    preview = parse_screener_file("test.csv", csv_grid)
    unknown = parse_screener_file("other.csv", b"Ticker,Revenue\nTEST,10\n")
    unknown_period = parse_screener_file(
        "period.csv",
        b"COMPANY NAME,Test\nReport Date,FY 2023,FY 2024\nSales,10,11\n",
    )

    assert preview.unsupported_reason is None
    assert preview.company_name == "Test CSV"
    assert unknown.unsupported_reason is not None
    assert "Unrecognized reporting-period" in (unknown_period.unsupported_reason or "")
