#!/usr/bin/env python3
"""weworkremotely_scraper.py — Scrape We Work Remotely via its RSS feeds.

The cleanest source in the whole pipeline: plain HTTP, no key, no login, no
Cloudflare, and a stable feed format. Each item carries custom fields most
boards never expose — region, country, state, skills, category, employment type,
expiry date, and the full HTML description.

    https://weworkremotely.com/categories/remote-design-jobs.rss   (design only)
    https://weworkremotely.com/remote-jobs.rss                     (everything)

**Read this before enabling it.** Every WWR listing is remote, and in practice
essentially all of them are posted as "Anywhere in the World" — 16 of 16 on the
design feed, 89 of 91 on the full feed. `profile.json` rule 2 says
"Canada ONLY - skip India remote, worldwide remote, or US-only", so the profile
as written rejects this entire source. That is why `canada_only=True` returns
almost nothing and why this is not wired into the daily run.

If worldwide-remote roles are acceptable (they are legal to apply to from
Canada; the practical catch is payroll and timezone, not eligibility), run with
--worldwide and the source becomes genuinely useful.

Usage:
    python Scripts/weworkremotely_scraper.py --worldwide --output Scripts/daily_report_wwr.json
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime

# Remote XML from a third party. defusedxml blocks entity-expansion and external
# entity attacks; the stdlib parser is the fallback when it is not installed
# (`pip install defusedxml` to close the gap).
try:
    import defusedxml.ElementTree as ET
    from xml.etree.ElementTree import ParseError
except ImportError:
    import xml.etree.ElementTree as ET
    from xml.etree.ElementTree import ParseError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

FEEDS = {
    "design": "https://weworkremotely.com/categories/remote-design-jobs.rss",
    "all": "https://weworkremotely.com/remote-jobs.rss",
}

# Regions a Canadian applicant can actually take.
CANADA_OK = re.compile(
    r"anywhere in the world|worldwide|north america|canada|americas", re.I)
CANADA_STRICT = re.compile(r"canada|toronto|vancouver|montreal|ottawa", re.I)

TAG_RE = re.compile(r"<[^>]+>")


def _log(msg):
    try:
        from daily_log import log
        log(msg)
    except Exception:
        print(msg)


def _fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        _log(f"  WWR fetch failed {url}: {e}")
        return b""


def _text(item, tag):
    el = item.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


def _split_title(raw):
    """WWR titles read "Company: Role"."""
    if ":" in raw:
        company, role = raw.split(":", 1)
        return company.strip(), role.strip()
    return "", raw.strip()


def _iso_date(pubdate):
    try:
        return parsedate_to_datetime(pubdate).date().isoformat()
    except Exception:
        return ""


def parse_feed(xml_bytes, canada_only=True, strict=False):
    if not xml_bytes:
        return []
    try:
        root = ET.fromstring(xml_bytes)
    except ParseError as e:
        _log(f"  WWR: feed did not parse: {e}")
        return []

    jobs = []
    for item in root.findall(".//item"):
        raw_title = _text(item, "title")
        if not raw_title:
            continue
        region = _text(item, "region")
        state = _text(item, "state")
        country = _text(item, "country")
        where = ", ".join(x for x in (region, state, country) if x)
        if canada_only:
            pattern = CANADA_STRICT if strict else CANADA_OK
            if not pattern.search(where):
                continue

        company, role = _split_title(raw_title)
        description = TAG_RE.sub(" ", _text(item, "description"))
        description = re.sub(r"\s+", " ", description).strip()
        link = _text(item, "link") or _text(item, "guid")
        jobs.append({
            "title":      role,
            "company":    company,
            "location":   where or "Remote",
            "salary":     "",
            "snippet":    description[:400],
            "url":        link,
            "age_str":    _iso_date(_text(item, "pubDate")),
            "source":     "weworkremotely",
            "job_key":    "wwr-" + (link.rsplit("/", 1)[-1] if link else raw_title[:40]),
            "apply_type": "DIRECT",
            # WWR-only extras
            "description":  description,   # full JD, so Phase 2 can skip Firecrawl
            "skills":       _text(item, "skills"),
            "wwr_category": _text(item, "category"),
            "job_type":     _text(item, "type"),
            "expires_at":   _iso_date(_text(item, "expires_at")),
        })
    return jobs


def search_wwr(feeds=None, canada_only=True, strict=False):
    feeds = feeds or ["design"]
    by_key = {}
    for name in feeds:
        url = FEEDS.get(name, name)
        for job in parse_feed(_fetch(url), canada_only=canada_only, strict=strict):
            by_key.setdefault(job["job_key"], job)
    jobs = list(by_key.values())
    _log(f"WWR: {len(jobs)} jobs from {len(feeds)} feed(s)"
         + (" (Canada-eligible only)" if canada_only else ""))
    return jobs


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="Scripts/daily_report_wwr.json")
    p.add_argument("--feeds", default="design", help="design, all, or both comma-separated")
    p.add_argument("--worldwide", action="store_true",
                   help="keep worldwide-remote roles (profile rule 2 skips them by default)")
    p.add_argument("--strict", action="store_true",
                   help="require Canada to be named explicitly, not just 'Anywhere'")
    args = p.parse_args()

    jobs = search_wwr(feeds=[f.strip() for f in args.feeds.split(",")],
                      canada_only=not args.worldwide, strict=args.strict)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)
    _log(f"Wrote {len(jobs)} We Work Remotely jobs to {args.output}")
