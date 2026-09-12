#!/usr/bin/env python3
"""apply_target.py — Where should this job actually be applied to?

`detect_ats()` matches strings in the job's URL, which is why a Loblaw posting
on `careers.loblaw.ca` routes to DIRECT and the Workday adapter — the one that
handles account creation and multi-step forms — is never called at all. It is
also why 53 LinkedIn links and 35 career-site front doors sit in the backlog
unapplied: the URL the job was *found* at is not the URL it can be *submitted*
at, and nothing in the pipeline knew the difference.

This decides that separately. Given a job, it answers with one of:

    SUBMIT   an ATS the adapters drive, with the URL to drive
    MANUAL   real job, no automatable path, a human finishes it
    SKIP     a surface we refuse to source from at all

The resolver's cache makes this cheap — no network for a company already seen.

Usage:
    from apply_target import target_for
    t = target_for({"company": "Asana", "url": "https://asana.com/careers/...",
                    "title": "Product Designer"})
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ats_resolver                                     # noqa: E402
from ats_resolver import BOARDS, UNSUBMITTABLE, from_url  # noqa: E402

# ATSs the adapters drive without a human. Anything outside this set is MANUAL
# even when we can see the posting, because a queue item that always fails is
# worse than one that was never queued.
DRIVABLE = {"greenhouse", "lever", "ashby", "workable"}

# Surfaces to stop sourcing entirely. Each one has been measured failing:
# jobbank has no API, LinkedIn's Easy Apply button is absent on most postings,
# Workday hides behind Paradox/Phenom widgets in shadow DOM.
SKIP_SURFACES = {
    "jobbank.gc.ca": "government portal, no API and no automatable form",
    "linkedin.com": "Easy Apply absent on most postings",
    "indeed.com": "CAPTCHA and no stable apply path",
    "myworkdayjobs.com": "multi-step behind account creation",
    "taleo": "no automatable path",
    "icims": "no automatable path",
}


def _skip_reason(url):
    u = (url or "").lower()
    for host, why in SKIP_SURFACES.items():
        if host in u:
            return why
    return None


def target_for(job, cache=None, allow_network=True):
    """Decide where *job* gets applied to.

    job needs `company`; `url` and `title` are used when present.
    """
    company = job.get("company") or job.get("co") or ""
    url = job.get("url") or job.get("apply_url") or ""
    title = job.get("title") or job.get("role") or ""

    # 1. The URL is already a board we drive. Nothing to resolve.
    hit = from_url(url)
    if hit and hit[0] in DRIVABLE:
        return {"action": "SUBMIT", "ats": hit[0], "slug": hit[1],
                "url": url, "via": "url", "company": company, "title": title}

    # 2. Does this company have a board, even though the link does not point at it?
    #    This is the Asana case: CAPTCHA-blocked at asana.com while
    #    greenhouse/asana served 103 jobs over an open API.
    cache = ats_resolver.load_cache() if cache is None else cache
    key = ats_resolver.key(company)
    entry = cache.get(key)
    if entry is None and allow_network and company:
        entry = ats_resolver.resolve(company, url, cache=cache)
    if entry and entry.get("ats") in DRIVABLE:
        return {"action": "SUBMIT", "ats": entry["ats"], "slug": entry["slug"],
                "url": entry.get("board") or url, "via": "resolver",
                "company": company, "title": title,
                "note": "found at a different URL than it was sourced from"
                        if url and not from_url(url) else ""}

    # 3. Nothing automatable. Is it worth a human, or not worth sourcing?
    why = _skip_reason(url)
    if why:
        return {"action": "SKIP", "reason": why, "url": url,
                "company": company, "title": title}
    return {"action": "MANUAL", "reason": (entry or {}).get("note") or "no public board",
            "url": url, "company": company, "title": title}


def summarise(jobs, allow_network=False):
    """Counts by action, for sizing a change before making it."""
    cache = ats_resolver.load_cache()
    out = {"SUBMIT": [], "MANUAL": [], "SKIP": []}
    for j in jobs:
        t = target_for(j, cache=cache, allow_network=allow_network)
        out[t["action"]].append(t)
    return out


if __name__ == "__main__":
    import json
    sys.path.insert(0, HERE)
    import build_tracker as bt

    rows = [{"company": r["company"], "url": r["url"], "title": r["role"],
             "status": r["status"]} for r in bt.scan()]
    todo = [r for r in rows if r["status"] == "Not Applied"]
    res = summarise(todo)

    print(f"{len(todo)} never-applied jobs\n")
    for action in ("SUBMIT", "MANUAL", "SKIP"):
        print(f"  {action:7} {len(res[action])}")
    print("\nSUBMIT — automatable today:")
    for t in res["SUBMIT"][:30]:
        print(f"   {t['company'][:24]:26} {t['ats']:11}/{t['slug'][:22]:24} via {t['via']}")
    import collections
    print("\nSKIP — stop sourcing these:")
    for why, n in collections.Counter(t["reason"] for t in res["SKIP"]).most_common():
        print(f"   {n:4}  {why}")
