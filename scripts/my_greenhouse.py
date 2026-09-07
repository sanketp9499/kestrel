#!/usr/bin/env python3
"""my_greenhouse.py — Read the user's MyGreenhouse candidate account.

This is not a job source. It is the only place that knows, first-hand, which
Greenhouse applications actually went through — which is exactly what the daily
log keeps guessing at ("no confirmation email arrived ... treat all as not
submitted"). MyGreenhouse answers that directly, and also flags Greenhouse's own
view of duplicate submissions.

The account is at https://my.greenhouse.io and exposes:

    GET /applications.json?page=<n>&active_only=<bool>
    -> {"total_applications": N,
        "active":   {"applications": [...], "total_pages": N, "count": N},
        "inactive": {...}}          # present when active_only=false

Each application record carries company_name, job_title, job_post_url,
applied_at, locations, inactive, currentStage, visibleStages, and
duplicate_of_application_id.

It needs the user's signed-in session, which lives in the browser profile, so this
runs through browser_fetch. NOTE: the automation profile at
~\\AppData\\Local\\JobHunterAutomation\\ChromeProfile is separate from everyday
Chrome — being logged in to MyGreenhouse in normal Chrome is not enough. Sign in
once inside the automation profile (`--login` opens it for you) or every run
reports login_required.

Usage:
    python Scripts/my_greenhouse.py --output Scripts/my_greenhouse_applications.json
    python Scripts/my_greenhouse.py --reconcile      # compare against the tracker
    python Scripts/my_greenhouse.py --login          # open a window to sign in
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_fetch import BrowserSession, _log

ORIGIN = "https://my.greenhouse.io"
MAX_PAGES = 25   # backstop; the account is nowhere near this many pages


def _page(session, page, active_only):
    path = f"/applications.json?page={page}&active_only={'true' if active_only else 'false'}"
    data = session.json_api(ORIGIN, path)
    if not isinstance(data, dict) or "__http_error" in (data or {}):
        return None
    return data


def _flatten(bucket, inactive_flag):
    out = []
    for a in (bucket or {}).get("applications", []) or []:
        out.append({
            "id":            a.get("id"),
            "company":       a.get("company_name", ""),
            "role":          a.get("job_title", ""),
            "url":           a.get("job_post_url", ""),
            "job_post_id":   a.get("job_post_id"),
            "location":      a.get("locations", ""),
            "applied_at":    a.get("applied_at", ""),
            "inactive":      bool(a.get("inactive", inactive_flag)),
            "current_stage": a.get("currentStage"),
            "duplicate_of":  a.get("duplicate_of_application_id"),
        })
    return out


def fetch_applications(headless=True):
    """Every application MyGreenhouse holds, active and inactive.

    Returns (records, error). *error* is "login_required" when the session is
    not signed in, so callers can flag rather than report an empty history.
    """
    records, error = [], None
    with BrowserSession(headless=headless, wait_ms=2500) as session:
        first = _page(session, 1, active_only=False)
        if first is None:
            return [], "login_required"

        total = first.get("total_applications")
        for key, flag in (("active", False), ("inactive", True)):
            bucket = first.get(key) or {}
            records += _flatten(bucket, flag)
            pages = int(bucket.get("total_pages") or 1)
            for p in range(2, min(pages, MAX_PAGES) + 1):
                nxt = _page(session, p, active_only=(key == "active"))
                if not nxt:
                    break
                records += _flatten(nxt.get(key) or {}, flag)

    seen, deduped = set(), []
    for r in records:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        deduped.append(r)

    _log(f"MyGreenhouse: {len(deduped)} applications "
         f"({sum(1 for r in deduped if not r['inactive'])} active, "
         f"{sum(1 for r in deduped if r['inactive'])} inactive"
         + (f", account reports {total}" if total is not None else "") + ")")
    return deduped, error


def reconcile(records):
    """What Greenhouse says was submitted, against what the tracker claims.

    Reports three things worth acting on: applications Greenhouse has that the
    tracker never recorded, Greenhouse's own duplicate flags, and anything it
    has already moved out of the active pipeline.
    """
    from daily_auto_apply import get_existing_entries, normalize_job_url
    tracker_urls, tracker_keys = get_existing_entries()

    missing, dupes, closed = [], [], []
    for r in records:
        key = f"{r['company']} - {r['role']}".strip().lower()
        url = normalize_job_url(r["url"]) if r["url"] else ""
        known = (url and url in tracker_urls) or r["company"].strip().lower() in tracker_keys \
            or key in tracker_keys
        if not known:
            missing.append(r)
        if r["duplicate_of"]:
            dupes.append(r)
        if r["inactive"]:
            closed.append(r)
    return {"missing_from_tracker": missing, "greenhouse_duplicates": dupes,
            "inactive": closed, "total": len(records)}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="Scripts/my_greenhouse_applications.json")
    parser.add_argument("--reconcile", action="store_true",
                        help="compare against the tracker spreadsheet")
    parser.add_argument("--login", action="store_true",
                        help="open MyGreenhouse in the automation profile so you can sign in")
    parser.add_argument("--show", action="store_true", help="run the browser visibly")
    args = parser.parse_args()

    if args.login:
        print("Opening MyGreenhouse in the automation Chrome profile.")
        print("Sign in, then close the window. Runs after this will be authenticated.")
        with BrowserSession(headless=False, wait_ms=1000) as s:
            s.html(ORIGIN + "/dashboard", wait_ms=1000)
            input("Press Enter here once you have signed in and the dashboard is showing... ")
        sys.exit(0)

    records, error = fetch_applications(headless=not args.show)
    if error:
        _log(f"MyGreenhouse: {error} — sign in with: python Scripts/my_greenhouse.py --login")
        sys.exit(2)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    _log(f"Wrote {len(records)} MyGreenhouse applications to {args.output}")

    if args.reconcile:
        report = reconcile(records)
        print(f"\nMyGreenhouse holds {report['total']} applications.")
        print(f"  Not in the tracker:        {len(report['missing_from_tracker'])}")
        print(f"  Flagged duplicate by GH:   {len(report['greenhouse_duplicates'])}")
        print(f"  No longer active:          {len(report['inactive'])}")
        for r in report["missing_from_tracker"]:
            print(f"    MISSING  {r['applied_at'][:10]}  {r['company']} - {r['role']}")
        for r in report["greenhouse_duplicates"]:
            print(f"    DUPLICATE of {r['duplicate_of']}  {r['company']} - {r['role']}")
