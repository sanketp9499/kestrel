#!/usr/bin/env python3
"""idealist_scraper.py — Scrape Idealist nonprofit job listings.

Idealist is client-rendered, so plain HTTP returns nav links and nothing else,
but it needs **no login** and showed no Cloudflare challenge. In a real browser
the board reports ~1,072 open jobs and each card renders as one pipe-delimited
line, which makes parsing unusually reliable:

    Title | Organisation | Mode | Location | Type | Salary | Posted N days ago

Real Canadian roles with CAD salaries do appear (e.g. "Operations and Finance
Manager | Human Rights Watch | Hybrid | Toronto, ON, Canada | Full Time |
CAD 100,000 - 120,000 / year"), which is why this one is worth having even
though it is a nonprofit-sector board rather than a design board.

the user's own filter URL kept the entry-level bands, so those are the default:
professionalLevel=NONE and ENTRY_LEVEL.

Usage:
    python Scripts/idealist_scraper.py --output Scripts/daily_report_idealist.json
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_fetch import BrowserSession, _log

BASE = "https://www.idealist.org"

# the user's filters: entry level and no-experience-required, Canada.
SEARCHES = [
    "/en/jobs?professionalLevel=NONE&professionalLevel=ENTRY_LEVEL&countryCode=CA",
    "/en/jobs?professionalLevel=NONE&professionalLevel=ENTRY_LEVEL&countryCode=CA&q=designer",
    "/en/jobs?professionalLevel=NONE&professionalLevel=ENTRY_LEVEL&countryCode=CA&q=communications",
]

CANADA = re.compile(
    r"canada|toronto|vancouver|montr[eé]al|ottawa|calgary|edmonton|winnipeg|"
    r"halifax|waterloo|kitchener|mississauga|,\s*(on|bc|ab|qc|ns|nb|mb|sk|nl|pe)\b", re.I)

EXTRACT_JS = """() => {
  return [...document.querySelectorAll('a[href*="/en/nonprofit-job/"]')].map(a => ({
    href: a.getAttribute('href'),
    text: (a.innerText || '').replace(/\\s*\\n\\s*/g, ' | ').trim()
  })).filter(r => r.text.length > 10);
}"""

DECLINE_JS = """() => {
  const words = /^(no,? thanks|decline|reject all|only necessary|essential only)$/i;
  const b = [...document.querySelectorAll('button,a')]
    .find(e => words.test((e.innerText || '').trim()));
  if (b) { b.click(); return true; }
  return false;
}"""

POSTED_RE = re.compile(r"posted\s+(.+)$", re.I)
SALARY_RE = re.compile(r"(CAD|USD|\$)\s?[\d,]+", re.I)
MODE_RE = re.compile(r"^(hybrid|remote|on ?site|in person)$", re.I)
TYPE_RE = re.compile(r"^(full time|part time|contract|temporary|internship|volunteer)$", re.I)


def _days_old(posted):
    m = re.search(r"(\d+)\s*(day|week|month|hour)", posted or "", re.I)
    if not m:
        return 0 if re.search(r"today|yesterday", posted or "", re.I) else 99
    n, unit = int(m.group(1)), m.group(2).lower()
    return {"hour": 0, "day": n, "week": n * 7, "month": n * 30}.get(unit, 99)


def parse_row(row, canada_only=True):
    """One pipe-delimited card line into a pipeline job dict."""
    parts = [p.strip() for p in row["text"].split(" | ") if p.strip()]
    if len(parts) < 2:
        return None

    title, org = parts[0], parts[1]
    mode = location = job_type = salary = posted = ""
    for p in parts[2:]:
        if MODE_RE.match(p):
            mode = p
        elif TYPE_RE.match(p):
            job_type = p
        elif SALARY_RE.search(p):
            salary = p
        elif POSTED_RE.match(p):
            posted = POSTED_RE.match(p).group(1)
        elif not location:
            location = p

    where = ", ".join(x for x in (location, mode) if x)
    if canada_only and not CANADA.search(where):
        return None

    href = row["href"]
    return {
        "title":      title,
        "company":    org,
        "location":   where or "Canada",
        "salary":     salary,
        "snippet":    "",
        "url":        href if href.startswith("http") else BASE + href,
        "age_str":    posted,
        "source":     "idealist",
        "job_key":    "idealist-" + href.rsplit("/", 1)[-1][:40],
        "apply_type": "DIRECT",
        # Idealist-only extras
        "job_type":   job_type,
        "work_mode":  mode,
        "days_old_raw": _days_old(posted),
    }


def search_idealist(searches=None, canada_only=True, headless=False, delay=3.0):
    searches = searches or SEARCHES
    by_key = {}
    with BrowserSession(headless=headless, wait_ms=8000) as s:
        for i, path in enumerate(searches):
            if not s.html(BASE + path, wait_ms=8000):
                _log(f"  Idealist: no content for {path[:60]}")
                continue
            try:
                s._page.evaluate(DECLINE_JS)
                s._page.wait_for_timeout(4000)
                rows = s._page.evaluate(EXTRACT_JS)
            except Exception as e:
                _log(f"  Idealist: extract failed: {str(e)[:80]}")
                continue
            for row in rows:
                job = parse_row(row, canada_only=canada_only)
                if job:
                    by_key.setdefault(job["job_key"], job)
            if i < len(searches) - 1:
                s.sleep(delay)
    jobs = list(by_key.values())
    _log(f"Idealist: {len(jobs)} {'Canadian ' if canada_only else ''}jobs "
         f"from {len(searches)} search(es)")
    return jobs


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="Scripts/daily_report_idealist.json")
    p.add_argument("--worldwide", action="store_true")
    p.add_argument("--headless", action="store_true")
    args = p.parse_args()

    jobs = search_idealist(canada_only=not args.worldwide, headless=args.headless)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)
    _log(f"Wrote {len(jobs)} Idealist jobs to {args.output}")
