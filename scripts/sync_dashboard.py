#!/usr/bin/env python3
"""sync_dashboard.py — Publish the Command Center to a GitHub repo after each run.

The pipeline runs on this machine and the data lives on E:. GitHub cannot reach
either, so "live dashboard" means: rebuild locally, then push. This is the push
half. Run it at the end of run_daily_job.ps1 and the hosted dashboard is never
more than one pipeline run behind.

Two publishing modes, because the data decides where it may go:

  --mode private   Full dashboard, real companies and statuses. Pushes to a
                   PRIVATE repo. Serve it through Cloudflare Pages + Access (free,
                   gate it to your Google account) so it is reachable from a phone
                   but not by the public. GitHub Pages cannot do this: Pages sites
                   on a personal account are public even when the repo is private.

  --mode public    Telemetry only. Company names, roles, salaries, locations and
                   every document name are stripped before publishing; what remains
                   is the pipeline's own vital signs — run status, per-source health,
                   counts by stage, adapter list. Safe for the public kestrel repo,
                   and genuinely useful: it is proof the machine is running.

Usage:
    python Scripts/sync_dashboard.py --mode public  --repo "C:/Users/Sanket/Projects/kestrel"
    python Scripts/sync_dashboard.py --mode private --repo "C:/path/to/kestrel-live"
"""
import argparse
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_history        # noqa: E402  (needs HERE on the path first)
import telemetry_page     # noqa: E402

CC = os.path.join(HERE, "command_center")
BUILT = os.path.join(CC, "Job_Hunter_Command_Center.html")
SUPPORT = os.path.join(CC, "support.js")

DATA_RE = re.compile(r"(window\.__CC_DATA__\s*=\s*)(\{.*?\})(;?\s*</script>)", re.S)

# Long enough that a reader can see a pattern rather than a week of noise, short
# enough to stay legible as one column per day on a phone.
HISTORY_DAYS = 90


def log(msg):
    print(f"[sync] {msg}")


def rebuild():
    """Regenerate the dashboard from the current Applications/ state."""
    r = subprocess.run([sys.executable, os.path.join(HERE, "build_command_center.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"build_command_center.py failed:\n{(r.stderr or r.stdout)[-1500:]}")
    log((r.stdout or "").strip().splitlines()[0] if r.stdout else "rebuilt")


def read_payload(html):
    m = DATA_RE.search(html)
    if not m:
        raise SystemExit("could not find __CC_DATA__ in the built dashboard")
    return m, json.loads(m.group(2))


def redact(d):
    """Strip everything identifying, keep the pipeline's vital signs.

    Deliberately destructive: jobs, details, discover rows, documents, tasks,
    activity feed, resume defaults and settings are dropped wholesale rather than
    anonymised, because anonymised job rows are still a map of where someone
    applied. Only aggregate counts and infrastructure status survive.
    """
    counts = d.get("counts", {})
    stage_counts = {}
    for j in d.get("jobs", []):
        stage_counts[j.get("status", "?")] = stage_counts.get(j.get("status", "?"), 0) + 1

    auto = dict(d.get("automation", {}))
    auto.pop("lastAppliedDate", None)   # a date is a fact about the search, not the machine
    # The scheduler entry carries a machine-local task name; publish the cadence only.
    if auto.get("scheduledTime"):
        auto["scheduledTime"] = re.sub(r"\s*\([^)]*\)", "", auto["scheduledTime"]).strip()

    return {
        "mode": "telemetry",
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        "counts": counts,
        "byStage": stage_counts,
        "totalTracked": len(d.get("jobs", [])),
        "sources": [{k: s.get(k) for k in ("id", "name", "glyph", "color", "synced", "health")}
                    for s in d.get("sources", [])],
        "automation": auto,
        # The run record is machine history, not search history: dates the
        # scheduler fired and how long each run took. It carries nothing about
        # which jobs were touched, so it is safe on the public side and it is
        # the only thing that makes the green lights above mean anything.
        "history": run_history.history(days=HISTORY_DAYS),
        "note": "Telemetry only. Company names, roles, salaries and documents are "
                "removed before publishing. See the repo README for how the pipeline works.",
    }


def write_telemetry_page(out_dir, tel):
    """Write the public status surface: the JSON feed and the page over it.

    The page itself lives in telemetry_page.py. It is regenerated on every run,
    so the design has to live in the generator — editing docs/status.html by
    hand buys you exactly one morning.
    """
    io.open(os.path.join(out_dir, "status.json"), "w", encoding="utf-8", newline="").write(
        json.dumps(tel, indent=2, ensure_ascii=False) + "\n")

    html = telemetry_page.render(tel, tel.get("history") or
                                 run_history.history(days=HISTORY_DAYS))
    io.open(os.path.join(out_dir, "status.html"), "w", encoding="utf-8", newline="").write(html)


def publish(repo, mode):
    out_dir = os.path.join(repo, "docs")
    if not os.path.isdir(os.path.join(repo, ".git")):
        raise SystemExit(f"not a git repo: {repo}")
    os.makedirs(out_dir, exist_ok=True)

    html = io.open(BUILT, encoding="utf-8").read()
    m, data = read_payload(html)

    if mode == "private":
        shutil.copyfile(BUILT, os.path.join(out_dir, "index.html"))
        shutil.copyfile(SUPPORT, os.path.join(out_dir, "support.js"))
        log(f"published FULL dashboard ({len(data.get('jobs', []))} jobs) to {out_dir}")
    else:
        tel = redact(data)
        write_telemetry_page(out_dir, tel)
        log(f"published TELEMETRY only ({tel['totalTracked']} tracked, no company names)")

    msg = (f"Dashboard sync {datetime.date.today().isoformat()} "
           f"({'full' if mode == 'private' else 'telemetry'})")
    subprocess.run(["git", "-C", repo, "add", "-A", "docs"], check=True)
    st = subprocess.run(["git", "-C", repo, "status", "--porcelain"],
                        capture_output=True, text=True).stdout.strip()
    if not st:
        log("no changes to publish")
        return
    subprocess.run(["git", "-C", repo, "commit", "-q", "-m", msg], check=True)
    p = subprocess.run(["git", "-C", repo, "push", "-q"], capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"push failed: {(p.stderr or '')[-400:]}")
    log("pushed")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("public", "private"), required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--no-rebuild", action="store_true")
    a = ap.parse_args()
    if not a.no_rebuild:
        rebuild()
    publish(os.path.abspath(a.repo), a.mode)
