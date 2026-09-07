#!/usr/bin/env python3
"""hiringcafe_scraper.py — Scrape HiringCafe (hiringcafe.com) search results.

HiringCafe is an aggregator sitting on top of ~12,800 company boards, and it is
the richest of the sources here. Its search pages are server-rendered, so the
whole result set is in the page's __NEXT_DATA__ under `ssrHits` — 60 records per
request, each one carrying:

  * `apply_url`  — the real ATS link, not a HiringCafe redirect
  * `source`     — which ATS (workday / greenhouse / lever / ashby / ...), so the
                   job routes straight to an existing adapter
  * structured location (`workplace_cities` / `_states` / `_countries`)
  * real salary with currency and frequency
  * `estimated_publish_date`, `is_expired`
  * `min_industry_and_role_yoe` and `seniority_level`, which is what the
    "skip 5+ years required" rule in RUN_PIPELINE.md actually needs

It is behind Cloudflare. Plain HTTP works for one cold request and then starts
returning "Just a moment..." challenges, so this goes through the real browser
(see browser_fetch.py) rather than urllib.

Usage:
    python Scripts/hiringcafe_scraper.py --output Scripts/daily_report_hiringcafe.json
"""
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_fetch import BrowserSession, _log

BASE = "https://hiringcafe.com/"

SEARCH_TERMS = [
    "ux designer",
    "product designer",
    "ui ux designer",
    "digital designer",
    "interaction designer",
    "web designer",
]

# The location filter HiringCafe itself applies for a Canadian visitor. Passing
# it explicitly means the results do not depend on what IP the run happens from.
CANADA_LOCATION = {
    "formatted_address": "Canada",
    "types": ["country"],
    "geometry": {"location": {"lat": 0, "lon": 0}},
    "id": "user_country",
    "address_components": [
        {"long_name": "Canada", "short_name": "CA", "types": ["country"]}
    ],
    "options": {"flexible_regions": ["anywhere_in_continent", "anywhere_in_world"]},
}

# HiringCafe's `source` values -> the apply_type names daily_auto_apply uses.
SOURCE_TO_ATS = {
    "greenhouse": "GREENHOUSE",
    "lever": "LEVER",
    "ashby": "ASHBY",
    "workable": "WORKABLE",
    "workday": "WORKDAY",
    "smartrecruiters": "DIRECT",
    "icims": "ICIMS",
    "taleo": "TALEO",
    "bamboohr": "BAMBOOHR",
}


def _search_url(term, extra_state=None):
    state = {"searchQuery": term, "locations": [CANADA_LOCATION]}
    if extra_state:
        state.update(extra_state)
    return BASE + "?searchState=" + urllib.parse.quote(json.dumps(state))


def _salary(v5):
    """Readable salary string from whichever compensation pair is populated."""
    currency = v5.get("listed_compensation_currency") or ""
    for freq, lo_key, hi_key, suffix in (
        ("Yearly", "yearly_min_compensation", "yearly_max_compensation", "/yr"),
        ("Hourly", "hourly_min_compensation", "hourly_max_compensation", "/hr"),
        ("Monthly", "monthly_min_compensation", "monthly_max_compensation", "/mo"),
    ):
        lo, hi = v5.get(lo_key), v5.get(hi_key)
        if lo or hi:
            lo_s = f"{int(lo):,}" if lo else "?"
            hi_s = f"{int(hi):,}" if hi else "?"
            return f"{lo_s} - {hi_s} {currency}{suffix}".strip()
    return ""


def _location(v5):
    parts = list(v5.get("workplace_cities") or []) or \
            list(v5.get("workplace_states") or []) or \
            list(v5.get("workplace_countries") or [])
    workplace = v5.get("workplace_type") or ""
    if workplace and workplace.lower() not in " ".join(parts).lower():
        parts.append(workplace)
    return ", ".join(p for p in parts if p)


def _is_canada(v5):
    blob = " ".join(list(v5.get("workplace_countries") or []) +
                    list(v5.get("boundless_workplace_countries") or [])).upper()
    return "CA" in blob.split() or "CANADA" in blob


def parse_hits(page_props, canada_only=True):
    hits = page_props.get("ssrHits") or []
    jobs = []
    for h in hits:
        if h.get("is_expired"):
            continue
        v5 = h.get("v5_processed_job_data") or {}
        if canada_only and not _is_canada(v5):
            continue
        info = h.get("job_information") or {}
        company = (h.get("enriched_company_data") or {}).get("name") \
            or (h.get("attributed_org") or {}).get("name") or ""
        published = (v5.get("estimated_publish_date") or "")[:10]
        jobs.append({
            "title":      info.get("title") or v5.get("core_job_title") or "",
            "company":    company,
            "location":   _location(v5),
            "salary":     _salary(v5),
            "snippet":    (v5.get("requirements_summary") or "")[:400],
            "url":        h.get("apply_url") or "",
            "age_str":    published,
            "source":     "hiringcafe",
            "job_key":    f"hiringcafe-{h.get('id') or h.get('objectID')}",
            "apply_type": SOURCE_TO_ATS.get((h.get("source") or "").lower(), ""),
            # HiringCafe-only extras
            "requirements_summary": v5.get("requirements_summary") or "",
            "min_yoe":        v5.get("min_industry_and_role_yoe"),
            "seniority":      v5.get("seniority_level") or "",
            "workplace_type": v5.get("workplace_type") or "",
            "commitment":     v5.get("commitment") or [],
            "ats_board":      h.get("board_token") or "",
        })
    return jobs


def search_hiringcafe(terms=None, canada_only=True, headless=False, delay=4.0):
    """One request per search term (60 results each), through a real browser.

    Headed by default on purpose: Cloudflare fails headless Chrome on this site
    every time, however long it waits. Same choice the LinkedIn adapter makes.
    """
    terms = terms or SEARCH_TERMS
    by_key, ok = {}, 0
    with BrowserSession(headless=headless, wait_ms=3500) as session:
        for i, term in enumerate(terms):
            props = session.next_data(_search_url(term))
            found = parse_hits(props, canada_only=canada_only) if props else []
            if found:
                ok += 1
            elif not props:
                _log(f"  HiringCafe: no data for '{term}' (challenge page or timeout)")
            for job in found:
                by_key.setdefault(job["job_key"], job)
            if i < len(terms) - 1:
                session.sleep(delay)
    jobs = list(by_key.values())
    _log(f"HiringCafe: {len(jobs)} unique Canada jobs from {ok}/{len(terms)} searches")
    return jobs


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="Scripts/daily_report_hiringcafe.json")
    parser.add_argument("--terms", help="comma-separated search terms")
    parser.add_argument("--worldwide", action="store_true", help="do not filter to Canada")
    parser.add_argument("--headless", action="store_true",
                        help="hide the browser (Cloudflare usually blocks this)")
    args = parser.parse_args()

    jobs = search_hiringcafe(
        terms=[t.strip() for t in args.terms.split(",")] if args.terms else None,
        canada_only=not args.worldwide,
        headless=args.headless,
    )
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)
    _log(f"Wrote {len(jobs)} HiringCafe jobs to {args.output}")
