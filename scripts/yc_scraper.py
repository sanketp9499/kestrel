#!/usr/bin/env python3
"""yc_scraper.py — Scrape Y Combinator's public startup jobs board.

Two YC job surfaces exist and only one is usable:

  * www.ycombinator.com/jobs/role/<role>  — public, no login, fully rendered.
    This is what we read.
  * www.workatastartup.com/jobs           — the real board, but it returns 406
    to non-browser clients and shows nothing without a YC account. Not used.

Each card carries company, YC batch, one-line tagline, posting age, title,
employment type, design sub-category, salary band and location, which is more
structure than most sources give up.

**Read the Canada caveat before wiring this into the daily run.** YC startups
skew heavily to San Francisco and New York, with a long tail in India. On a
typical sweep only a handful of roles are Canada-eligible, so this is a
low-volume, high-quality source, not a replacement for the board scrapers.

Usage:
    python Scripts/yc_scraper.py --output Scripts/daily_report_yc.json
    python Scripts/yc_scraper.py --worldwide      # skip the Canada filter
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_fetch import BrowserSession, _log

BASE = "https://www.ycombinator.com"
ROLE_PATHS = ["/jobs/role/design"]

# Deliberately no bare "CA": in YC location strings CA means California far more
# often than Canada ("San Francisco, CA, US"), so matching it turns the Canada
# filter into a California filter. Match cities, provinces and the country name.
CANADA = ["canada", "toronto", "vancouver", "montreal", "montréal", "ottawa",
          "calgary", "edmonton", "waterloo", "kitchener", "halifax", "winnipeg",
          "mississauga", "ontario", "british columbia", "quebec", "québec",
          "alberta", "nova scotia", "manitoba", "saskatchewan"]

# "Numen (S23)*Engineering a future without cancer deaths.(25 days ago)"
HEAD_RE = re.compile(r"^(?P<company>.+?)\s*\((?P<batch>[WSFXwsfx]\d{2})\)")
AGE_RE = re.compile(r"\(([^()]*ago)\)")

EXTRACT_JS = """() => {
  const rows = [...document.querySelectorAll('a[href*="/companies/"]')]
    .filter(a => /\\/companies\\/[^/]+\\/jobs\\//.test(a.getAttribute('href') || ''));
  return rows.map(a => {
    const box = a.closest('div') && a.closest('div').parentElement;
    return {
      href: a.getAttribute('href'),
      title: (a.innerText || '').trim(),
      block: box ? (box.innerText || '').replace(/\\s*\\n\\s*/g, ' | ').trim() : ''
    };
  });
}"""


def _parse_block(block, title):
    """Pull the fields out of one card's flattened text."""
    head = block.split(" | ")[0] if " | " in block else block
    m = HEAD_RE.match(head)
    company = m.group("company").strip() if m else ""
    batch = m.group("batch").upper() if m else ""

    age = ""
    a = AGE_RE.search(head)
    if a:
        age = a.group(1).strip()

    parts = [p.strip() for p in block.split(" | ")[1:] if p.strip() and p.strip() != "•"]
    if parts and parts[0] == title:
        parts = parts[1:]

    job_type = parts[0] if parts else ""
    salary, location, tags = "", "", []
    for p in parts[1:]:
        if re.search(r"[$₹€£]\s?\d|\d+K\s*-\s*\d+K", p):
            salary = p
        elif re.search(r"[A-Z]{2}$|remote|,\s*[A-Z]{2},", p, re.I) or "/" in p:
            location = p
        else:
            tags.append(p)
    return company, batch, age, job_type, salary, location, tags


def _days_old(age_str):
    m = re.search(r"(\d+)\s*(day|week|month|hour)", age_str or "", re.I)
    if not m:
        return 99
    n, unit = int(m.group(1)), m.group(2).lower()
    return {"hour": 0, "day": n, "week": n * 7, "month": n * 30}.get(unit, 99)


def parse_rows(rows, canada_only=True):
    jobs = []
    for r in rows:
        title = (r.get("title") or "").strip()
        block = r.get("block") or ""
        if not title or not block:
            continue
        company, batch, age, job_type, salary, location, tags = _parse_block(block, title)
        if canada_only and not any(t in location.lower() for t in CANADA):
            continue
        href = r["href"]
        jobs.append({
            "title":      title,
            "company":    company,
            "location":   location,
            "salary":     salary,
            "snippet":    " ".join(tags)[:400],
            "url":        href if href.startswith("http") else BASE + href,
            "age_str":    age,
            "source":     "ycombinator",
            "job_key":    "yc-" + href.rsplit("/", 1)[-1],
            "apply_type": "DIRECT",
            # YC-only extras
            "yc_batch":   batch,
            "job_type":   job_type,
            "tags":       tags,
            "days_old_raw": _days_old(age),
        })
    return jobs


def search_yc(paths=None, canada_only=True, headless=False, delay=3.0):
    paths = paths or ROLE_PATHS
    by_key = {}
    with BrowserSession(headless=headless, wait_ms=6000) as session:
        for i, path in enumerate(paths):
            if not session.html(BASE + path, wait_ms=6000):
                _log(f"  YC: no content for {path}")
                continue
            try:
                rows = session._page.evaluate(EXTRACT_JS)
            except Exception as e:
                _log(f"  YC: extract failed on {path}: {str(e)[:80]}")
                continue
            for job in parse_rows(rows, canada_only=canada_only):
                by_key.setdefault(job["job_key"], job)
            if i < len(paths) - 1:
                session.sleep(delay)
    jobs = list(by_key.values())
    _log(f"YC: {len(jobs)} {'Canada-eligible ' if canada_only else ''}jobs "
         f"from {len(paths)} role page(s)")
    return jobs


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="Scripts/daily_report_yc.json")
    p.add_argument("--worldwide", action="store_true", help="do not filter to Canada")
    p.add_argument("--headless", action="store_true")
    args = p.parse_args()

    jobs = search_yc(canada_only=not args.worldwide, headless=args.headless)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)
    _log(f"Wrote {len(jobs)} YC jobs to {args.output}")
