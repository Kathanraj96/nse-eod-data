# nse-eod-data

Daily end-of-day closing prices for Indian listed equities, built from the official
NSE and BSE Bhavcopy files and published as a single JSON file.

```
https://raw.githubusercontent.com/Kathanraj96/nse-eod-data/main/prices.json
```

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
  [config/composites.json](config/composites.json).

## How it updates

[.github/workflows/update-prices.yml](.github/workflows/update-prices.yml) runs on weekdays at
19:00 IST, with a retry at 22:00 IST. It runs [fetch_prices.py](fetch_prices.py), which uses only the
Python standard library, and commits `prices.json` only when a newer trading day is available.
To run it on demand, go to **Actions → Update EOD prices → Run workflow**.

Run locally:

```bash
python3 fetch_prices.py
```

## Disclaimer

Data is sourced from publicly available exchange files and is provided as-is, for
informational purposes only.
