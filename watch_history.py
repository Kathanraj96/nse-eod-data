#!/usr/bin/env python3
"""Weekly watch on the corporate-action history of the curated stocks.

Looks for events that could make the calculator's recorded history stale:
bonus, split, consolidation, merger/demerger/arrangement, capital reduction,
name or symbol changes, and curated symbols that no longer have a price.
For each new finding it opens a GitHub issue. It never edits any data.

Usage: python3 watch_history.py [--dry-run]
"""
import csv
import io
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
LOOKBACK_DAYS = 21
LOOKAHEAD_DAYS = 90
KEYWORDS = re.compile(
    r"bonus|split|sub-?division|consolidat|arrangement|amalgamat|demerger|merger|"
    r"capital reduction|reduction of (?:share )?capital|face value", re.I)
NAME_CHANGE_URL = "https://nsearchives.nseindia.com/content/equities/namechange.csv"
SYMBOL_CHANGE_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"
NSE_HOME = "https://www.nseindia.com/companies-listing/corporate-filings-actions"
NSE_API = "https://www.nseindia.com/api/corporates-corporateActions"

try:
    from curl_cffi import requests as http  # NSE blocks plain clients from some hosts
    session = http.Session(impersonate="chrome120")
except ImportError:
    sys.exit("curl_cffi is required: pip install curl_cffi")


def fmt(d):
    return d.strftime("%d-%m-%Y")


def parse(text):
    return datetime.strptime(text.strip(), "%d-%b-%Y").date()


def fetch_actions(today):
    session.get(NSE_HOME, timeout=30)
    r = session.get(NSE_API, params={
        "index": "equities",
        "from_date": fmt(today - timedelta(days=LOOKBACK_DAYS)),
        "to_date": fmt(today + timedelta(days=LOOKAHEAD_DAYS)),
    }, headers={"Referer": "https://www.nseindia.com/"}, timeout=60)
    r.raise_for_status()
    rows = r.json()
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("NSE corporate actions returned no rows")
    return rows


def fetch_csv(url):
    r = session.get(url, timeout=60)
    r.raise_for_status()
    return list(csv.reader(io.StringIO(r.text)))


def findings(curated, today):
    since = today - timedelta(days=LOOKBACK_DAYS)
    out = []  # (key, title, body)

    for a in fetch_actions(today):
        sym, subject = a.get("symbol", ""), a.get("subject", "")
        if sym in curated and KEYWORDS.search(subject) and "dividend" not in subject.lower():
            key = f"{sym} {a.get('exDate')} {subject}"
            out.append((key, f"[history] {sym}: {subject} (ex {a.get('exDate')})",
                        f"NSE lists a corporate action for curated stock **{sym}** ({a.get('comp')}).\n\n"
                        f"- Subject: {subject}\n- Ex-date: {a.get('exDate')}\n- Face value now: {a.get('faceVal')}\n\n"
                        "Check the calculator entry and add or adjust the history if needed."))

    for r in fetch_csv(NAME_CHANGE_URL):
        try:
            sym, old, new, when = r[0].strip(), r[1].strip(), r[2].strip(), parse(r[3])
        except (IndexError, ValueError):
            continue
        if sym in curated and when >= since:
            out.append((f"{sym} rename {when}", f"[history] {sym}: renamed to {new} ({when})",
                        f"Name change for curated stock **{sym}**: {old} -> {new}, effective {when}.\n\n"
                        "Add the old name to the calculator aliases."))

    for r in fetch_csv(SYMBOL_CHANGE_URL):
        try:
            old, new, when = r[1].strip(), r[2].strip(), parse(r[3])
        except (IndexError, ValueError):
            continue
        if old in curated and when >= since:
            out.append((f"{old} symbol {when}", f"[history] {old}: symbol changed to {new} ({when})",
                        f"Curated stock **{old}** now trades as **{new}** from {when}.\n\n"
                        "Update the symbol in the calculator."))

    prices = json.loads((ROOT / "prices.json").read_text())["prices"]
    for sym in sorted(curated - prices.keys()):
        out.append((f"{sym} no price", f"[history] {sym}: no longer in daily prices",
                    f"Curated stock **{sym}** has no price in prices.json. It may be delisted, merged or renamed."))
    return out


def existing_issue_titles():
    res = subprocess.run(["gh", "issue", "list", "--state", "all", "--limit", "500",
                          "--search", "[history] in:title", "--json", "title"],
                         capture_output=True, text=True, check=True)
    return {i["title"] for i in json.loads(res.stdout)}


def main():
    dry = "--dry-run" in sys.argv
    today = date.today()
    curated = set(json.loads((ROOT / "config" / "curated.json").read_text())["symbols"])
    found = findings(curated, today)
    seen = set() if dry else existing_issue_titles()
    opened = 0
    for _, title, body in found:
        if title in seen:
            continue
        print(("WOULD OPEN: " if dry else "OPENING: ") + title)
        if not dry:
            subprocess.run(["gh", "issue", "create", "--title", title, "--body",
                            body + "\n\n_Opened by watch_history.py. Data is not edited automatically._"],
                           check=True)
        opened += 1
    print(f"{len(curated)} curated stocks, {len(found)} findings, {opened} new")


if __name__ == "__main__":
    main()
