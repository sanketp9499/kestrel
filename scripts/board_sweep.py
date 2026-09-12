#!/usr/bin/env python3
"""board_sweep.py — Source jobs from boards that can be submitted to.

The principle the rest of the pipeline was missing: **never source a job you
cannot submit to.** Sourcing from LinkedIn and Indeed produced a queue where 53
of 135 items had no Easy Apply button and 35 sat behind career-site widgets, so
the pile grew and the applied count did not.

This sweeps the boards `ats_resolver` has mapped — Greenhouse, Lever, Ashby and
Workable — over their public JSON APIs. No browser, no login, no CAPTCHA, no
front door. Every job it returns carries a direct apply URL on an ATS the
adapters already drive, so the queue is submittable by construction rather than
by hope.

LinkedIn, Indeed and Wellfound keep their job: they are good at telling you
*which companies* are hiring designers in Canada. Feed those names to
`ats_resolver --backfill` and the board list grows itself.

Usage:
    python Scripts/board_sweep.py                    # what is out there today
    python Scripts/board_sweep.py --repo <scan repo> # dedup + write a queue
    python Scripts/board_sweep.py --json
"""
import argparse
import datetime
import io
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ats_resolver                      # noqa: E402
import role_filter                       # noqa: E402
from ats_resolver import BOARDS          # noqa: E402

UA = "Mozilla/5.0 (compatible; kestrel-job-pipeline/1.0)"


def _fetch(ats, slug, timeout=20):
    try:
        req = urllib.request.Request(BOARDS[ats]["api"].format(slug=slug),
                                     headers={"User-Agent": UA})
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except Exception:
        return None


def _normalise(ats, slug, company, data):
    """One shape out of four APIs. Apply URL is the point: it is what makes
    this job submittable, and it is never the URL the job was found at."""
    if data is None:
        return []
    out = []
    if ats == "lever":
        for j in (data if isinstance(data, list) else []):
            cats = j.get("categories") or {}
            out.append({
                "title": j.get("text", ""),
                "location": cats.get("location") or "",
                "team": cats.get("team") or cats.get("department") or "",
                "url": j.get("hostedUrl") or "",
                "apply_url": j.get("applyUrl") or j.get("hostedUrl") or "",
                "job_id": j.get("id", ""),
                "posted": j.get("createdAt"),
            })
        return _tag(out, ats, slug, company)

    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    if ats == "greenhouse":
        for j in jobs:
            out.append({
                "title": j.get("title", ""),
                "location": (j.get("location") or {}).get("name", ""),
                "team": "",
                "url": j.get("absolute_url", ""),
                "apply_url": j.get("absolute_url", ""),
                "job_id": str(j.get("id", "")),
                "posted": j.get("first_published") or j.get("updated_at"),
            })
    elif ats == "ashby":
        for j in jobs:
            if j.get("isListed") is False:
                continue
            out.append({
                "title": j.get("title", ""),
                "location": j.get("location") or "",
                "team": j.get("team") or j.get("department") or "",
                "url": j.get("jobUrl", ""),
                "apply_url": j.get("applyUrl") or j.get("jobUrl", ""),
                "job_id": j.get("id", ""),
                "posted": j.get("publishedAt"),
            })
    elif ats == "workable":
        for j in jobs:
            loc = " ".join(str(j.get(k) or "") for k in ("city", "state", "country")).strip()
            out.append({
                "title": j.get("title", ""),
                "location": loc,
                "team": j.get("department") or "",
                "url": j.get("url") or j.get("shortlink") or "",
                "apply_url": j.get("application_url") or j.get("url") or "",
                "job_id": j.get("code") or j.get("shortcode") or "",
                "posted": j.get("published_on") or j.get("created_at"),
            })
    return _tag(out, ats, slug, company)


def _tag(rows, ats, slug, company):
    for r in rows:
        r["company"] = company
        r["ats"] = ats
        r["slug"] = slug
        r["apply_type"] = ats.upper()
        r["source"] = "board"
    return rows


def sweep(require_canada=True, include_senior=True):
    """Every design role on every mapped board, with why each drop happened."""
    cache = ats_resolver.load_cache()
    boards = [v for v in cache.values() if v.get("ats") and v.get("jobs")]
    kept, drops, scanned, dead = [], {}, 0, 0

    for b in boards:
        data = _fetch(b["ats"], b["slug"])
        if data is None:
            dead += 1
            continue
        for job in _normalise(b["ats"], b["slug"], b["company"], data):
            scanned += 1
            keep, why = role_filter.verdict(job["title"], job["location"],
                                            require_canada=require_canada)
            if not keep:
                drops[why] = drops.get(why, 0) + 1
                continue
            job["seniority"] = why
            if why == "senior" and not include_senior:
                drops["senior"] = drops.get("senior", 0) + 1
                continue
            kept.append(job)

    kept.sort(key=lambda j: ({"junior": 0, "mid": 1, "senior": 2}[j["seniority"]],
                             j["company"].lower()))
    return {"boards": len(boards), "unreachable": dead, "scanned": scanned,
            "kept": kept, "drops": drops}


def write_queue(result, repo):
    """Dedup against the shared memory and write a queue the laptop consumes."""
    import scan_state
    seen_urls, seen_keys = scan_state.load_sets(repo)
    from daily_auto_apply import normalize_job_url, company_role_key

    fresh = []
    for j in result["kept"]:
        u = normalize_job_url(j.get("url") or j.get("apply_url") or "")
        k = company_role_key(j.get("company", ""), j.get("title", ""))
        if (u and u in seen_urls) or (k and k in seen_keys):
            continue
        fresh.append(j)

    today = datetime.date.today().isoformat()
    qdir = os.path.join(repo, "queue")
    os.makedirs(qdir, exist_ok=True)
    path = os.path.join(qdir, f"{today}-boards.json")
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps({
            "date": today, "source": "board-sweep", "count": len(fresh),
            "consumed": False,
            "note": "Every entry carries a direct apply URL on an ATS the "
                    "adapters drive. Submittable by construction.",
            "jobs": fresh,
        }, indent=1, ensure_ascii=False) + "\n")
    scan_state.add(repo, fresh)
    return path, len(fresh)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", help="Scan repo to dedup against and write a queue into")
    ap.add_argument("--anywhere", action="store_true", help="Do not require Canada")
    ap.add_argument("--no-senior", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    r = sweep(require_canada=not a.anywhere, include_senior=not a.no_senior)
    if a.json:
        print(json.dumps(r, indent=1, ensure_ascii=False, default=str))
        sys.exit(0)

    print(f"  boards swept        {r['boards']}"
          + (f"  ({r['unreachable']} unreachable)" if r["unreachable"] else ""))
    print(f"  postings scanned    {r['scanned']}")
    print(f"  design roles kept   {len(r['kept'])}\n")
    for j in r["kept"]:
        print(f"   {j['seniority']:7} {j['company'][:20]:22} {j['title'][:46]:48} "
              f"{j['location'][:22]:24} {j['ats']}")
    print("\n  dropped:")
    for why, n in sorted(r["drops"].items(), key=lambda x: -x[1]):
        print(f"   {n:5}  {why}")

    if a.repo:
        p, n = write_queue(r, a.repo)
        print(f"\n  wrote {p}: {n} new after dedup")
