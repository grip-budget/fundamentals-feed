import csv
import datetime
import os
import time
import requests

# SEC EDGAR strictly requires a descriptive User-Agent with a contact email
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "AVUVScreener your.email@example.com")
SEC_HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}

NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nasdaq.com/",
}

# Maps NASDAQ sector labels to standard GICS sectors used in your spreadsheet
SECTOR_MAP = {
    "Finance": "Financials",
    "Technology": "Information Technology",
    "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Staples": "Consumer Staples",
    "Health Care": "Health Care",
    "Energy": "Energy",
    "Industrials": "Industrials",
    "Basic Materials": "Materials",
    "Utilities": "Utilities",
    "Telecommunications": "Communication Services",
    "Real Estate": "Real Estate",
    "Capital Goods": "Industrials",
    "Basic Industries": "Materials",
    "Consumer Services": "Consumer Discretionary",
    "Consumer Non-Durables": "Consumer Staples",
    "Consumer Durables": "Consumer Discretionary",
    "Public Utilities": "Utilities",
    "Transportation": "Industrials",
    "Miscellaneous": "Other",
}


def fetch_json(url, headers, sleep_sec=0.15):
    time.sleep(sleep_sec)
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Warning: request failed for {url}: {e}")
    return None


def fetch_nasdaq_screener():
    url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25&offset=0&download=true"
    data = fetch_json(url, NASDAQ_HEADERS, sleep_sec=0)
    if not data or "data" not in data or "rows" not in data["data"]:
        print("Warning: NASDAQ screener unavailable; continuing with SEC data only.")
        return {}

    out = {}
    for row in data["data"]["rows"]:
        ticker = (row.get("symbol") or "").strip().upper()
        if not ticker:
            continue
        raw_sector = (row.get("sector") or "").strip()
        sector = SECTOR_MAP.get(raw_sector, raw_sector)

        raw_mcap = str(row.get("marketCap") or "").replace(",", "").replace("$", "").strip()
        try:
            mcap_m = round(float(raw_mcap) / 1_000_000, 2) if raw_mcap else None
            if mcap_m is not None and mcap_m <= 0:
                mcap_m = None
        except ValueError:
            mcap_m = None

        raw_ipo = str(row.get("ipoyear") or "").strip()
        ipo_date = f"{raw_ipo}-07-01" if raw_ipo.isdigit() and len(raw_ipo) == 4 else ""

        out[ticker] = {
            "sector": sector,
            "mcap_m": mcap_m,
            "ipo_date": ipo_date,
        }
    print(f"Loaded {len(out)} tickers from NASDAQ Screener.")
    return out


def fetch_sec_cik_map():
    url = "https://www.sec.gov/files/company_tickers.json"
    data = fetch_json(url, SEC_HEADERS)
    if not data:
        raise RuntimeError("Failed to fetch SEC company_tickers.json. Check SEC_USER_AGENT.")
    ticker_to_cik = {}
    for entry in data.values():
        t = str(entry.get("ticker", "")).strip().upper()
        cik = int(entry["cik_str"])
        if t:
            ticker_to_cik[t] = cik
            if "-" in t:
                ticker_to_cik[t.replace("-", ".")] = cik
    print(f"Loaded {len(ticker_to_cik)} SEC ticker-to-CIK mappings.")
    return ticker_to_cik


def recent_quarter_frames(num_quarters=8):
    now = datetime.datetime.now(datetime.timezone.utc)
    y = now.year
    q = (now.month - 1) // 3 + 1
    frames = []
    for _ in range(num_quarters):
        frames.append((y, q))
        q -= 1
        if q == 0:
            q = 4
            y -= 1
    return frames


def fetch_frame(taxonomy, tag, unit, period):
    url = f"https://data.sec.gov/api/xbrl/frames/{taxonomy}/{tag}/{unit}/{period}.json"
    data = fetch_json(url, SEC_HEADERS)
    if not data or "data" not in data:
        return {}
    result = {}
    for item in data["data"]:
        cik = item.get("cik")
        val = item.get("val")
        if cik is not None and val is not None:
            result[int(cik)] = float(val)
    return result


def get_latest_and_prior_instant(tags_with_tax, unit, quarters):
    frame_cache = {}
    for y, q in quarters:
        period = f"CY{y}Q{q}I"
        merged = {}
        for tax, tag in tags_with_tax:
            vals = fetch_frame(tax, tag, unit, period)
            for cik, v in vals.items():
                if cik not in merged:
                    merged[cik] = v
        frame_cache[(y, q)] = merged

    latest = {}
    prior = {}
    for y, q in quarters[:4]:
        for cik, v in frame_cache.get((y, q), {}).items():
            if cik not in latest:
                latest[cik] = (v, (y, q))
                prev_v = frame_cache.get((y - 1, q), {}).get(cik)
                if prev_v is not None:
                    prior[cik] = prev_v
    return latest, prior


def get_latest_annual(tags_with_tax, unit):
    now_year = datetime.datetime.now(datetime.timezone.utc).year
    latest = {}
    for y in [now_year, now_year - 1, now_year - 2]:
        period = f"CY{y}"
        for tax, tag in tags_with_tax:
            vals = fetch_frame(tax, tag, unit, period)
            for cik, v in vals.items():
                if cik not in latest:
                    latest[cik] = v
    return latest


def main():
    nasdaq = fetch_nasdaq_screener()
    ticker_to_cik = fetch_sec_cik_map()
    quarters = recent_quarter_frames(8)

    print("Fetching SEC Book Equity...")
    equity_latest, _ = get_latest_and_prior_instant(
        [
            ("us-gaap", "StockholdersEquity"),
            ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
            ("us-gaap", "PartnersCapital"),
        ],
        "USD",
        quarters,
    )

    print("Fetching SEC Total Assets...")
    assets_latest, assets_prior = get_latest_and_prior_instant(
        [("us-gaap", "Assets")],
        "USD",
        quarters,
    )

    print("Fetching SEC Shares Outstanding...")
    shares_latest, shares_prior = get_latest_and_prior_instant(
        [
            ("dei", "EntityCommonStockSharesOutstanding"),
            ("us-gaap", "CommonStockSharesOutstanding"),
        ],
        "shares",
        quarters,
    )

    print("Fetching SEC Annual Operating Cash Flow...")
    ocf_annual = get_latest_annual(
        [
            ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
            ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
        ],
        "USD",
    )

    print("Fetching SEC Annual Operating Income (EBIT)...")
    ebit_annual = get_latest_annual(
        [
            ("us-gaap", "OperatingIncomeLoss"),
            ("us-gaap", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"),
        ],
        "USD",
    )

    print("Fetching SEC Annual Interest Expense...")
    int_exp_annual = get_latest_annual(
        [
            ("us-gaap", "InterestExpense"),
            ("us-gaap", "InterestExpenseDebt"),
            ("us-gaap", "InterestAndDebtExpense"),
        ],
        "USD",
    )

    all_tickers = sorted(set(nasdaq.keys()) | set(ticker_to_cik.keys()))
    rows_written = 0

    with open("fundamentals_import.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Ticker",
            "Sector",
            "Snapshot Market Cap ($M)",
            "Adjusted Book Value of Equity ($M)",
            "Adjusted Operating Cash Flow ($M)",
            "YoY Total Asset Growth (%)",
            "Net Share Issuance (%)",
            "Interest Coverage Ratio (x)",
            "IPO Date",
        ])

        for ticker in all_tickers:
            meta = nasdaq.get(ticker, {})
            cik = ticker_to_cik.get(ticker)

            sector = meta.get("sector", "")
            mcap_m = meta.get("mcap_m")
            ipo_date = meta.get("ipo_date", "")

            book_m = ""
            ocf_m = ""
            asset_growth = ""
            share_issuance = ""
            int_cov = ""

            if cik is not None:
                if cik in equity_latest:
                    book_m = round(equity_latest[cik][0] / 1_000_000, 2)
                if cik in ocf_annual:
                    ocf_m = round(ocf_annual[cik] / 1_000_000, 2)

                if cik in assets_latest and cik in assets_prior and assets_prior[cik] > 0:
                    asset_growth = round((assets_latest[cik][0] / assets_prior[cik]) - 1, 4)

                if cik in shares_latest and cik in shares_prior and shares_prior[cik] > 0:
                    share_issuance = round((shares_latest[cik][0] / shares_prior[cik]) - 1, 4)

                if cik in ebit_annual:
                    ebit = ebit_annual[cik]
                    interest = int_exp_annual.get(cik, 0.0)
                    if interest > 0:
                        int_cov = max(-99.0, min(99.0, round(ebit / interest, 2)))
                    elif ebit > 0:
                        int_cov = 99.0  # Profitable with zero reported interest expense
                    else:
                        int_cov = 0.0

                # NASDAQ leaves ipoyear blank for many legacy companies;
                # if a company already has prior-year SEC balance-sheet filings, mark it seasoned.
                if not ipo_date and cik in assets_prior:
                    ipo_date = "2000-01-01"

            if any(x != "" and x is not None for x in [sector, mcap_m, book_m, ocf_m]):
                writer.writerow([
                    ticker,
                    sector,
                    "" if mcap_m is None else mcap_m,
                    book_m,
                    ocf_m,
                    asset_growth,
                    share_issuance,
                    int_cov,
                    ipo_date,
                ])
                rows_written += 1

    print(f"Wrote {rows_written} rows to fundamentals_import.csv")


if __name__ == "__main__":
    main()
