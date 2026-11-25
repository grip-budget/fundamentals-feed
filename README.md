# fundamentals-feed

An automated data pipeline that compiles fundamental financial metrics for U.S. exchange-listed equities into a clean, single-file CSV (`fundamentals_import.csv`). Built to feed a quantitative small-cap value and profitability screening model in Google Sheets.

## How It Works

A GitHub Actions workflow runs `fetch_fundamentals.py` every **Sunday at 23:00 UTC** (and can be triggered manually anytime from the **Actions** tab).

1. **Company Metadata:** Pulls tickers, GICS-mapped sectors, snapshot market capitalizations, and IPO years from the NASDAQ Screener API.
2. **Financial Statements:** Pulls bulk balance-sheet, cash-flow, and income-statement figures across all U.S. reporting companies using the **SEC EDGAR XBRL Frames API** and maps them via `company_tickers.json`.
3. **Output:** Writes a sorted `fundamentals_import.csv` and commits any changes back to the repository so downstream tools (such as Google Sheets via Apps Script) can ingest the raw CSV URL automatically.

## Output Schema (`fundamentals_import.csv`)

| Column | Units / Format | Source & Calculation |
| :--- | :--- | :--- |
| `Ticker` | String | Uppercase exchange ticker symbol |
| `Sector` | String | NASDAQ sector mapped to standard GICS sector names |
| `Snapshot Market Cap ($M)` | USD Millions | Snapshot market capitalization from NASDAQ |
| `Adjusted Book Value of Equity ($M)` | USD Millions | Most recent quarterly `StockholdersEquity` (with fallbacks) via SEC XBRL |
| `Adjusted Operating Cash Flow ($M)` | USD Millions | Most recent full-year `NetCashProvidedByUsedInOperatingActivities` via SEC XBRL |
| `YoY Total Asset Growth (%)` | Decimal (`0.12` = 12%) | Year-over-year change in quarterly `Assets` (same quarter prior year) |
| `Net Share Issuance (%)` | Decimal (`-0.05` = -5%) | Year-over-year change in quarterly `EntityCommonStockSharesOutstanding` |
| `Interest Coverage Ratio (x)` | Multiple | Annual Operating Income (`EBIT`) ÷ Annual `InterestExpense` (capped at `-99x` to `99x`) |
| `IPO Date` | `YYYY-MM-DD` | Derived from NASDAQ `ipoyear` (`YYYY-07-01`); defaults to `2000-01-01` for seasoned legacy SEC filers with blank IPO years |

## Repository Structure

```text
.
├── .github/
│   └── workflows/
│       └── update.yml        # Weekly GitHub Actions schedule + manual dispatch
├── fetch_fundamentals.py     # SEC EDGAR + NASDAQ data fetcher and CSV builder
└── fundamentals_import.csv   # Auto-generated output file
