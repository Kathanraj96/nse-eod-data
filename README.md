# nse-eod-data

[![Update EOD prices](https://github.com/Kathanraj96/nse-eod-data/actions/workflows/update-prices.yml/badge.svg)](https://github.com/Kathanraj96/nse-eod-data/actions/workflows/update-prices.yml)

Daily end-of-day closing prices for Indian listed equities, built from the official
NSE and BSE Bhavcopy files and published as JSON.

| File | Contents | Size (gzip) |
| --- | --- | --- |
| [`prices.json`](https://raw.githubusercontent.com/Kathanraj96/nse-eod-data/main/prices.json) | `{symbol: close}` for price lookups | ~36 KB |
| [`stocks.json`](https://raw.githubusercontent.com/Kathanraj96/nse-eod-data/main/stocks.json) | `[symbol, name, close, formerNames]` rows for search | ~86 KB |

Only equity shares are included. ISIN security type `01` excludes bonds, NCDs, InvITs and
rights entitlements.

## Format

```json
{
  "asOf": "2026-10-16",
  "sources": ["NSE", "BSE"],
  "generatedAt": "2026-10-16T19:02:11+05:30",
  "count": 5123,
  "prices": { "RELIANCE": 1412.3, "TCS": 3020.5, "...": 0 }
}
```

- Keys are NSE ticker symbols. Companies listed only on BSE appear under their BSE ticker.
- NSE is preferred. BSE fills in companies (matched by ISIN) that NSE doesn't cover.
- Composite symbols such as demerged companies are summed from their parts. See
  [config/composites.json](config/composites.json). These appear only in `prices.json`.

`stocks.json` uses the same `asOf`/`sources`/`generatedAt` fields, plus:

```json
{ "fields": ["symbol", "name", "price", "formerNames"],
  "stocks": [["RELIANCE", "RELIANCE INDUSTRIES LTD.", 1211.2],
             ["ZEEL", "ZEE ENTERTAINMENT ENTERPRISES", 98.4, ["Zee Telefilms Ltd"]]] }
```

`formerNames` (oldest first) appears only when the company has changed its name. It comes from NSE's
[name-change](https://nsearchives.nseindia.com/content/equities/namechange.csv) list, which covers
renames from about 2000 onwards. Symbols that have changed since a rename are followed through
NSE's symbol-change list. If NSE's lists can't be fetched, the previous day's names are kept.

## How it updates

[.github/workflows/update-prices.yml](.github/workflows/update-prices.yml) runs on weekdays at
19:00 IST, with a retry at 22:00 IST. It runs [fetch_prices.py](fetch_prices.py), which uses only the
Python standard library, and commits `prices.json` only when a newer trading day is available.
To run it on demand, go to **Actions → Update EOD prices → Run workflow**.

A run **fails**, and GitHub emails a failure notice, when neither exchange file can be fetched,
when fewer than 1,000 stocks are parsed, or when the newest file is more than 6 days old.

Run locally:

```bash
python3 fetch_prices.py
```

## Disclaimer

Data is sourced from publicly available exchange files and is provided as-is, for
informational purposes only.
