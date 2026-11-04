# Fincrux Saved-Response Data Validation

**Reviewed:** 2026-11-03  
**Scope:** Offline review of the existing `HDFCBANK.json`, `MARUTI.json`, and
`CIPLA.json` files in this folder, plus the official Fincrux documentation and
pricing pages available on the review date. **No API requests were made.**
No CAGR or investment rating was calculated.

## Executive recommendation

**Suitable only with caveats; not ready for production financial analysis as
received.** The saved responses have useful 12-period annual histories, quarterly
results, balance sheets, and cash flows. However, the API response and its
published financials documentation do not establish reporting basis, statement
currency/scale, EPS corporate-action adjustment policy, restatement history, or
accounting-standard metadata. The reported HDFC Bank series also crosses a
material merger boundary. Resolve these items with Fincrux and validate the
provider's source/period semantics before calculating growth or normalizing
financials.

## 1. Reporting basis

- The three saved JSON responses were searched for `consolidated`,
  `standalone`, and reporting-basis metadata in both keys and values. No
  indicators were found. The company description and statement rows do not
  identify a basis either.
- The [Fincrux Company Financials documentation](https://fincrux.org/docs/company-financials)
  documents `api_key` and optional `force_update` request parameters. It does
  **not** document a `consolidated`, `standalone`, or other reporting-basis
  selector.
- **Conclusion for HDFCBANK, MARUTI, and CIPLA: reporting basis not identified.**
  Do not label or combine the series as consolidated or standalone without
  vendor confirmation.

## 2. Units and currency

The saved responses contain no unit/currency metadata, and the Financials API
documentation describes statement arrays but does not specify their amount
units.

| Statement/value | What the response shows | Validation conclusion |
|---|---|---|
| Revenue/sales | Numeric values under `Revenue` or `Sales` | **Unit and currency unknown**; do not assume INR crore. |
| Net profit | Numeric values under `Net Profit` | **Unit and currency unknown**; do not assume INR crore. |
| EPS | Row label is `EPS in Rs` | Label suggests rupees per share, but formal documentation and adjustment basis are absent. Treat as **provisional, vendor confirmation required**. |
| Balance sheet | Amount rows with no unit annotation | **Unit and currency unknown**. |
| Cash flow | Amount rows with no unit annotation | **Unit and currency unknown**. |

Values in the coverage report and raw files are preserved as returned. No unit
conversion or imputation has been applied.

## 3. Financial data mapping and period meaning

All three responses use a category-by-period matrix, not arrays of financial
record objects:

- Headers are in `data.<statement>[0]`; the first header cell is `Category`,
  followed by period labels.
- Statement rows are in `data.<statement>[1:]`; the first cell of each row is
  its category label and remaining cells align positionally with the header.
- A value is therefore at
  `data.<statement>[row_index][period_column_index]`, where the row is located
  by its first-cell category and the column by its header. `TTM` is not an
  annual observation.

| Statement/value | Exact response path / row selector |
|---|---|
| Annual revenue, HDFCBANK | `data.profit_and_loss[row where row[0] == "Revenue"][column where header == "Mar YYYY"]` |
| Annual revenue, MARUTI and CIPLA | `data.profit_and_loss[row where row[0] == "Sales"][column where header == "Mar YYYY"]` |
| Annual net profit, all three | `data.profit_and_loss[row where row[0] == "Net Profit"][column where header == "Mar YYYY"]` |
| Annual EPS, all three | `data.profit_and_loss[row where row[0] == "EPS in Rs"][column where header == "Mar YYYY"]` |
| Balance sheet | `data.balance_sheet`; dated columns are the first row |
| Cash flow | `data.cash_flows`; dated columns are the first row |
| Quarterly results | `data.quaterly_results`; this is the exact spelling returned by the API, rather than the documentation's `quarterly_results` |

Balance-sheet row labels found:

| Field | HDFCBANK | MARUTI | CIPLA |
|---|---|---|---|
| Equity capital | `Equity Capital` | `Equity Capital` | `Equity Capital` |
| Reserves | `Reserves` | `Reserves` | `Reserves` |
| Borrowings | `Borrowing` (singular) | `Borrowings` | `Borrowings` |
| Deposits | `Deposits` | Not present | Not present |
| Total liabilities | `Total Liabilities` | `Total Liabilities` | `Total Liabilities` |

For each field above, its value is the matching row in `data.balance_sheet` at
the column whose header is the desired `Mar YYYY` or other reported date. The
exact order of rows can vary by company; match by row label, not fixed array
index.

The saved headers run from `Mar 2015` through `Mar 2026`; the annual P&L also
contains a `TTM` column. The date labels are month/year, not explicit fiscal-year
identifiers. Given Indian reporting practice, `Mar YYYY` appears to represent
the financial year ended in March, rather than a calendar-year total, but the
API docs do not state the financial-year convention. Confirm the period
definition, fiscal-year start/end, and treatment of TTM with Fincrux before
using year-to-year comparisons.

## 4. Historical comparability and accounting metadata

### HDFC Bank FY2024 revenue row

The saved HDFCBANK P&L has `Revenue` of **161,586** at `Mar 2023` and **258,341**
at `Mar 2024` (provider-returned units are unknown). That is an increase of
96,755 in the returned values. It is not safe to treat this as like-for-like
organic growth.

HDFC Ltd's amalgamation into HDFC Bank became effective **1 July 2023**. FY2024
therefore spans a period in which the merged business is included after the
effective date; FY2023 predates the merger. The merger is a material
comparability break and is a plausible contributor to the jump. These saved
rows alone cannot isolate the merger contribution or establish whether the
values are standalone or consolidated. Reconcile the provider series to HDFC
Bank's audited FY2023-24 results and obtain any pro-forma/comparable prior-period
basis before interpreting the change. HDFC Bank's [official financial results
page](https://www.hdfc.bank.in/about-us/investor-relations/financial-results)
and [annual-report index](https://www.hdfc.bank.in/about-us/investor-relations/annual-reports)
are the primary documents to use for that reconciliation.

### EPS adjustments, restatements, and accounting standards

- None of the saved JSON files identifies whether historical EPS is adjusted
  for stock splits, bonus issues, rights issues, or other corporate actions.
- The Financials documentation does not state whether EPS is adjusted or how
  adjustments are applied. Fincrux publishes a separate
  [Corporate Actions endpoint](https://fincrux.org/docs/company-corporate-actions)
  for dividend, bonus, split, and rights events, but that documentation does
  not say that the Financials endpoint's historical EPS is adjusted against
  those events.
- **EPS adjustment status is unknown for HDFCBANK, MARUTI, and CIPLA.** Do not
  mix it with prices or other share-count-based metrics until confirmed.
- A metadata scan found no restatement/version history, accounting-standard
  label (for example Ind AS/IFRS), or accounting-policy field in any of the
  saved payloads. The Financials documentation does not document such fields.
  Their presence/absence in the source statements and any restatement policy
  need Fincrux confirmation.

## 5. Debt and equity interpretation

### MARUTI and CIPLA

Both responses include `Borrowings`, `Equity Capital`, and `Reserves`; a
conventional **book debt-to-equity proxy is conceptually calculable** as
interest-bearing borrowings divided by equity capital plus reserves, provided
that:

1. Fincrux confirms units and reporting basis are consistent across these rows
   and years.
2. `Borrowings` is confirmed to mean interest-bearing debt and its scope
   (current/non-current, lease liabilities, and other debt) is documented.
3. Equity is consistently defined, including treatment of minority interests
   if the series is consolidated.
4. The selected balance-sheet date and period are aligned.

The current payload alone does not satisfy those checks. `Total Liabilities`
must not be substituted for debt. No debt/equity values have been calculated
in this validation.

### HDFC Bank

Do not apply the industrial-company debt/equity formula blindly. Deposits are a
core funding source and are explicitly present alongside borrowings and total
liabilities; treating all liabilities as debt obscures how a bank operates.
Prefer bank-specific, consistently sourced indicators, including:

- CET1 and total capital adequacy ratios;
- gross and net NPA ratios and provision coverage;
- net interest margin (NIM);
- liquidity coverage ratio (LCR);
- credit-to-deposit ratio; and
- CASA ratio, where useful.

These are recommendations for subsequent validated data work; this report
does not calculate them.

## 6. Current Fincrux pricing, limits, and other restrictions

The [official Fincrux pricing page](https://fincrux.org/pricing) and
[Financials endpoint documentation](https://fincrux.org/docs/company-financials)
were re-read on 2026-11-03. Rates are account-level, not per API key. All plans
are described as having the same dataset/endpoints; plans differ by throughput
and forced-refresh allowance.

| Plan | Published price | Normal request limits documented | Forced-refresh limit |
|---|---:|---|---|
| Hobby | Free (₹0/month) | 5 requests/day; per-minute limit **not specified** | Not included |
| Plus | ₹200/month | 10 requests/minute; daily normal-request limit **not specified** | 5/day |
| Pro | ₹1,000/month | 60 requests/minute; daily normal-request limit **not specified** | 25/day |

Additional published details:

- Pricing says rate limits apply to the **account**, not to each API key.
- Pricing describes access to 3,000+ listed companies and the same financial
  statements/endpoints on all plans.
- The Financials endpoint docs list `api_key` as required and `force_update`
  as optional. Forced-refresh limits above are not the same as ordinary
  request limits.
- No price for overages, separate burst/concurrency limits, uptime SLA,
  response-retention guarantee, change-notification policy, or plan-specific
  data-quality guarantees were found in the cited pages. These are **not
  specified there**, not assumed to be unlimited.

## 7. Unresolved questions for Fincrux support

1. Can the Financials endpoint return an explicit standalone/consolidated
   selector or field? What basis is used for each of these three symbols?
2. What currency and scale apply to every statement amount (for example INR,
   ₹ crore, ₹ lakh)? Are units guaranteed consistent across companies and
   across all statement types? Does `EPS in Rs` mean unadjusted INR per share?
3. Do `Mar YYYY` headers represent Indian financial years ended 31 March?
   How should users interpret `TTM`, and are annual statements fiscal-year or
   calendar-year data?
4. Is historical EPS adjusted for splits, bonus issues, rights issues, and
   other corporate actions for HDFCBANK, MARUTI, and CIPLA? If so, what is the
   adjustment policy and effective history?
5. What source is used for financials, and what accounting standards and
   restatement/version-history policies apply? Can restatements be detected
   from the API?
6. For HDFC Bank, how is the HDFC Ltd merger reflected in FY2024 and the
   comparative history? Is a pro-forma, merged-entity-comparable history
   available? Which reporting basis does the saved revenue series use?
7. What precisely is included in `Borrowings` for industrial issuers, including
   lease liabilities and current maturities? Are liability/equity definitions
   consistent with the company's source filings?
8. What are the Plus/Pro daily normal request caps, Hobby per-minute limit,
   burst/concurrency behavior, overage/429 handling, and any production SLA or
   retention guarantee? Are the forced-update allowances per account per
   calendar day, and does a forced update also consume the ordinary request
   quota?

## Sources

- Fincrux, [Pricing](https://fincrux.org/pricing) (checked 2026-11-03).
- Fincrux, [Company Financials endpoint](https://fincrux.org/docs/company-financials)
  (checked 2026-11-03).
- Fincrux, [Corporate Actions endpoint](https://fincrux.org/docs/company-corporate-actions)
  (checked 2026-11-03).
- HDFC Bank, [Financial Results](https://www.hdfc.bank.in/about-us/investor-relations/financial-results).
- HDFC Bank, [Annual Reports](https://www.hdfc.bank.in/about-us/investor-relations/annual-reports).
- Local evidence: `HDFCBANK.json`, `MARUTI.json`, and `CIPLA.json` in this
  directory. These were read offline; no API calls were made during this review.
