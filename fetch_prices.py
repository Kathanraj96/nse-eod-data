#!/usr/bin/env python3
"""
Build prices.json from the official NSE + BSE end-of-day Bhavcopy files.

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


def equity_rows(text):
    """Yield (symbol, isin, series, close) for company equity rows (ISIN 'INE...')."""
    for r in csv.DictReader(io.StringIO(text)):
        isin = r.get("ISIN", "")
        if r.get("FinInstrmTp") != "STK" or not isin.startswith("INE"):
            continue
        try:
            close = float(r["ClsPric"])
        except (KeyError, ValueError):
            continue
        if close > 0:
            yield r["TckrSymb"].strip(), isin, r.get("SctySrs", "").strip(), close


def build_prices(nse_text, bse_text):
    prices = {}
    seen_isins = set()

    if nse_text:
        best = {}  # symbol -> (priority, isin, close)
        for sym, isin, series, close in equity_rows(nse_text):
            if series not in NSE_SERIES_PRIORITY:
                continue
            rank = NSE_SERIES_PRIORITY.index(series)
            if sym not in best or rank < best[sym][0]:
                best[sym] = (rank, isin, close)
        for sym, (_, isin, close) in best.items():
            prices[sym] = round(close, 2)
            seen_isins.add(isin)

    if bse_text:
        for sym, isin, _, close in equity_rows(bse_text):
            # Only companies NSE didn't cover, and never overwrite an NSE ticker.
            if isin in seen_isins or sym in prices:
                continue
            prices[sym] = round(close, 2)
            seen_isins.add(isin)

    return prices


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
    previous = current_as_of()
    if previous and previous >= as_of:
        print(f"prices.json already at {previous}; nothing to do.")
        return 0

    prices = build_prices(nse_text, bse_text)
    if len(prices) < 1000:  # a sane full-market file has thousands of rows
        print(f"Only {len(prices)} prices parsed; refusing to publish.", file=sys.stderr)
        return 1
    apply_composites(prices)

    payload = {
        "asOf": as_of,
        "sources": [s for s, t in (("NSE", nse_text), ("BSE", bse_text)) if t],
        "generatedAt": now.isoformat(timespec="seconds"),
        "count": len(prices),
        "prices": dict(sorted(prices.items())),
    }
    OUT_FILE.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    print(f"Wrote {len(prices)} prices as of {as_of} from {payload['sources']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
