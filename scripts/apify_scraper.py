"""apify_scraper.py — Scrape Indeed CA + LinkedIn Jobs via Apify."""
import json, os, re, time
from datetime import timedelta
from apify_client import ApifyClient
from daily_log import log, load_profile
from role_filter import verdict

# Whether the last scrape was degraded rather than merely empty. "Apify is out
# of credit" and "Apify found nothing today" used to produce the same empty list
# and the same log line, so a dead source looked like a quiet market.
_STATUS = {"quota_exceeded": False, "error": "", "calls": 0, "failures": 0}

# Substrings Apify uses when the account cannot run actors at all.
_QUOTA_SIGNS = ("hard limit", "usage limit", "monthly usage", "limit exceeded",
                "forbidden", "payment required", "insufficient credit",
                "quota", "not enough")


def reset_status():
    _STATUS.update({"quota_exceeded": False, "error": "", "calls": 0, "failures": 0})


def last_status() -> dict:
    return dict(_STATUS)


def _note_failure(exc) -> None:
    msg = str(exc)
    _STATUS["failures"] += 1
    _STATUS["error"] = msg
    if any(s in msg.lower() for s in _QUOTA_SIGNS):
        _STATUS["quota_exceeded"] = True
        log("  APIFY UNAVAILABLE - this is not an empty result, the account "
            f"cannot run actors at all: {msg[:160]}")
    else:
        log(f"  Apify call failed: {msg[:160]}")


def _run_actor(client, actor_id: str, run_input: dict, timeout_s: int = 120) -> list:
    """Run an actor and return its dataset items.

    Separated out so the tests can stand in for it. Every call is real money on
    a $5/month plan.
    """
    _STATUS["calls"] += 1
    run = client.actor(actor_id).call(run_input=run_input,
                                      run_timeout=timedelta(seconds=timeout_s))
    return list(client.dataset(run["defaultDatasetId"]).iterate_items())


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

def filter_roles_verbose(jobs: list, drop_senior: bool = False) -> tuple:
    """(kept, dropped). Dropped rows carry drop_reason, so phase 1 can say why
    the pool shrank instead of just reporting a smaller number.

    Delegates to role_filter.verdict - the gate board_sweep.py and cloud_scan.py
    already use. SKIP_TITLES below is not the gate any more: run over the 67
    distinct titles in the recent pool it matched 0 of them. It looks for "staff
    designer" while the real title is "Staff Product Designer".

    Seniority is NOT a drop reason. Sanket's rule, 2026-09-13: he is not hunting
    senior roles specifically, but if he is eligible then why not, and he wants
    every design discipline in the net. A title is a bad proxy for eligibility -
    "Senior Product Designer" at a startup can ask for 3 years while "Product
    Designer" at a bank asks for 8 - so eligibility is judged in phase 3 by
    experience_gate.py, which reads the number the posting actually states.

    What still drops here: roles that are not design at all (tester, engineer,
    sales, retail floor), and internships in either language.

    Location is judged separately by filter_canada, so this pass only reads the
    title.
    """
    kept, dropped = [], []
    for j in jobs:
        keep, why = verdict(j.get("title", ""), location=None, require_canada=False)
        if keep and drop_senior and why == "senior":
            keep, why = False, "senior (drop_senior was asked for explicitly)"
        (kept if keep else dropped).append(j if keep else {**j, "drop_reason": why})
    return kept, dropped


def filter_roles(jobs: list) -> list:
    return filter_roles_verbose(jobs)[0]

def scrape_indeed(client: ApifyClient, term: str, max_items: int = 50) -> list:
    log(f"  Apify Indeed: '{term}'")
    try:
        items = _run_actor(client, "borderline/indeed-scraper", {
            "country": "ca",
            "query": term,
            "location": "Canada",
            "maxRows": max_items,
        })
        jobs = []
        for item in items:
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
        _note_failure(e)
        return []

def scrape_linkedin(client: ApifyClient, term: str, max_items: int = 50) -> list:
    log(f"  Apify LinkedIn: '{term}'")
    try:
        search_url = (
            "https://www.linkedin.com/jobs/search/?"
            f"keywords={term.replace(' ', '%20')}&location=Canada"
        )
        items = _run_actor(client, "curious_coder/linkedin-jobs-scraper", {
            "urls": [search_url],
            "count": max(max_items, 10),
        })
        jobs = []
        for item in items:
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
        _note_failure(e)
        return []

def scrape_all(search_terms: list, max_per_term: int = 50) -> list:
    profile = load_profile()
    apify_token = profile.get("apify_token")
    if not apify_token:
        log("Warning: Apify token not configured (no env var, no secrets.local.json)")
        return []
    reset_status()
    client  = ApifyClient(apify_token)
    all_jobs = []
    for term in search_terms:
        all_jobs.extend(scrape_indeed(client, term, max_per_term))
        all_jobs.extend(scrape_linkedin(client, term, max_per_term))
        time.sleep(1)

    in_canada = filter_canada(all_jobs)
    filtered, dropped = filter_roles_verbose(in_canada)

    reasons = {}
    for d in dropped:
        reasons[d["drop_reason"]] = reasons.get(d["drop_reason"], 0) + 1
    log(f"Apify total after filters: {len(filtered)} / {len(all_jobs)} raw "
        f"({len(all_jobs) - len(in_canada)} outside Canada, {len(dropped)} off-band)")
    for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        log(f"    dropped {n:3d} - {reason}")

    if _STATUS["quota_exceeded"]:
        log("Apify returned NOTHING because the account is over its monthly "
            "limit. Today's pool is missing its largest source - treat a small "
            "pool as a broken run, not a quiet market.")
    return filtered

if __name__ == "__main__":
    import argparse
    from daily_log import init_log, load_profile, log
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="Scripts/daily_report.json")
    # Was 5, which capped the whole day at 7 terms x (5 Indeed + 10 LinkedIn)
    # = 105 postings before any filtering. Five rows per search is whatever the
    # board ranked first, which skews to big-company senior posts.
    #
    # Only doubled, not raised further: this account is the FREE plan with $5 of
    # monthly credit and it exhausted that credit in under two weeks at 5. Extra
    # volume should come from board_sweep.py, which reads 3,449 postings off real
    # ATS boards for nothing. Raise this only on a paid plan.
    parser.add_argument("--max", type=int, default=10)
    args = parser.parse_args()
    init_log()
    profile = load_profile()
    terms = profile.get("target_roles", ["Product Designer"])
    jobs = scrape_all(terms, max_per_term=args.max)
    import json
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)
    log(f"Wrote {len(jobs)} jobs to {args.output}")
