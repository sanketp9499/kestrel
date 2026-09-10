#!/usr/bin/env python3
"""pull_queue.py — The laptop's side of the split.

The cloud scan queues roles it has sourced, scored and deduped. This pulls that
queue down, turns it into the `Scripts/daily_report.json` the local phases
already expect, and pushes the refreshed dedup memory back so tomorrow's scan
knows what the tracker knows.

Nothing personal travels upward except normalised URLs and company|role keys:
the resume, the tracker, the documents and every application folder stay here.

Run this before the local apply run:

    python Scripts/pull_queue.py                    # fetch, convert, push seen
    python Scripts/pull_queue.py --no-push          # fetch and convert only
    python Scripts/pull_queue.py --date 2026-09-10  # a specific day's queue
"""
import argparse
import datetime
import glob
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import scan_state                       # noqa: E402
from daily_log import log               # noqa: E402

DEFAULT_REPO = os.environ.get("KESTREL_SCAN_REPO",
                              r"C:\Users\Sanket\Projects\kestrel-scan")
REPORT_OUT = os.path.join(HERE, "daily_report.json")


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo, *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r.stdout.strip()


def newest_queue(repo, date=None):
    if date:
        p = os.path.join(repo, "queue", f"{date}.json")
        return p if os.path.exists(p) else None
    files = sorted(glob.glob(os.path.join(repo, "queue", "*.json")))
    return files[-1] if files else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--date", help="Queue file to consume (default: newest)")
    ap.add_argument("--no-pull", action="store_true")
    ap.add_argument("--no-push", action="store_true",
                    help="Skip exporting the tracker back to seen.json")
    a = ap.parse_args()

    if not os.path.isdir(os.path.join(a.repo, ".git")):
        raise SystemExit(f"not a git repo: {a.repo}\n"
                         "Set KESTREL_SCAN_REPO or pass --repo.")

    if not a.no_pull:
        log(f"pulling {a.repo}")
        git(a.repo, "pull", "--ff-only")

    qpath = newest_queue(a.repo, a.date)
    if not qpath:
        log("no queue file found - has the scan run yet?")
        return 1

    with io.open(qpath, encoding="utf-8") as f:
        q = json.load(f)

    if q.get("consumed"):
        log(f"{os.path.basename(qpath)} was already consumed on "
            f"{q.get('consumedAt')}. Pass --date to force an older one.")
        return 1

    jobs = q.get("jobs", [])
    log(f"{os.path.basename(qpath)}: {len(jobs)} roles queued by the scan")

    by_type = {}
    for j in jobs:
        by_type.setdefault(j.get("apply_type", "unknown"), []).append(j)
    for t, lst in sorted(by_type.items(), key=lambda x: -len(x[1])):
        log(f"    {t:22s} {len(lst)}")

    # The local phases read daily_report.json. Hand them exactly that shape so
    # nothing downstream has to learn about the split.
    report = {
        "date": q.get("date"),
        "source": "cloud-scan",
        "queue_file": os.path.relpath(qpath, a.repo).replace("\\", "/"),
        "total_new": len(jobs),
        "by_type": {k: len(v) for k, v in by_type.items()},
        "jobs": jobs,
    }
    with io.open(REPORT_OUT, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    log(f"wrote {REPORT_OUT}")

    q["consumed"] = True
    q["consumedAt"] = datetime.datetime.now().isoformat(timespec="seconds")
    with io.open(qpath, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(q, indent=1, ensure_ascii=False) + "\n")

    if not a.no_push:
        # Union, never replace. A role sits in the queue before it reaches the
        # tracker, so a straight tracker export would forget everything the
        # cloud just queued and re-offer all of it tomorrow.
        p, nu, nk = scan_state.export_from_tracker(a.repo)
        log(f"seen.json now holds {nu} urls, {nk} keys "
            f"(tracker union queued)")
        git(a.repo, "add", "state", "queue")
        if git(a.repo, "status", "--porcelain"):
            git(a.repo, "commit", "-q", "-m",
                f"Laptop consumed {q.get('date')} queue ({len(jobs)} roles)")
            git(a.repo, "push", "-q")
            log("pushed")
        else:
            log("nothing to push")

    return 0


if __name__ == "__main__":
    sys.exit(main())
