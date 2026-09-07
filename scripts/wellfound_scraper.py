#!/usr/bin/env python3
"""wellfound_scraper.py — Scrape Wellfound (ex-AngelList) job search pages.

No API key, no Apify actor, no login. Wellfound's SEO role pages ship the whole
result set inside the page's __NEXT_DATA__ blob, and each record already carries
the FULL job description. Two consequences worth knowing:

  * this source costs nothing to run (plain HTTP, no credits burned), and
  * Phase 2's Firecrawl call can be skipped for these jobs — the JD is already
    in the record under "description".

Each record also exposes `atsSource`, i.e. which real ATS the posting was
mirrored from (Ashby / Greenhouse / Lever / Workable), or None for a job that is
applied to natively on Wellfound.

Usage:
    python Scripts/wellfound_scraper.py --output Scripts/daily_report_wellfound.json
"""
import datetime
import json
import re
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

# Wellfound role slugs — only these five resolve for design work. Slugs it does
# NOT have (verified, all return an empty page): interaction-designer,
# visual-designer, ux-ui-designer, digital-designer.
ROLE_SLUGS = [
    "product-designer",
    "ux-designer",
    "ui-designer",
    "web-designer",
    "graphic-designer",
]

# City slugs, not provinces or countries — "canada" resolves to an empty page.
CITY_SLUGS = ["toronto", "vancouver", "montreal", "ottawa"]

BASE = "https://wellfound.com"
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

ATS_MAP = {
    "AtsIntegration::Ashby::Listing": "ASHBY",
    "AtsIntegration::Greenhouse::Listing": "GREENHOUSE",
    "AtsIntegration::Lever::Listing": "LEVER",
    "AtsIntegration::Workable::Listing": "WORKABLE",
}


def _log(msg):
    try:
        from daily_log import log
        log(msg)
    except Exception:
        print(msg)


def _fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-CA,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        _log(f"  Wellfound fetch failed {url}: {e}")
        return ""


def _apollo(html_text):
    """Pull the Apollo cache out of __NEXT_DATA__. {} when the page is a shell."""
    m = NEXT_DATA_RE.search(html_text)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
        return data["props"]["pageProps"]["apolloState"]["data"]
    except (ValueError, KeyError, TypeError):
        return {}


def _company_index(state):
    """job cache key -> company name/slug, walking StartupResult back-references."""
    index = {}
    for value in state.values():
        if not isinstance(value, dict) or value.get("__typename") != "StartupResult":
            continue
        for ref in value.get("highlightedJobListings") or []:
            key = ref.get("__ref") if isinstance(ref, dict) else None
            if key:
                index[key] = (value.get("name", ""), value.get("slug", ""))
    return index


# Wellfound is a global board, and its listings name their locations explicitly.
# The shared is_canada() treats a bare "Remote" as eligible, which on this source
# floods the report with Bangalore / Beirut / "Earth" roles the profile says to
# skip. So decide Canada scope here, off the structured location names, before
# anything reaches the shared filters.
CANADA_SCOPE = [
    "canada", "canadian", "ontario", "british columbia", "alberta", "quebec",
    "québec", "nova scotia", "new brunswick", "manitoba", "saskatchewan",
    "newfoundland", "toronto", "ottawa", "vancouver", "montreal", "montréal",
    "calgary", "edmonton", "winnipeg", "halifax", "waterloo", "kitchener",
    "mississauga", "victoria", "north america",
]


def _in_canada_scope(job) -> bool:
    names = list(job.get("locationNames") or []) + \
            list(job.get("acceptedRemoteLocationNames") or [])
    blob = " ".join(names).lower()
    return any(t in blob for t in CANADA_SCOPE)


def _location_str(job):
    """One location string the shared is_canada / is_remote_or_ottawa filters can read."""
    names = list(job.get("locationNames") or [])
    names += list(job.get("acceptedRemoteLocationNames") or [])
    config = job.get("remoteConfig") or {}
    if job.get("remote") or config.get("kind") == "REMOTE":
        names.append("Remote")
    elif config.get("wfhFlexible"):
        names.append("Hybrid")
    seen, out = set(), []
    for n in names:
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return ", ".join(out)


def _posted_date(job):
    ts = job.get("liveStartAt")
    if not ts:
        return ""
    try:
        return datetime.date.fromtimestamp(int(ts)).isoformat()
    except (ValueError, OSError, OverflowError):
        return ""


def parse_page(html_text, canada_only=True):
    """__NEXT_DATA__ blob -> job dicts in the shape daily_auto_apply expects."""
    state = _apollo(html_text)
    if not state:
        return []
    companies = _company_index(state)
    jobs = []
    for key, value in state.items():
        if not key.startswith("JobListingSearchResult:"):
            continue
        if canada_only and not _in_canada_scope(value):
            continue
        company, company_slug = companies.get(key, ("", ""))
        description = value.get("description") or ""
        job_id = value.get("id") or key.split(":", 1)[1]
        slug = value.get("slug") or ""
        jobs.append({
            "title":       value.get("title", ""),
            "company":     company,
            "location":    _location_str(value),
            "salary":      value.get("compensation") or "",
            "snippet":     description[:400],
            "url":         f"{BASE}/jobs/{job_id}-{slug}" if slug else f"{BASE}/jobs/{job_id}",
            "age_str":     _posted_date(value),
            "source":      "wellfound",
            "job_key":     f"wellfound-{job_id}",
            "apply_type":  "WELLFOUND",
            # Wellfound-only extras
            "description":   description,   # full JD — Phase 2 can skip Firecrawl
            "ats_source":    ATS_MAP.get(value.get("atsSource"), ""),
            "job_type":      value.get("jobType", ""),
            "company_slug":  company_slug,
            "years_min":     value.get("yearsExperienceMin"),
            "primary_role":  value.get("primaryRoleTitle", ""),
        })
    return jobs


def search_wellfound(roles=None, cities=None, include_remote=True, delay=0.8,
                     canada_only=True):
    """Sweep role x city SEO pages plus the remote page for each role."""
    roles = roles or ROLE_SLUGS
    cities = cities or CITY_SLUGS
    urls = [f"{BASE}/role/l/{r}/{c}" for r in roles for c in cities]
    if include_remote:
        urls += [f"{BASE}/role/r/{r}" for r in roles]

    by_key, pages_ok = {}, 0
    for url in urls:
        page = _fetch(url)
        found = parse_page(page, canada_only=canada_only) if page else []
        if found:
            pages_ok += 1
        for job in found:
            by_key.setdefault(job["job_key"], job)   # same job appears on several pages
        time.sleep(delay)

    jobs = list(by_key.values())
    _log(f"Wellfound: {len(jobs)} unique jobs from {pages_ok}/{len(urls)} pages with results")
    return jobs


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="Scripts/daily_report_wellfound.json")
    parser.add_argument("--roles", help="comma-separated role slugs")
    parser.add_argument("--cities", help="comma-separated city slugs")
    parser.add_argument("--no-remote", action="store_true")
    parser.add_argument("--worldwide", action="store_true",
                        help="keep jobs with no Canada/North America location")
    args = parser.parse_args()

    jobs = search_wellfound(
        roles=args.roles.split(",") if args.roles else None,
        cities=args.cities.split(",") if args.cities else None,
        include_remote=not args.no_remote,
        canada_only=not args.worldwide,
    )
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)
    _log(f"Wrote {len(jobs)} Wellfound jobs to {args.output}")
