"""Drop postings that are already gone, before the pipeline spends on them.

A dead posting costs a Firecrawl extraction, two Claude document calls, a folder
and a tracker row before phase 5 discovers it. `ats_resolver.py` measured the
scale: 11 of 13 Lever slugs and 10 of 17 Greenhouse slugs were 404.

Two rules keep this from doing more harm than good:

  A non-200 is not proof of death. 403 and 429 mean a bot filter or a rate
  limit, and Cloudflare-fronted boards hand those to urllib constantly. Dropping
  them would quietly delete real jobs, which is a worse failure than the one
  being fixed. Only 404 and 410 are treated as gone.

  A 200 is not proof of life. Expired postings routinely return 200 with "no
  longer accepting applications" in the body. That phrase is checked for, but
  only in forms specific enough that a JD saying "applications close on Friday"
  or "closing the loop with stakeholders" survives.

Anything uncertain is kept. The cost of keeping a dead job is one wasted
document set; the cost of dropping a live one is a job Sanket never sees.
"""
import re
import urllib.error
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}

DEAD_STATUS = {404, 410}

# Deliberately whole phrases. "closed", "filled" and "expired" on their own
# appear in live job descriptions.
CLOSED_PHRASES = [
    r"no longer accepting applications?",
    r"no longer (?:be )?available",
    r"this (?:job|position|role|posting|opening) (?:has been|is|was) (?:closed|filled|removed|expired)",
    r"this (?:job|position|role|posting) is no longer",
    r"(?:job|position|role) (?:posting )?not found",
    r"(?:job|position|posting) has been filled",
    r"we are no longer (?:accepting|considering)",
    r"applications? (?:are|is) closed",
    r"this (?:job|posting|role) has expired",
    r"sorry,? this job",
    r"the (?:job|position) you(?:'re| are) looking for",
]
CLOSED_RE = re.compile("|".join(CLOSED_PHRASES), re.I)


def _fetch(url: str, timeout: int = 15):
    """(status, body). Raises on network failure; callers treat that as unknown."""
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def check_url(url: str, fetch=None, timeout: int = 15) -> tuple:
    """(alive, reason). Only a definite death returns False."""
    fetch = fetch or _fetch
    try:
        status, body = fetch(url, timeout=timeout)
    except Exception as e:
        return True, f"unreachable ({type(e).__name__}) - kept, timeout is not evidence"

    if status in DEAD_STATUS:
        return False, f"HTTP {status} - posting not found"
    if status != 200:
        return True, f"HTTP {status} - kept, not evidence the posting is gone"

    text = re.sub(r"<[^>]+>", " ", body or "")
    m = CLOSED_RE.search(text)
    if m:
        return False, f"page says the posting is closed: {m.group(0)[:60]!r}"
    return True, "HTTP 200"


def filter_alive(jobs: list, fetch=None, url_key: str = "url") -> tuple:
    """Split a job list into (kept, dropped). Dropped rows carry dead_reason.

    A job with no URL is kept: there is nothing to check, and guessing would
    delete it.
    """
    kept, dropped = [], []
    for job in jobs:
        url = (job.get(url_key) or job.get("apply_url") or "").strip()
        if not url:
            kept.append(job)
            continue
        alive, why = check_url(url, fetch=fetch)
        if alive:
            kept.append(job)
        else:
            dropped.append({**job, "dead_reason": why})
    return kept, dropped


if __name__ == "__main__":
    import argparse, io, json
    ap = argparse.ArgumentParser(description="Drop postings that are already gone")
    ap.add_argument("--input", required=True, help="JSON list of job records")
    ap.add_argument("--output", help="where to write the surviving jobs")
    ap.add_argument("--url-key", default="url")
    args = ap.parse_args()

    jobs = json.load(io.open(args.input, encoding="utf-8"))
    kept, dropped = filter_alive(jobs, url_key=args.url_key)
    for d in dropped:
        print(f"DROPPED  {str(d.get('company'))[:28]:28s} {d['dead_reason']}")
    print(f"{len(kept)} live, {len(dropped)} dead, of {len(jobs)}")
    if args.output:
        json.dump(kept, io.open(args.output, "w", encoding="utf-8"),
                  indent=2, ensure_ascii=False)
