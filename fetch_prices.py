#!/usr/bin/env python3
"""
Build prices.json and stocks.json from the official NSE + BSE end-of-day Bhavcopy files.

- prices.json: {symbol: close} for every listed equity (small, for price lookups).
- stocks.json: [symbol, name, close] rows for every listed equity (for search).

- NSE is the primary source; BSE fills in companies (by ISIN) not traded on NSE.
- If one exchange's file can't be fetched, the other is used alone.
- Composite symbols (e.g. demergers) are summed from their parts, see config/composites.json.
- Exits 0 without touching prices.json when there is no newer trading day.

Standard library only, so it runs on a bare GitHub Actions runner.
"""

import csv
import io
import json
import sys
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_FILE = ROOT / "prices.json"
STOCKS_FILE = ROOT / "stocks.json"
COMPOSITES_FILE = ROOT / "config" / "composites.json"

NSE_URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d}_F_0000.csv.zip"
BSE_URL = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{d}_F_0000.CSV"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "*/*",
}

IST = timezone(timedelta(hours=5, minutes=30))
# Bhavcopy files are normally out by ~18:00 IST; before that, start from the previous day.
PUBLISH_HOUR_IST = 18
LOOKBACK_DAYS = 10
# Fail the run (so GitHub emails a failure) if the newest file found is older than this.
# Covers weekends plus a couple of exchange holidays.
MAX_STALE_DAYS = 6

# Preferred NSE series when a symbol trades in more than one.
NSE_SERIES_PRIORITY = ["EQ", "BE", "BZ", "SM", "ST"]


def http_get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def fetch_nse(day):
    raw = http_get(NSE_URL.format(d=day.strftime("%Y%m%d")))
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        return zf.read(zf.namelist()[0]).decode("utf-8")


def fetch_bse(day):
    return http_get(BSE_URL.format(d=day.strftime("%Y%m%d"))).decode("utf-8")


def try_fetch(fetcher, day, label):
    try:
        return fetcher(day)
    except Exception as exc:  # 404 on holidays, 403 from bot protection, timeouts...
        print(f"  {label} {day:%Y-%m-%d}: unavailable ({exc})")
        return None


def is_equity_isin(isin):
    # Indian ISIN: 'INE' + 4-char issuer + 2-digit security type + ... ; type '01' = equity shares.
    # Excludes bonds/NCDs (07), InvITs (23), rights entitlements (20), etc.
    return len(isin) == 12 and isin.startswith("INE") and isin[7:9] == "01"


def tidy_name(name):
    # Exchange names are kept in their original case (title-casing mangles acronyms like ITC).
    return " ".join(name.split()).rstrip(" -")


def equity_rows(text):
    """Yield (symbol, isin, series, name, close) for company equity share rows."""
    for r in csv.DictReader(io.StringIO(text)):
        isin = r.get("ISIN", "")
        if r.get("FinInstrmTp") != "STK" or not is_equity_isin(isin):
            continue
        try:
            close = float(r["ClsPric"])
        except (KeyError, ValueError):
            continue
        if close > 0:
            yield (r["TckrSymb"].strip(), isin, r.get("SctySrs", "").strip(),
                   tidy_name(r.get("FinInstrmNm", "")), close)


def build_stocks(nse_text, bse_text):
    """Return {symbol: (name, close)}."""
    stocks = {}
    seen_isins = set()
    # Both exchanges truncate names (to different lengths); keep the longer one per ISIN.
    bse_names = {isin: name for _, isin, _, name, _ in equity_rows(bse_text)} if bse_text else {}

    if nse_text:
        best = {}  # symbol -> (priority, isin, name, close)
        for sym, isin, series, name, close in equity_rows(nse_text):
            if series not in NSE_SERIES_PRIORITY:
                continue
            rank = NSE_SERIES_PRIORITY.index(series)
            if sym not in best or rank < best[sym][0]:
                best[sym] = (rank, isin, name, close)
        for sym, (_, isin, name, close) in best.items():
            name = max(name, bse_names.get(isin, ""), key=len)
            stocks[sym] = (name, round(close, 2))
            seen_isins.add(isin)

    if bse_text:
        for sym, isin, _, name, close in equity_rows(bse_text):
            # Only companies NSE didn't cover, and never overwrite an NSE ticker.
            if isin in seen_isins or sym in stocks:
                continue
            stocks[sym] = (name, round(close, 2))
            seen_isins.add(isin)

    return stocks


def apply_composites(prices):
    if not COMPOSITES_FILE.exists():
        return
    composites = json.loads(COMPOSITES_FILE.read_text())
    for sym, spec in composites.items():
        parts = spec["parts"]
        missing = [p for p in parts if p not in prices]
        if missing:
            print(f"  composite {sym}: skipped, missing parts {missing}")
            continue
        prices[sym] = round(sum(prices[p] * spec.get("ratio", {}).get(p, 1) for p in parts), 2)


def current_as_of():
    try:
        return json.loads(OUT_FILE.read_text()).get("asOf")
    except (FileNotFoundError, ValueError):
        return None


def main():
    now = datetime.now(IST)
    start = now.date() if now.hour >= PUBLISH_HOUR_IST else now.date() - timedelta(days=1)

    for offset in range(LOOKBACK_DAYS):
        day = start - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        print(f"Trying {day:%Y-%m-%d}...")
        nse_text = try_fetch(fetch_nse, day, "NSE")
        bse_text = try_fetch(fetch_bse, day, "BSE")
        if nse_text or bse_text:
            break
    else:
        print("No Bhavcopy found from either exchange in the lookback window.", file=sys.stderr)
        return 1

    as_of = day.isoformat()
    if (now.date() - day).days > MAX_STALE_DAYS:
        print(f"Newest Bhavcopy is from {as_of}, more than {MAX_STALE_DAYS} days old.", file=sys.stderr)
        return 1
    previous = current_as_of()
    if previous and previous >= as_of:
        print(f"prices.json already at {previous}; nothing to do.")
        return 0

    stocks = build_stocks(nse_text, bse_text)
    if len(stocks) < 1000:  # a sane full-market file has thousands of rows
        print(f"Only {len(stocks)} stocks parsed; refusing to publish.", file=sys.stderr)
        return 1
    prices = {sym: close for sym, (_, close) in stocks.items()}
    apply_composites(prices)

    meta = {
        "asOf": as_of,
        "sources": [s for s, t in (("NSE", nse_text), ("BSE", bse_text)) if t],
        "generatedAt": now.isoformat(timespec="seconds"),
    }
    write_json(OUT_FILE, {**meta, "count": len(prices), "prices": dict(sorted(prices.items()))})
    write_json(STOCKS_FILE, {
        **meta,
        "count": len(stocks),
        "fields": ["symbol", "name", "price"],
        "stocks": [[sym, name, close] for sym, (name, close) in sorted(stocks.items())],
    })
    print(f"Wrote {len(prices)} prices / {len(stocks)} stocks as of {as_of} from {meta['sources']}.")
    return 0


def write_json(path, payload):
    path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")


if __name__ == "__main__":
    sys.exit(main())
