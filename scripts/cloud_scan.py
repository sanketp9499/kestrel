#!/usr/bin/env python3
"""cloud_scan.py — The scan engine, built to run on a GitHub runner.

Kestrel's two engines were always separate; this is the half that can leave the
laptop. It sources, scores and dedups, then writes a queue the laptop picks up.
It never opens a browser, never signs in anywhere, never touches a resume and
never submits anything, so a datacenter IP and an ephemeral filesystem cost it
nothing.

Deliberately has no LLM in it. Sourcing and scoring are ordinary code, and the
agent was only ever needed for the tailoring and judgement calls in the local
phases. Dropping it makes the scheduled run deterministic, free of an API key,
and cheap.

Reads:   state/seen.json          (what has already been considered)
         scan_config.json         (search terms and filters; no personal data)
Writes:  queue/<date>.json        (new scored candidates, for the laptop)
         state/seen.json          (updated so tomorrow does not re-offer these)
         state/last_scan.json     (small run record for the status page)

Usage:
    python Scripts/cloud_scan.py --repo .            # full run
    python Scripts/cloud_scan.py --repo . --dry-run  # source and score, write nothing
"""
import argparse
import datetime
import io
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import scan_state                                    # noqa: E402
from daily_log import log                            # noqa: E402


def load_config(repo):
    """Search terms and filters. Falls back to the module defaults.

    Kept as its own file rather than reusing sanket_profile.json: the profile
    carries a phone number, an address and resume paths, none of which the
    scan needs and none of which should sit in a repo that a runner checks out.
    """
    p = os.path.join(repo, "scan_config.json")
    cfg = {}
    if os.path.exists(p):
        with io.open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    import daily_auto_apply as daa
    cfg.setdefault("search_terms", daa.SEARCH_TERMS)
    cfg.setdefault("max_per_term", daa.MAX_PER_TERM)
    cfg.setdefault("sources", ["apify", "wellfound", "greenhouse", "lever"])
    # The board sources return a company's whole careers page, not a filtered
    # search, so the first cloud run queued a Chief Technical Officer, four
    # Stripe product marketing roles and a Flutter developer. score_and_filter
    # ranks but does not reject, so the queue needs its own gate. An allowlist,
    # not a blocklist: the point is to hand the laptop design roles, and the
    # ways a title can fail to be one are unbounded.
    # The head term has to be a design one. Matching on "product" or "web"
    # alone let a Senior Product Manager through; matching on the discipline
    # keeps Brand Designer and UI Designer, which a score gate was throwing
    # away because score ranks relevance, it does not establish it.
    cfg.setdefault("title_must_match",
                   r"(\bdesign(er|ers)?\b|\bux\b|\bui\b|\bux/?ui\b|\bui/?ux\b"
                   r"|user experience|user interface|ux research)")
    # Zero by default: the title allowlist is the gate, and a real design role
    # that happens to score 0 is still a real design role.
    cfg.setdefault("min_score", 0)
    return cfg


def _source(name, fn, out, errors):
    """Run one source. A source that dies must not take the scan with it."""
    try:
        jobs = fn() or []
        log(f"  {name}: {len(jobs)} postings")
        out.extend(jobs)
        return len(jobs)
    except Exception as e:
        log(f"  {name}: FAILED, continuing without it - {e}")
        errors.append({"source": name, "error": str(e),
                       "trace": traceback.format_exc()[-800:]})
        return 0


def collect(cfg):
    """Every source that works without a signed-in browser."""
    jobs, errors, per_source = [], [], {}
    want = set(cfg["sources"])
    terms = cfg["search_terms"]
    n_before = 0

    if "apify" in want and os.environ.get("APIFY_TOKEN"):
        def _apify():
            from apify_scraper import scrape_all
            return scrape_all(terms, cfg["max_per_term"])
        per_source["apify"] = _source("Apify (Indeed + LinkedIn)", _apify, jobs, errors)
    elif "apify" in want:
        log("  Apify: skipped, no APIFY_TOKEN in the environment")
        errors.append({"source": "apify", "error": "APIFY_TOKEN not set"})

    if "wellfound" in want:
        def _wf():
            from wellfound_scraper import search_wellfound
            return search_wellfound()
        per_source["wellfound"] = _source("Wellfound", _wf, jobs, errors)

    if "greenhouse" in want:
        def _gh():
            from daily_auto_apply import search_greenhouse_boards
            return search_greenhouse_boards("")
        per_source["greenhouse"] = _source("Greenhouse boards", _gh, jobs, errors)

    if "lever" in want:
        def _lv():
            from daily_auto_apply import search_lever_boards
            return search_lever_boards("")
        per_source["lever"] = _source("Lever boards", _lv, jobs, errors)

    del n_before
    return jobs, per_source, errors


def gate(scored, cfg):
    """Split scored jobs into what the laptop should see and what it should not.

    Dropped roles are returned rather than discarded: a queue that silently
    shrinks is indistinguishable from a quiet day, and this project has already
    been bitten once by a number that could not tell those apart.
    """
    import re
    pat = re.compile(cfg["title_must_match"], re.I)
    floor = cfg["min_score"]
    keep, dropped = [], []
    for j in scored:
        title = j.get("title") or j.get("role") or ""
        if not pat.search(title):
            reason = "off-role"
        elif (j.get("score") or 0) < floor:
            reason = "low-score"
        else:
            keep.append(j)
            continue
        dropped.append({"reason": reason, "title": title,
                        "company": j.get("company", ""),
                        "score": j.get("score"),
                        "source": j.get("apply_type", "")})
    return keep, dropped


def run(repo, dry_run=False):
    started = datetime.datetime.now()
    today = datetime.date.today().isoformat()
    log(f"cloud scan {today} - repo {os.path.abspath(repo)}")

    cfg = load_config(repo)
    seen_urls, seen_keys = scan_state.load_sets(repo)
    log(f"  dedup memory: {len(seen_urls)} urls, {len(seen_keys)} company|role keys")

    jobs, per_source, errors = collect(cfg)
    log(f"  {len(jobs)} raw postings from {len(per_source)} sources")

    from daily_auto_apply import score_and_filter
    scored = score_and_filter(jobs, seen_urls, seen_keys)
    log(f"  {len(scored)} new after scoring and dedup")

    fresh, dropped = gate(scored, cfg)
    if dropped:
        log(f"  {len(dropped)} dropped by the queue gate "
            f"(min_score {cfg['min_score']}, title allowlist):")
        for d in dropped[:8]:
            log(f"      {d['reason']:11s} {d['title'][:52]}  [{d['company']}]")
        if len(dropped) > 8:
            log(f"      ... and {len(dropped) - 8} more, all listed in "
                f"state/last_scan.json")
    log(f"  {len(fresh)} queued for the laptop")

    by_type = {}
    for j in fresh:
        by_type.setdefault(j.get("apply_type", "unknown"), []).append(j)
    for t, lst in sorted(by_type.items(), key=lambda x: -len(x[1])):
        log(f"    {t:22s} {len(lst)}")

    elapsed = round((datetime.datetime.now() - started).total_seconds() / 60.0, 1)
    record = {
        "date": today,
        "startedAt": started.isoformat(timespec="seconds"),
        "minutes": elapsed,
        "raw": len(jobs),
        "scored": len(scored),
        "queued": len(fresh),
        "droppedByGate": len(dropped),
        "dropped": dropped,
        "gate": {"minScore": cfg["min_score"],
                 "titleMustMatch": cfg["title_must_match"]},
        "bySource": per_source,
        "byApplyType": {k: len(v) for k, v in by_type.items()},
        "errors": errors,
        "ranOn": "github-actions" if os.environ.get("GITHUB_ACTIONS") else "local",
    }

    if dry_run:
        log("  --dry-run: nothing written")
        print(json.dumps(record, indent=2))
        return record

    qdir = os.path.join(repo, "queue")
    os.makedirs(qdir, exist_ok=True)
    qpath = os.path.join(qdir, f"{today}.json")
    with io.open(qpath, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps({
            "date": today,
            "generatedAt": record["startedAt"],
            "count": len(fresh),
            "consumed": False,
            "jobs": fresh,
        }, indent=1, ensure_ascii=False) + "\n")
    log(f"  wrote {qpath}")

    # Fold the queue into the shared memory now, not after the laptop consumes
    # it. If the laptop is off for three days the scan still must not offer the
    # same eight roles three times.
    _, nu, nk = scan_state.add(repo, fresh)
    log(f"  dedup memory now {nu} urls, {nk} keys")

    spath = os.path.join(repo, "state", "last_scan.json")
    os.makedirs(os.path.dirname(spath), exist_ok=True)
    with io.open(spath, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(record, indent=1, ensure_ascii=False) + "\n")

    log(f"  scan complete in {elapsed} min")
    return record


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        rec = run(a.repo, a.dry_run)
    except Exception:
        log("cloud scan FAILED:\n" + traceback.format_exc())
        raise
    # A scan that sourced nothing at all is a failure worth failing the job for:
    # every source erroring looks identical to a quiet day otherwise.
    if rec["raw"] == 0:
        log("no postings from any source - failing so the run is not recorded green")
        sys.exit(2)
