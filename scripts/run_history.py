#!/usr/bin/env python3
"""run_history.py — Reconstruct the pipeline's run history from the daily logs.

A status page whose every row says "working" teaches people not to read it. The
only thing that makes a green light mean anything is the record behind it, so
this module reads `Scripts/daily_log_YYYY-MM-DD.txt` and reports, per calendar
day, whether the 8 AM run happened and how it ended.

Verdicts:
    clean    the run finished with exit code 0 after doing real work
    noop     exit code 0, but the run was over in under NOOP_MINUTES — it
             started and returned before it could have scanned anything. Exit 0
             is not the same as "worked", and a status page that conflates the
             two is the reason a silent failure can run for weeks unnoticed.
    errors   the run finished, but with a non-zero exit code
    partial  a log exists and the run started, but never logged a completion
    norun    no log for that date at all

Encoding note: these logs are appended to by both Python (UTF-8) and
PowerShell 5.1 (UTF-16LE for redirected native stderr), so a single file can
carry both. Stripping NUL bytes before decoding collapses the UTF-16LE ASCII
runs into readable text instead of losing the whole file to one bad chunk.

Usage:
    python Scripts/run_history.py            # print a summary
    python Scripts/run_history.py --days 90  # window length
    python Scripts/run_history.py --json     # machine-readable
"""
import argparse
import datetime
import glob
import io
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

LOG_RE = re.compile(r"daily_log_(\d{4}-\d{2}-\d{2})\.txt$")
COMPLETE_RE = re.compile(r"PIPELINE COMPLETE \(exit code:\s*(-?\d+)\)")
START_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2})\] STARTING PIPELINE")
BANNER_START_RE = re.compile(
    r"\[(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2})\] STARTING PIPELINE")
BANNER_END_RE = re.compile(
    r"\[(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2})\] PIPELINE COMPLETE")

VERDICTS = ("clean", "noop", "errors", "partial", "norun")

# A full sweep sources six boards, extracts descriptions and drives Playwright.
# Observed real runs take 15-80 minutes; the fast ones cluster under a minute.
# Anything below this finished before it could have done the work.
NOOP_MINUTES = 2.0


def read_log(path):
    """Decode a log that may mix UTF-8 and UTF-16LE within one file."""
    raw = io.open(path, "rb").read()
    return raw.replace(b"\x00", b"").decode("utf-8", errors="replace")


def _minutes_spanned(text):
    """Minutes from the STARTING banner to the COMPLETE banner.

    Deliberately not first-to-last timestamp: these files are also appended to
    by hand-run scripts at other hours, so the outer span of a log can be 15
    hours for a run that took 20 minutes.
    """
    start = BANNER_START_RE.search(text)
    end = BANNER_END_RE.search(text)
    if not (start and end):
        return None
    def mins(m):
        return int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 60.0
    span = mins(end) - mins(start)
    if span < 0:            # crossed midnight
        span += 24 * 60
    return round(span, 1)


def scan_logs(scripts_dir=HERE):
    """Return {date: {...}} for every daily log found on disk."""
    out = {}
    for path in sorted(glob.glob(os.path.join(scripts_dir, "daily_log_*.txt"))):
        m = LOG_RE.search(os.path.basename(path))
        if not m:
            continue
        date = m.group(1)
        text = read_log(path)
        done = COMPLETE_RE.search(text)
        started = bool(START_RE.search(text)) or "STARTING PIPELINE" in text
        minutes = _minutes_spanned(text)
        if not (done or started):
            # A log with entries but no STARTING banner means something else
            # wrote to the day's file - an ad-hoc script, or the test suite,
            # which shares this filename. The scheduler never ran, so this is
            # not a run at all. Counting it as an incomplete run overstates the
            # record in the one direction this page must never overstate.
            continue
        if done:
            code = int(done.group(1))
            if code != 0:
                verdict = "errors"
            elif minutes is not None and minutes < NOOP_MINUTES:
                verdict = "noop"
            else:
                verdict = "clean"
        else:
            code, verdict = None, "partial"
        out[date] = {
            "date": date,
            "verdict": verdict,
            "exit": code,
            "minutes": minutes,
            "bytes": os.path.getsize(path),
        }
    return out


def history(days=90, today=None, scripts_dir=HERE):
    """A dense day-by-day window ending today, oldest first.

    Days before the first log ever written are omitted rather than reported as
    downtime: the pipeline cannot have failed on a day it did not yet exist.
    """
    logs = scan_logs(scripts_dir)
    if not logs:
        return {"days": [], "firstRun": None, "lastRun": None,
                "ranCount": 0, "windowDays": 0, "cleanRate": None, "streak": 0}

    today = today or datetime.date.today()
    first_log = datetime.date.fromisoformat(min(logs))
    start = max(today - datetime.timedelta(days=days - 1), first_log)

    out = []
    d = start
    while d <= today:
        key = d.isoformat()
        out.append(logs.get(key, {"date": key, "verdict": "norun",
                                  "exit": None, "minutes": None, "bytes": 0}))
        d += datetime.timedelta(days=1)

    ran = [x for x in out if x["verdict"] != "norun"]
    clean = [x for x in ran if x["verdict"] == "clean"]

    # Count back from the most recent day that actually ran. Today counts as a
    # gap only once it has a log; before the 8 AM run fires it is simply a day
    # that has not happened yet, not a miss.
    streak = 0
    for x in reversed(out):
        if x["verdict"] == "norun" and streak == 0:
            continue
        if x["verdict"] == "clean":
            streak += 1
        else:
            break

    durations = sorted(x["minutes"] for x in clean if x["minutes"] is not None)
    median = durations[len(durations) // 2] if durations else None

    return {
        "days": out,
        "firstRun": min(logs),
        "lastRun": max(logs),
        "ranCount": len(ran),
        "workedCount": len(clean),
        "windowDays": len(out),
        "cleanRate": round(100.0 * len(clean) / len(ran), 1) if ran else None,
        "medianMinutes": median,
        "longestRunMinutes": durations[-1] if durations else None,
        "streak": streak,
        "noopThresholdMinutes": NOOP_MINUTES,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    h = history(a.days)
    if a.json:
        print(json.dumps(h, indent=2))
    else:
        tally = {v: 0 for v in VERDICTS}
        for x in h["days"]:
            tally[x["verdict"]] += 1
        print(f"window      {h['windowDays']} days ({h['firstRun']} -> {h['lastRun']})")
        print(f"ran         {h['ranCount']}")
        print(f"clean rate  {h['cleanRate']}%   current streak {h['streak']}")
        print("verdicts    " + "  ".join(f"{k}={tally[k]}" for k in VERDICTS))
