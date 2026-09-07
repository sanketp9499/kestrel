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
    python scripts/sync_dashboard.py --mode public  --repo "/path/to/kestrel"
    python scripts/sync_dashboard.py --mode private --repo "/path/to/kestrel-live"
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
CC = os.path.join(HERE, "command_center")
BUILT = os.path.join(CC, "Job_Hunter_Command_Center.html")
SUPPORT = os.path.join(CC, "support.js")

DATA_RE = re.compile(r"(window\.__CC_DATA__\s*=\s*)(\{.*?\})(;?\s*</script>)", re.S)


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
        "note": "Telemetry only. Company names, roles, salaries and documents are "
                "removed before publishing. See the repo README for how the pipeline works.",
    }


def write_telemetry_page(out_dir, tel):
    """A small standalone status page — not the full app, which needs job rows."""
    io.open(os.path.join(out_dir, "status.json"), "w", encoding="utf-8", newline="").write(
        json.dumps(tel, indent=2, ensure_ascii=False) + "\n")

    src = tel["sources"]
    bots = tel["automation"].get("bots", [])
    rows = "\n".join(
        f'<tr><td>{s["name"]}</td><td class="s {s["health"]}">{s["health"]}</td>'
        f'<td>{s.get("synced","-")}</td></tr>' for s in src)
    chips = " ".join(f'<span class=chip>{b["name"]}</span>' for b in bots)
    stage = tel["byStage"]
    cards = "".join(
        f'<div class=card><b>{v}</b><span>{k}</span></div>'
        for k, v in (("tracked", tel["totalTracked"]),
                     ("applied", stage.get("applied", 0)),
                     ("wishlist", stage.get("not", 0)),
                     ("captcha-blocked", stage.get("captcha", 0)),
                     ("interviews", stage.get("interview", 0))))
    html = f"""<!doctype html><meta charset=utf-8>
<title>Kestrel — pipeline status</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{{color-scheme:dark light}}
body{{font:15px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;
max-width:760px;margin:40px auto;padding:0 20px;background:#0d1117;color:#e6edf3}}
h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#8b949e;margin:0 0 28px;font-size:13.5px}}
.cards{{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 28px}}
.card{{flex:1 1 110px;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 14px}}
.card b{{display:block;font-size:24px}} .card span{{color:#8b949e;font-size:12px}}
table{{width:100%;border-collapse:collapse;margin:0 0 24px}}
td{{padding:8px 6px;border-bottom:1px solid #21262d;font-size:13.5px}}
.s{{font-weight:600}} .working{{color:#3fb950}} .broken{{color:#f85149}} .reconnect{{color:#d29922}}
.chip{{display:inline-block;background:#161b22;border:1px solid #30363d;border-radius:999px;
padding:3px 10px;margin:0 5px 6px 0;font-size:12px}}
.note{{color:#8b949e;font-size:12.5px;border-top:1px solid #21262d;padding-top:16px;margin-top:8px}}
a{{color:#58a6ff}}
</style>
<h1>Kestrel — pipeline status</h1>
<p class=sub>{tel["automation"].get("scheduledTime","scheduled daily")} · last log
{tel["automation"].get("lastLogDate","-")} · generated {tel["generatedAt"][:16].replace("T"," ")}</p>
<div class=cards>{cards}</div>
<h3 style="font-size:14px;margin:0 0 8px">Sources</h3>
<table>{rows}</table>
<h3 style="font-size:14px;margin:0 0 8px">ATS adapters</h3>
<div>{chips}</div>
<p class=note>{tel["note"]}<br>
<a href="./">Interactive demo</a> · <a href="https://github.com/sanketp9499/kestrel">Source</a></p>
"""
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
