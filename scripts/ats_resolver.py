#!/usr/bin/env python3
"""ats_resolver.py — Map a company to the ATS board you can actually submit to.

The pipeline's board lists were hardcoded company slugs written months ago:
11 of 13 Lever slugs and 10 of 17 Greenhouse slugs now 404, so the only source
that can auto-submit was being fed from a dead list. Meanwhile 53 jobs sat on
LinkedIn URLs the bot cannot submit to and 35 behind company career-site front
doors, several of which turned out to have a clean public API the whole time:
Asana sat in the CAPTCHA-blocked pile while its Greenhouse board served 103
jobs over an API that needs no account, no browser and no CAPTCHA.

So stop hardcoding and stop guessing from the job URL alone. Resolve the
company to its board once, cache it, and let the list grow itself.

Four boards, all public JSON, all submittable by the existing adapters:

    greenhouse  boards-api.greenhouse.io/v1/boards/{slug}/jobs
    lever       api.lever.co/v0/postings/{slug}?mode=json&state=published
    ashby       api.ashbyhq.com/posting-api/job-board/{slug}
    workable    apply.workable.com/api/v1/widget/accounts/{slug}?details=true

Resolution order, cheapest and most reliable first:

    1. the URL already names the ATS       (jobs.lever.co/fullscript -> fullscript)
    2. slug variants of the company name   (Asana -> asana)
    3. sniff the company's careers page    (finds the board it links out to)

Order matters because names lie: "Absorb Software" is `absorblms`, "GAIN" is
`thisisgain`, "Owner.com" is `owner`. Name-slugging alone resolved 6 of 20
companies in testing; the URL pass catches the ones it cannot.

Usage:
    python Scripts/ats_resolver.py --company "Asana"
    python Scripts/ats_resolver.py --company "Fullscript" --url https://jobs.lever.co/fullscript/abc
    python Scripts/ats_resolver.py --backfill        # every company in the tracker
    python Scripts/ats_resolver.py --report
"""
import argparse
import datetime
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CACHE_PATH = os.path.join(HERE, "ats_boards.json")
UA = "Mozilla/5.0 (compatible; kestrel-job-pipeline/1.0)"

# A hit is stable - boards do not move often. A miss is worth retrying sooner,
# because a company that had no board last month may have one now.
HIT_TTL_DAYS = 30
MISS_TTL_DAYS = 7

BOARDS = {
    "greenhouse": {
        "api": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        "count": lambda d: len(d.get("jobs", [])),
        "public": "https://boards.greenhouse.io/{slug}",
        "url_re": re.compile(
            r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)"),
    },
    "lever": {
        "api": "https://api.lever.co/v0/postings/{slug}?mode=json&state=published",
        "count": lambda d: len(d) if isinstance(d, list) else 0,
        "public": "https://jobs.lever.co/{slug}",
        "url_re": re.compile(r"jobs\.lever\.co/([A-Za-z0-9_-]+)"),
    },
    "ashby": {
        "api": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
        "count": lambda d: len(d.get("jobs", [])),
        "public": "https://jobs.ashbyhq.com/{slug}",
        "url_re": re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_-]+)"),
    },
    "workable": {
        # Insist the payload actually carries a jobs list. Under load this API
        # answers 200 with a body that has no `jobs` key at all, and a lenient
        # count read that as "0 jobs, board exists" - which is how a backfill
        # came back claiming Amazon, Autodesk and EA were all on Workable.
        "api": "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true",
        "count": lambda d: len(d["jobs"]) if isinstance(d, dict) and "jobs" in d else None,
        "public": "https://apply.workable.com/{slug}",
        "url_re": re.compile(r"apply\.workable\.com/([A-Za-z0-9_-]+)"),
    },
}

# Present so a caller can tell "no board" from "a board we deliberately refuse
# to drive". These are submittable by a human only; sourcing them produces a
# queue item that always fails, which is worse than not sourcing it.
UNSUBMITTABLE = re.compile(
    r"jobbank\.gc\.ca|linkedin\.com|indeed\.com|myworkdayjobs\.com|"
    r"taleo|icims|smartrecruiters\.com/[A-Za-z]+/job", re.I)

LEGAL_NOISE = re.compile(
    r"\b(inc|inc\.|ltd|ltd\.|llc|limited|corp|corp\.|corporation|company|co|"
    r"canada|technologies|technology|tech|labs|lab|group|holdings|solutions|"
    r"software|systems|digital|studio|studios|the|and)\b", re.I)


def _get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json, text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def load_cache():
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with io.open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f).get("boards", {})
    except (OSError, ValueError):
        return {}


def save_cache(boards):
    hits = sum(1 for v in boards.values() if v.get("ats"))
    payload = {
        "updated": datetime.datetime.now().isoformat(timespec="seconds"),
        "note": "Company -> ATS board map, grown by ats_resolver.py. Hits keep "
                "for %d days, misses are retried after %d." % (HIT_TTL_DAYS, MISS_TTL_DAYS),
        "counts": {"companies": len(boards), "resolved": hits},
        "boards": dict(sorted(boards.items())),
    }
    tmp = CACHE_PATH + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    os.replace(tmp, CACHE_PATH)


def key(company):
    return re.sub(r"[^a-z0-9]", "", str(company or "").lower())


def slug_variants(company):
    """Candidate slugs for a company name, most likely first."""
    raw = str(company or "").strip()
    if not raw:
        return []
    base = re.sub(r"[^\w\s-]", " ", raw.lower())
    stripped = LEGAL_NOISE.sub(" ", base)
    words = [w for w in re.split(r"[\s_-]+", stripped) if w]
    all_words = [w for w in re.split(r"[\s_-]+", base) if w]

    out = []
    for parts in (words, all_words):
        if not parts:
            continue
        out.append("".join(parts))          # spryPoint -> sprypoint
        out.append("-".join(parts))         # irth solutions -> irth-solutions
        if len(parts) > 1:
            out.append(parts[0])            # jane software -> jane
    seen, uniq = set(), []
    for s in out:
        if s and s not in seen and len(s) > 1:
            seen.add(s)
            uniq.append(s)
    return uniq[:6]


def from_url(url):
    """Pull (ats, slug) straight out of a URL that already names the board."""
    if not url:
        return None
    for ats, cfg in BOARDS.items():
        m = cfg["url_re"].search(url)
        if m:
            return ats, m.group(1)
    return None


def probe(ats, slug, timeout=8):
    """Job count for a board, or None when it does not exist."""
    cfg = BOARDS[ats]
    try:
        raw = _get(cfg["api"].format(slug=slug), timeout=timeout)
        return cfg["count"](json.loads(raw))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
        return None


def sniff_careers(url, timeout=10):
    """Fetch a page and look for a board it links out to.

    This is what gets past the front doors. A company careers page built on
    Phenom or Paradox has no form to fill, but it almost always links or
    iframes the real ATS somewhere in the markup.
    """
    if not url:
        return None
    try:
        html = _get(url, timeout=timeout).decode("utf-8", errors="replace")
    except Exception:
        return None
    for ats, cfg in BOARDS.items():
        m = cfg["url_re"].search(html)
        if m:
            return ats, m.group(1)
    return None


def _fresh(entry):
    ts = entry.get("checked")
    if not ts:
        return False
    try:
        age = (datetime.datetime.now() - datetime.datetime.fromisoformat(ts)).days
    except ValueError:
        return False
    return age < (HIT_TTL_DAYS if entry.get("ats") else MISS_TTL_DAYS)


def resolve(company, url=None, cache=None, use_cache=True, polite=0.3):
    """Return the board for *company*, or a miss record explaining why not."""
    cache = load_cache() if cache is None else cache
    k = key(company)
    if use_cache and k in cache and _fresh(cache[k]):
        hit = dict(cache[k])
        hit["method"] = hit.get("method", "?") + "+cache"
        return hit

    def record(ats=None, slug=None, jobs=None, method="none", note=""):
        entry = {"company": company, "ats": ats, "slug": slug, "jobs": jobs,
                 "method": method, "note": note,
                 "checked": datetime.datetime.now().isoformat(timespec="seconds")}
        if ats:
            entry["board"] = BOARDS[ats]["public"].format(slug=slug)
        cache[k] = entry
        return entry

    # 1. the URL already names the board
    hit = from_url(url)
    if hit:
        ats, slug = hit
        n = probe(ats, slug)
        if n is not None:
            return record(ats, slug, n, "url")

    # 2. slug variants of the name.
    #
    # A name match needs postings to count. The URL pass can accept an empty
    # board because the URL already proves it is the right company; a name
    # match has no such proof, and an empty board is exactly what a wrong guess
    # looks like. "Big Blue Bubble" matching an empty `big` account is not a
    # resolution, it is a coincidence, and acting on it wastes an apply attempt.
    empty = None
    for slug in slug_variants(company):
        for ats in BOARDS:
            n = probe(ats, slug)
            time.sleep(polite)
            if n:
                return record(ats, slug, n, "name")
            if n == 0 and empty is None:
                empty = (ats, slug)

    # 3. sniff whatever page we do have
    if url and not UNSUBMITTABLE.search(url):
        hit = sniff_careers(url)
        if hit:
            ats, slug = hit
            n = probe(ats, slug)
            if n is not None:
                return record(ats, slug, n, "careers-page")

    if empty:
        # Recorded, not returned as a hit: worth retrying after MISS_TTL, since
        # a real company's board is often just empty this week.
        return record(note=f"matched an empty {empty[0]} board ({empty[1]}), "
                           f"no postings to submit to")
    why = "on a surface we do not drive" if (url and UNSUBMITTABLE.search(url)) \
        else "no public board found"
    return record(note=why)


def backfill(limit=None, polite=0.3):
    """Resolve every company the tracker knows about and report the coverage."""
    import build_tracker as bt
    rows = bt.scan()
    seen, targets = set(), []
    for r in rows:
        k = key(r["company"])
        if not k or k in seen:
            continue
        seen.add(k)
        targets.append(r)
    if limit:
        targets = targets[:limit]

    cache = load_cache()
    resolved = before = 0
    print(f"resolving {len(targets)} companies "
          f"({sum(1 for t in targets if _fresh(cache.get(key(t['company']), {})))} already cached)\n")
    for i, r in enumerate(targets, 1):
        cached = key(r["company"]) in cache and _fresh(cache[key(r["company"])])
        e = resolve(r["company"], r["url"], cache=cache, polite=polite)
        if e.get("ats"):
            resolved += 1
            if not cached:
                print(f"  [{i:3}/{len(targets)}] {r['company'][:28]:30} -> "
                      f"{e['ats']}/{e['slug']} ({e['jobs']} jobs) via {e['method']}")
        before += 1 if (r["url"] and not UNSUBMITTABLE.search(r["url"])
                        and from_url(r["url"])) else 0
        if i % 25 == 0:
            save_cache(cache)
    save_cache(cache)

    print(f"\n  companies                          {len(targets)}")
    print(f"  had a submittable URL already      {before}")
    print(f"  now resolve to an ATS board        {resolved}")
    print(f"  coverage                           {100.0*resolved/len(targets):.0f}%")
    return resolved, len(targets)


def report():
    cache = load_cache()
    hits = {k: v for k, v in cache.items() if v.get("ats")}
    by_ats, by_method = {}, {}
    jobs = 0
    for v in hits.values():
        by_ats[v["ats"]] = by_ats.get(v["ats"], 0) + 1
        m = v.get("method", "?").replace("+cache", "")
        by_method[m] = by_method.get(m, 0) + 1
        jobs += v.get("jobs") or 0
    print(f"cache: {len(cache)} companies, {len(hits)} with a board")
    print(f"  open postings on those boards: {jobs}")
    print("  by ats:    " + ", ".join(f"{k}={v}" for k, v in sorted(by_ats.items())))
    print("  resolved by: " + ", ".join(f"{k}={v}" for k, v in sorted(by_method.items())))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--company")
    ap.add_argument("--url")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()

    if a.report:
        report()
    elif a.backfill:
        backfill(limit=a.limit)
    elif a.company:
        cache = load_cache()
        e = resolve(a.company, a.url, cache=cache, use_cache=not a.no_cache)
        save_cache(cache)
        print(json.dumps(e, indent=2))
    else:
        ap.error("need --company, --backfill or --report")
