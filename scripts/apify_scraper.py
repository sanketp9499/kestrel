"""apify_scraper.py — Scrape Indeed CA + LinkedIn Jobs via Apify."""
import json, os, re, time
from datetime import timedelta
from apify_client import ApifyClient
from daily_log import log, load_profile

CANADA_TERMS = [
    "ontario","british columbia","alberta","quebec","bc","on","ab","qc",
    "nova scotia","new brunswick","manitoba","saskatchewan",
    "toronto","ottawa","vancouver","calgary","montreal","edmonton",
    "winnipeg","halifax","canada","remote"
]

SKIP_TITLES = re.compile(
    r'\b(director|head of|vp |vice president|principal|staff designer'
    r'|game artist|fashion|interior|industrial|print designer)\b', re.I
)

def filter_canada(jobs: list) -> list:
    result = []
    for j in jobs:
        loc = (j.get("location") or "").lower()
        if any(t in loc for t in CANADA_TERMS):
            result.append(j)
    return result

def filter_roles(jobs: list) -> list:
    return [j for j in jobs if not SKIP_TITLES.search(j.get("title", ""))]

def scrape_indeed(client: ApifyClient, term: str, max_items: int = 50) -> list:
    log(f"  Apify Indeed: '{term}'")
    try:
        run = client.actor("borderline/indeed-scraper").call(run_input={
            "country": "ca",
            "query": term,
            "location": "Canada",
            "maxRows": max_items,
        }, run_timeout=timedelta(seconds=120))
        jobs = []
        for item in client.dataset(run.default_dataset_id).iterate_items():
            location = item.get("location") or {}
            salary = item.get("salary") or {}
            jobs.append({
                "title":      item.get("title", ""),
                "company":    item.get("companyName", ""),
                "location":   location.get("formattedAddressShort", "") or location.get("city", ""),
                "salary":     salary.get("salaryText", ""),
                "snippet":    (item.get("descriptionText") or "")[:400],
                "url":        item.get("jobUrl") or item.get("applyUrl", ""),
                "age_str":    item.get("age", "") or item.get("datePublished", ""),
                "source":     "apify-indeed",
                "job_key":    str(item.get("jobKey", "")),
                "apply_type": "",
            })
        log(f"    → {len(jobs)} results")
        return jobs
    except Exception as e:
        log(f"  Apify Indeed error: {e}")
        return []

def scrape_linkedin(client: ApifyClient, term: str, max_items: int = 50) -> list:
    log(f"  Apify LinkedIn: '{term}'")
    try:
        search_url = (
            "https://www.linkedin.com/jobs/search/?"
            f"keywords={term.replace(' ', '%20')}&location=Canada"
        )
        run = client.actor("curious_coder/linkedin-jobs-scraper").call(run_input={
            "urls": [search_url],
            "count": max(max_items, 10),
        }, run_timeout=timedelta(seconds=120))
        jobs = []
        for item in client.dataset(run.default_dataset_id).iterate_items():
            jobs.append({
                "title":      item.get("title", ""),
                "company":    item.get("companyName", ""),
                "location":   item.get("location", ""),
                "salary":     item.get("salary", "") or "",
                "snippet":    (item.get("descriptionText") or "")[:400],
                "url":        item.get("applyUrl") or item.get("link", ""),
                "age_str":    item.get("postedAt", ""),
                "source":     "apify-linkedin",
                "job_key":    str(item.get("id", "")),
                "apply_type": "LINKEDIN",
            })
        log(f"    → {len(jobs)} results")
        return jobs
    except Exception as e:
        log(f"  Apify LinkedIn error: {e}")
        return []

def scrape_all(search_terms: list, max_per_term: int = 50) -> list:
    profile = load_profile()
    apify_token = profile.get("apify_token")
    if not apify_token:
        log("Warning: Apify token not configured (no env var, no secrets.local.json)")
        return []
    client  = ApifyClient(apify_token)
    all_jobs = []
    for term in search_terms:
        all_jobs.extend(scrape_indeed(client, term, max_per_term))
        all_jobs.extend(scrape_linkedin(client, term, max_per_term))
        time.sleep(1)
    filtered = filter_roles(filter_canada(all_jobs))
    log(f"Apify total after filters: {len(filtered)} / {len(all_jobs)} raw")
    return filtered

if __name__ == "__main__":
    import argparse
    from daily_log import init_log, load_profile, log
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="Scripts/daily_report.json")
    parser.add_argument("--max", type=int, default=5)
    args = parser.parse_args()
    init_log()
    profile = load_profile()
    terms = profile.get("target_roles", ["Product Designer"])
    jobs = scrape_all(terms, max_per_term=args.max)
    import json
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)
    log(f"Wrote {len(jobs)} jobs to {args.output}")
