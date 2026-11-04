import pytest

from stockvisualizer.screener_browser import (
    _safe_download_filename,
    DownloadResult,
    iter_download_results,
    parse_symbol_queue,
    validate_delay,
)


def test_symbol_queue_normalizes_and_deduplicates_symbols():
    queue = parse_symbol_queue(" hdfcbank \nMARUTI\nHDFCBANK\n\nCIPLA")

    assert queue.symbols == ("HDFCBANK", "MARUTI", "CIPLA")
    assert queue.duplicates == ("HDFCBANK",)


def test_symbol_queue_accepts_common_nse_symbol_punctuation():
    queue = parse_symbol_queue("M&M\nBAJAJ-AUTO\n3MINDIA")

    assert queue.symbols == ("M&M", "BAJAJ-AUTO", "3MINDIA")


@pytest.mark.parametrize(
    "text",
    (
        "",
        "RELIANCE\ninvalid symbol",
        "A" * 51,
        "RELIANCE\n" + "\n".join(f"STOCK{number}" for number in range(100)),
    ),
)
def test_symbol_queue_rejects_empty_invalid_or_oversized_queues(text):
    with pytest.raises(ValueError):
        parse_symbol_queue(text)


def test_symbol_queue_rejects_invalid_limit():
    with pytest.raises(ValueError):
        parse_symbol_queue("RELIANCE", max_symbols=0)


@pytest.mark.parametrize("delay", (True, 2, 31, 3.5))
def test_browser_delay_enforces_bounded_whole_seconds(delay):
    with pytest.raises(ValueError):
        validate_delay(delay)


def test_browser_delay_accepts_supported_bounds():
    assert validate_delay(3) == 3
    assert validate_delay(30) == 30


def test_download_filename_is_safe_and_limited_to_supported_formats():
    assert _safe_download_filename(
        "HDFCBANK", "../../financials 2026.xlsx"
    ) == "HDFCBANK__financials_2026.xlsx"
    assert _safe_download_filename("CIPLA", "export.pdf") is None


def test_download_queue_continues_after_company_level_failure_and_keeps_successes():
    def downloader(symbol):
        if symbol == "BAD":
            return DownloadResult(
                symbol, None, None, None, "company not found", False
            )
        return DownloadResult(symbol, f"{symbol}.xlsx", b"data", symbol, None)

    results = list(iter_download_results(["GOOD1", "BAD", "GOOD2"], downloader))

    assert [result.symbol for result in results] == ["GOOD1", "BAD", "GOOD2"]
    assert [result.symbol for result in results if result.content] == [
        "GOOD1",
        "GOOD2",
    ]


def test_download_queue_stops_at_access_control_failure():
    def downloader(symbol):
        if symbol == "BLOCKED":
            return DownloadResult(
                symbol, None, None, None, "access denied", True
            )
        return DownloadResult(symbol, f"{symbol}.xlsx", b"data", symbol, None)

    results = list(
        iter_download_results(["FIRST", "BLOCKED", "NOT-ATTEMPTED"], downloader)
    )

    assert [result.symbol for result in results] == ["FIRST", "BLOCKED"]
    assert results[0].content == b"data"
