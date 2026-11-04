# StocksVisualizer
My stocks Dashboard
# StockVisualizer

StockVisualizer is a modular Streamlit dashboard for exploring an Indian-stock
watchlist. It uses SQLite for local storage, Pandas/NumPy for data handling and
calculations, and Plotly for charts.

> **Sample-data notice:** All prices, financial statements, and derived metrics
> included at first launch are illustrative synthetic data. They are not real
> market data, are not refreshed from an exchange or data provider, and must not
> be used to make investment decisions.

## Features

- An initialized watchlist containing `HDFCBANK.NS`, `MARUTI.NS`, and
  `CIPLA.NS`.
- SQLite database initialized and seeded on first run.
- A watchlist-first home page with a compact financial metrics table.
- Revenue CAGR, net-profit CAGR, normalized core P/E, expected growth,
  cumulative EPS payback, and an educational screening rating, each in its own
  calculation module.
- Maximum-available (up to 9-year) and separate 4-year revenue and net-profit CAGRs, reported P/E,
  normalized Core P/E, and EPS-payback growth sensitivity analysis.
- A synthetic financial-history chart for the original sample-data workspace.
- A separate **Screener imports** workspace for manually downloaded Excel and
  compatible Data Sheet CSV files, without changing the sample-data workflow.
- Persistent SQLite watchlist membership, searchable/sortable watchlist rows,
  per-stock selection, and selected-only bulk download, refresh, remove, and
  snapshot actions.
- Permanent normalized import snapshots, metric-level anomaly checks, snapshot
  comparisons, and Excel export of saved analysis.
- Unit tests for calculation edge cases and database initialization.

### Watchlist, bulk actions, and metrics

The home page is the persistent watchlist. **Add stock** accepts one or more NSE
symbols (including `&`, dots, and hyphens), then opens the existing assisted
Screener workflow. Sign in manually; StockVisualizer never requests or stores
credentials. The export is previewed and ticker-confirmed before import, and
successfully imported stocks are added to the watchlist. Select individual
rows or all rows and choose **Refresh selected** to queue another export. The
usual preview, duplicate handling, and explicit import confirmation still
apply.

The watchlist displays price, source, market cap, P/E, Rating, growth, EPS,
payback, Debt/Equity, anomaly status, and a Screener company link (plus a
selection control). CAGR periods are
shown dynamically and capped at nine years; 4Y CAGRs require five consecutive
annual observations. Market capitalization is taken from the export when
present, otherwise derived from its price and adjusted shares. P/E is shown
as spreadsheet price divided by latest EPS before a live fetch. **Fetch Live
Data** queries Yahoo Finance for the `.NS` ticker and stores its price, market
capitalization, trailing P/E, trailing EPS, and Debt/Equity separately from Screener
financial snapshots. Yahoo market capitalization is converted from INR to
crore for display. A cached Yahoo value takes precedence; a missing field in a
partial Yahoo response stays unavailable rather than falling back to an older
spreadsheet value. Successful Screener reimport clears that stock's Yahoo
quote cache. **Exp Growth** is calculated from available revenue and net-profit
CAGRs, but can be edited per stock as a decimal fraction (for example, `0.15`
means 15%). Manual values are stored in SQLite and drive the EPS payback
calculation until that stock is reimported; clearing the cell restores
calculated growth. Yahoo `debtToEquity` is returned as a percentage and
normalized to a ratio for display (for example, 75 becomes 0.75x). When Yahoo
omits that field, Debt/Equity is derived from Yahoo's latest annual balance
sheet as total debt divided by stockholders' equity. It remains unavailable if
the provider omits the required balance-sheet values. Financial anomaly status reflects the
saved analysis snapshot.

The **Source** column contains only `Yahoo` or `Screener`. Rating uses the
displayed P/E and Expected Growth (converted from decimal fraction to percent)
to calculate fair P/E as `0.096 × growth_percent²`, then compares actual P/E
with fair P/E. Its scorecard labels are Strong Buy (Deep Value), Good Buy
(Undervalued), Fair Value (Hold / Neutral), Slightly Overvalued, or Overvalued
(Avoid / Sell). Rating is unavailable if P/E or Expected Growth is missing,
non-finite, zero, or negative.

Yahoo price fields are stored separately and do not alter historical Screener
observations or saved analysis snapshots. Prices in sample data remain
illustrative and are never presented as market quotes. Yahoo responses can be
partial or delayed; quote timestamps and freshness remain available in the
underlying row data. Exchange selection is based on the `.NS` ticker mapping,
which is not independently verified by the application.

## Run locally

From this directory, create and activate a virtual environment, then install
the dependencies:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start the dashboard:

```powershell
streamlit run app.py
```

The application creates `data\stockvisualizer.db` and seeds it with sample
records on first launch. Set `STOCKVISUALIZER_DB` to use a different SQLite
file path.

Run the tests:

```powershell
python -m pytest
```

## Import Screener exports

The **Screener imports** page accepts multiple `.xlsx` files and CSV files that
use the Screener `Data Sheet` grid layout. The supplied version 2.1 workbooks
contain `Profit & Loss`, `Quarters`, `Balance Sheet`, `Cash Flow`,
`Customization`, and `Data Sheet` sheets. The importer reads the raw `Data
Sheet`; formula-only display tabs are not treated as source values. CSV files
with a different shape are reported as unsupported rather than guessed. No
Screener API calls, private endpoints, or access-control bypasses are used.

An optional **Assisted browser downloads** section can open a temporary
Playwright Chromium browser for manual sign-in, then visit up to 100 unique
Screener company symbols sequentially and click the visible **Export to Excel**
control. Browser-assisted downloads are intended only for accounts and uses
permitted by Screener. The browser has an in-memory context: StockVisualizer
does not read or store passwords, persist browser profiles/cookies, or retain
login state after the browser is closed. CAPTCHA, login redirects, HTTP
restrictions, timeouts, missing/ambiguous export controls, and unexpected
formats stop the queue; they are not retried or bypassed. A minimum three-second
delay is enforced between company pages. This local browser opens on the machine
running Streamlit, so this workflow is not suitable for a remotely hosted app.

Install the browser runtime once after installing the Python requirements:

```powershell
python -m playwright install chromium
```

In the import page, enter one Screener company symbol per line, open the
temporary browser, sign in manually, and confirm before starting the queue.
Completed `.xlsx`/`.csv` downloads are held in the current Streamlit session's
memory, parsed by the existing importer, and shown in its normal preview and
mapping-confirmation flow. Nothing is committed until **Import selected files**
is clicked. Identical queued symbols are ignored, identical file hashes are
skipped, and failed/unsupported exports are reported. Close the temporary
browser when finished. Bulk manual file upload remains the fallback.

Before saving, the page previews parsed observations, periods, missing metrics,
and warnings. Since exports provide a company name but no exchange ticker, an
operator must confirm the ticker before importing. Exact content hashes detect
previous imports and offer skip or re-import; re-import always creates another
snapshot and never overwrites prior analysis. Original files are not copied.
SQLite retains the source filename, checksum, import timestamp, parser version,
confirmed ticker mapping, normalized observations (including nulls and
derived-value provenance), analysis, anomaly findings, and thresholds. Deleting
the downloaded files after import does not delete these saved records.

The inspected exports do not contain explicit unit metadata. The user-confirmed
import convention is **financial statement amounts in INR crore**, with EPS,
face value, and share price in INR, share counts in crore shares, and ratios in
their stated percentage/multiple units. The reporting basis is stored as
**Unknown** unless independently confirmed; that metadata warning is displayed
separately and does not by itself change financial anomaly status.

Screener-reported EPS is retained and preferred when available. Derived EPS is
kept in a separate field and used only when reported EPS is unavailable and
adjusted share count is valid; it is labelled with its derivation. The supplied
exports have no reported EPS values in their raw Data Sheets, so their EPS is
derived from net profit divided by adjusted shares. Reported P/E is calculated
from the export's current price and latest EPS. It is labelled **Reported P/E**
only when that EPS is Screener-reported; if EPS is derived, the resulting
multiple is labelled separately as **P/E (derived EPS)** and reported P/E is
unavailable. Normalized Core P/E remains unavailable without sufficient historical exceptional-item and
cyclical-margin evidence. Quarterly operating margin is retained only as a
labelled derived ratio when quarterly operating profit and revenue are present;
formula-only ratios are not imported as reported facts.

### Anomaly checks

For positive comparable annual values, each YoY growth is compared with up to
five **prior** valid growth observations. The baseline is the median; the
robust scale is `1.4826 × MAD`, where `MAD` is the median absolute deviation.
A deviation is flagged beyond `max(3 × robust scale, 0.02)`. The default
zero-MAD tolerance of `0.02` is a two-percentage-point growth/log-difference
floor intended to suppress rounding noise. Three or four prior observations
produce provisional comparisons; fewer than three cannot establish a baseline.
The lookback, minimum history, cutoff, tolerance, and annual period-date
tolerance are configurable before import and saved with each snapshot. These are screening
heuristics, not statistical guarantees.

Revenue and profit growth are not flagged merely for exceeding 40%. Loss-to-
profit and profit-to-loss transitions are reported separately instead of being
expressed as misleading percentage growth. EPS divergence is:

```text
ln(current EPS / previous EPS) - ln(current net profit / previous net profit)
```

It is checked against its own rolling median/MAD baseline and is a manual-review
signal, not an assertion of incorrect data. Share-count changes, recorded bonus
shares, changed face value, duplicate annual metrics, missing years, non-finite
values, zero/negative denominators, and unusual annual period intervals receive
metric-level explanations. Unknown reporting basis is metadata uncertainty,
not a financial anomaly. Financial status is Green when no significant checks
fire, Orange for reviewable anomalies or insufficient history, and Red for
critical invalid data or duplicate annual records.

The supplied example exports contain ten annual observations (March 2017
through March 2026). Their maximum-available CAGRs are therefore labelled 9Y,
not 10Y. The importer never fills missing years or metrics with zero. Saved snapshots can be compared with each other or
with the latest saved import for that ticker, and their analysis and normalized
records can be exported to Excel.

## Fincrux data-coverage test

The optional one-off coverage test is separate from the sample-data dashboard.
It reads `FINCRUX_API_KEY` from the process environment or project `.env` file
and fetches HDFCBANK, MARUTI, and CIPLA financials once each. It does not send
`force_update`, calculate CAGR, or change the dashboard data source.

```powershell
python scripts\fincrux_coverage_test.py
```

Raw API response bodies and `coverage_report.md` are saved under
`data\fincrux_test\`. To regenerate the report from those saved responses
without making any API requests:

```powershell
python scripts\fincrux_coverage_test.py --analyze-only
```

## Project structure

```text
app.py
scripts/
  fincrux_coverage_test.py  # Explicit one-off historical coverage test
stockvisualizer/
  calculations/
    anomaly_detection.py  # Provider-independent completeness and growth checks
  dashboard.py            # Existing sample pages plus imported-data navigation
  database.py             # Sample schema and immutable Screener snapshot storage
  screener_analysis.py    # Provider-independent metrics and saved analysis
  screener_import.py      # Screener workbook / compatible Data Sheet CSV parser
  screener_pages.py       # Import preview, snapshots, comparison, and export
  stock_data.py           # Sample data access and DataFrame preparation
tests/
```

## Metric definitions and assumptions

- **Revenue / net-profit CAGR:** calculated independently from the latest
  consecutive annual history, up to 10 CAGR years (11 observations). At least
  three observations are required; the displayed period is observations minus
  one (for example, ten observations produce a 9Y CAGR). A missing fiscal year
  ends the usable suffix; gaps are never bridged. The starting and ending
  values must be positive. The 4Y metric remains separate and requires five
  consecutive annual observations.
- **Expected growth:** the arithmetic mean of valid maximum-history and
  separate 4Y revenue and net-profit CAGRs. An identical 4Y value is not
  counted twice when the maximum-history CAGR itself covers four years. The
  dashboard, detail pages, and Excel exports identify each contributing metric
  and its actual period.
- The sample database contains five years, so the maximum-history metric is
  labelled 4Y; available 4Y values are included in Expected Growth.
- **Reported P/E:** sample market price divided by the latest reported EPS.
  Zero or negative EPS yields `N/A`.
- **Normalized Core P/E:** market price divided by the average of historical
  core EPS values adjusted using documented financial statements. The current
  sample dataset has reported EPS only, not the historical exceptional-item or
  margin data needed to make those adjustments; therefore the dashboard does
  not invent normalized earnings and shows this multiple as unavailable. A
  sound normalization should identify exceptional income and expenses in each
  period and assess cyclical margins against historical conditions before
  deriving core earnings.
- **Cumulative EPS payback:** Year 1 EPS is current EPS; each later year grows
  by the assumed rate. Annual and cumulative EPS are reported until cumulative
  EPS first reaches the sample share price or the 30-year horizon ends. The
  first full year is the first integer year to cross the price. Fractional
  payback linearly interpolates within that final year, assuming EPS accrues
  evenly during it. Sensitivity scenarios use 8%, 10%, 12%, and 15% EPS growth;
  these rates are assumptions, not forecasts.
- **Stock rating:** a transparent rule-based screen using expected growth,
  normalized Core P/E, and payback. It reports `Insufficient data` when a
  required valuation or growth input is unavailable. It is an educational
  label, not a recommendation.

This project is for demonstration and educational use only.
