from __future__ import annotations

import hashlib
import queue
import re
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit


_SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9&._-]{0,49}$")
_EXPORT_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
_MIN_DELAY_SECONDS = 3
_MAX_DELAY_SECONDS = 30


@dataclass(frozen=True)
class SymbolQueue:
    symbols: tuple[str, ...]
    duplicates: tuple[str, ...]


@dataclass(frozen=True)
class DownloadResult:
    symbol: str
    filename: str | None
    content: bytes | None
    content_sha256: str | None
    error: str | None
    stop_queue: bool = False


def iter_download_results(
    symbols: Sequence[str],
    download_one: Callable[[str], DownloadResult],
) -> Iterator[DownloadResult]:
    """Yield every result and stop only when a safety condition requires it."""
    for symbol in symbols:
        result = download_one(symbol)
        yield result
        if result.stop_queue:
            break


@dataclass
class _BrowserCommand:
    action: str
    symbol: str = ""
    delay_seconds: int = 3
    completed: threading.Event = field(default_factory=threading.Event)
    result: DownloadResult | None = None


def parse_symbol_queue(text: str, max_symbols: int = 100) -> SymbolQueue:
    """Validate and de-duplicate one Screener company symbol per line."""
    if isinstance(max_symbols, bool) or not isinstance(max_symbols, int) or max_symbols < 1:
        raise ValueError("The queue limit must be a positive whole number.")

    symbols: list[str] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    for raw_symbol in text.splitlines():
        symbol = raw_symbol.strip().upper()
        if not symbol:
            continue
        if not _SYMBOL_PATTERN.fullmatch(symbol):
            raise ValueError(
                f"Invalid Screener company symbol {raw_symbol.strip()!r}. "
                "Use letters, numbers, ampersands, dots, underscores, and hyphens only."
            )
        if symbol in seen:
            duplicates.append(symbol)
            continue
        seen.add(symbol)
        symbols.append(symbol)

    if len(symbols) > max_symbols:
        raise ValueError(f"The queue is limited to {max_symbols} unique symbols.")
    if not symbols:
        raise ValueError("Enter at least one Screener company symbol.")
    return SymbolQueue(tuple(symbols), tuple(duplicates))


def validate_delay(delay_seconds: int) -> int:
    if (
        isinstance(delay_seconds, bool)
        or not isinstance(delay_seconds, int)
        or not _MIN_DELAY_SECONDS <= delay_seconds <= _MAX_DELAY_SECONDS
    ):
        raise ValueError(
            f"Choose a delay between {_MIN_DELAY_SECONDS} and "
            f"{_MAX_DELAY_SECONDS} seconds."
        )
    return delay_seconds


def _safe_download_filename(symbol: str, suggested_filename: str) -> str | None:
    basename = Path(suggested_filename).name
    suffix = Path(basename).suffix.lower()
    if suffix not in {".xlsx", ".csv"}:
        return None
    stem = Path(basename).stem
    safe_stem = _EXPORT_FILENAME_PATTERN.sub("_", stem).strip("._-") or "export"
    return f"{symbol}__{safe_stem}{suffix}"


class ScreenerBrowserSession:
    """Temporary headed browser session; authentication is never persisted."""

    def __init__(self) -> None:
        self._commands: queue.Queue[_BrowserCommand] = queue.Queue()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._startup_error: str | None = None
        self._thread = threading.Thread(
            target=self._serve_browser,
            name="screener-browser-session",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=45):
            self.close()
            raise RuntimeError("The temporary browser did not start in time.")
        if self._startup_error:
            raise RuntimeError(self._startup_error)

    @staticmethod
    def _login_redirected(page: Any) -> bool:
        path = urlsplit(page.url).path.casefold().strip("/")
        return path in {"login", "signin", "sign-in", "accounts/login"}

    @staticmethod
    def _visible_export_control(page: Any) -> Any | None:
        controls = (
            page.get_by_role("button", name="Export to Excel", exact=True),
            page.get_by_role("link", name="Export to Excel", exact=True),
        )
        visible: list[Any] = []
        for locator in controls:
            for index in range(locator.count()):
                candidate = locator.nth(index)
                if candidate.is_visible() and candidate.is_enabled():
                    visible.append(candidate)
        return visible[0] if len(visible) == 1 else None

    @classmethod
    def _download_one(
        cls,
        page: Any,
        symbol: str,
        delay_seconds: int,
        timeout_error: type[Exception],
        browser_error: type[Exception],
    ) -> DownloadResult:
        try:
            page.wait_for_timeout(delay_seconds * 1000)
            response = page.goto(
                f"https://www.screener.in/company/{quote(symbol)}/",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            if cls._login_redirected(page):
                return DownloadResult(
                    symbol,
                    None,
                    None,
                    None,
                    "The page redirected to login. Sign in manually and restart the queue.",
                    True,
                )
            if response is not None and response.status in {401, 403, 429}:
                return DownloadResult(
                    symbol,
                    None,
                    None,
                    None,
                    f"The company page returned HTTP {response.status}; queue stopped.",
                    True,
                )
            if response is not None and response.status == 404:
                return DownloadResult(
                    symbol,
                    None,
                    None,
                    None,
                    "The company page returned HTTP 404; this symbol failed, "
                    "but the queue can continue.",
                    False,
                )
            if response is not None and response.status >= 400:
                return DownloadResult(
                    symbol,
                    None,
                    None,
                    None,
                    f"The company page returned HTTP {response.status}; queue stopped.",
                    True,
                )
            verification_text = page.get_by_text(
                re.compile(r"captcha|verify you are human", re.IGNORECASE)
            )
            if any(
                verification_text.nth(index).is_visible()
                for index in range(verification_text.count())
            ):
                return DownloadResult(
                    symbol,
                    None,
                    None,
                    None,
                    "A CAPTCHA or human-verification page was detected; queue stopped.",
                    True,
                )

            control = cls._visible_export_control(page)
            if control is None:
                return DownloadResult(
                    symbol,
                    None,
                    None,
                    None,
                    "Exactly one visible Export to Excel control was not found. "
                    "The page may require login or its layout may have changed; "
                    "queue stopped.",
                    True,
                )

            with page.expect_download(timeout=20_000) as download_info:
                control.click(timeout=5_000)
            download = download_info.value
            filename = _safe_download_filename(symbol, download.suggested_filename)
            if filename is None:
                return DownloadResult(
                    symbol,
                    None,
                    None,
                    None,
                    "The export did not produce an .xlsx or .csv file; queue stopped.",
                    True,
                )
            download_path = download.path()
            if download_path is None:
                return DownloadResult(
                    symbol,
                    None,
                    None,
                    None,
                    "The browser did not provide a completed download file; queue stopped.",
                    True,
                )
            path = Path(download_path)
            if path.stat().st_size > _MAX_DOWNLOAD_BYTES:
                return DownloadResult(
                    symbol,
                    None,
                    None,
                    None,
                    "The export exceeded the 50 MB safety limit; queue stopped.",
                    True,
                )
            content = path.read_bytes()
            return DownloadResult(
                symbol,
                filename,
                content,
                hashlib.sha256(content).hexdigest(),
                None,
            )
        except timeout_error:
            return DownloadResult(
                symbol,
                None,
                None,
                None,
                "The page or export timed out. The queue stopped; use manual import "
                "if the export is available.",
                True,
            )
        except browser_error:
            return DownloadResult(
                symbol,
                None,
                None,
                None,
                "The browser session failed or was closed. The queue stopped.",
                True,
            )
        except OSError:
            return DownloadResult(
                symbol,
                None,
                None,
                None,
                "The completed download could not be read. The queue stopped.",
                True,
            )

    def _serve_browser(self) -> None:
        playwright = None
        browser = None
        context = None
        try:
            from playwright.sync_api import (
                Error as PlaywrightError,
                TimeoutError as PlaywrightTimeoutError,
                sync_playwright,
            )
        except ImportError:
            self._startup_error = (
                "Browser support is not installed. Install the project "
                "dependencies and run `python -m playwright install chromium`."
            )
            self._ready.set()
            self._closed.set()
            return

        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            page.goto(
                "https://www.screener.in/",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
        except (PlaywrightError, OSError):
            self._startup_error = (
                "Could not open the temporary browser. Check the browser "
                "installation and network connection."
            )
            self._ready.set()
            self._close_resources(context, browser, playwright, PlaywrightError)
            self._closed.set()
            return

        self._ready.set()
        try:
            while True:
                command = self._commands.get()
                if command.action == "close":
                    command.completed.set()
                    break
                try:
                    command.result = self._download_one(
                        page,
                        command.symbol,
                        command.delay_seconds,
                        PlaywrightTimeoutError,
                        PlaywrightError,
                    )
                finally:
                    command.completed.set()
        finally:
            self._close_resources(context, browser, playwright, PlaywrightError)
            self._closed.set()

    @staticmethod
    def _close_resources(
        context: Any,
        browser: Any,
        playwright: Any,
        browser_error: type[Exception],
    ) -> None:
        for resource in (context, browser):
            if resource is not None:
                try:
                    resource.close()
                except browser_error:
                    pass
        if playwright is not None:
            try:
                playwright.stop()
            except browser_error:
                pass

    def download_one(self, symbol: str, delay_seconds: int = 3) -> DownloadResult:
        """Queue one company export to run on the browser's owning thread."""
        delay_seconds = validate_delay(delay_seconds)
        symbol = symbol.strip().upper()
        if not _SYMBOL_PATTERN.fullmatch(symbol):
            raise ValueError(f"Invalid Screener company symbol: {symbol!r}.")
        command = _BrowserCommand("download", symbol, delay_seconds)
        if self._closed.is_set():
            return DownloadResult(
                symbol, None, None, None, "The browser session is closed.", True
            )
        self._commands.put(command)
        if not command.completed.wait(timeout=120):
            return DownloadResult(
                symbol,
                None,
                None,
                None,
                "The browser worker timed out. The queue stopped.",
                True,
            )
        return command.result or DownloadResult(
            symbol,
            None,
            None,
            None,
            "The browser worker returned no export result. The queue stopped.",
            True,
        )

    def close(self) -> None:
        if self._closed.is_set():
            return
        command = _BrowserCommand("close")
        self._commands.put(command)
        command.completed.wait(timeout=30)
        self._thread.join(timeout=30)
