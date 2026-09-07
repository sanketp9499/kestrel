#!/usr/bin/env python3
"""board_sessions.py — Check and establish logged-in sessions for gated job boards.

Several boards only show jobs to a signed-in user. the user has accounts on them,
but the accounts live in his everyday Chrome profile while the pipeline drives a
**separate** automation profile at
~\\AppData\\Local\\JobHunterAutomation\\ChromeProfile. Signing in on one does not
sign in the other, so the pipeline sees a logged-out site no matter how many
accounts exist.

This tool exists so that has to be fixed exactly once:

    python Scripts/board_sessions.py --check          # which boards can the pipeline see?
    python Scripts/board_sessions.py --login          # open each gated board to sign in
    python Scripts/board_sessions.py --login --only wttj,startupjobs

`--check` is honest about the difference between "logged out" and "logged in but
no results", because those need different fixes.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_fetch import BrowserSession, _log

# name -> (url to test, url to sign in at, how to tell we can see jobs)
BOARDS = {
    "wttj": {
        "check": "https://www.welcometothejungle.com/en/jobs?query=product%20designer&aroundQuery=Toronto",
        "login": "https://app.welcometothejungle.com/jobs",
        "job_link": r"/jobs/",
        "signed_out": ["3 steps to the job that fits", "tell us about yourself"],
    },
    "startupjobs": {
        "check": "https://startup.jobs/?q=designer&l=canada",
        "login": "https://startup.jobs/login",
        "job_link": r"/[a-z0-9-]+-\d+$",
        "signed_out": ["sign in", "log in to continue"],
    },
    "idealist": {
        "check": "https://www.idealist.org/en/jobs?professionalLevel=NONE&professionalLevel=ENTRY_LEVEL&locationType=NATIONAL&countryCode=CA",
        "login": "https://www.idealist.org/en/login",
        "job_link": r"/en/nonprofit-job/",
        "signed_out": ["log in to idealist"],
    },
    "dribbble": {
        "check": "https://dribbble.com/browse-project-briefs",
        "login": "https://dribbble.com/session/new",
        "job_link": r"/project-briefs/|/jobs/",
        "signed_out": ["sign in", "go pro"],
    },
    "workatastartup": {
        "check": "https://www.workatastartup.com/jobs",
        "login": "https://account.ycombinator.com/",
        "job_link": r"/jobs/\d+",
        "signed_out": ["log in", "sign in"],
    },
}

COUNT_JS = """(pattern) => {
  const re = new RegExp(pattern);
  const hrefs = [...document.querySelectorAll('a')].map(a => a.getAttribute('href') || '');
  return hrefs.filter(h => re.test(h)).length;
}"""

# Consent walls hide the page before anything can be judged. Decline non-essential.
DECLINE_JS = """() => {
  const words = /^(no,? thanks|decline|refuse|reject all|only necessary|essential only|continue without accepting)$/i;
  const b = [...document.querySelectorAll('button,a')]
    .find(e => words.test((e.innerText || '').trim()));
  if (b) { b.click(); return b.innerText.trim(); }
  return null;
}"""


def check(names=None, headless=False):
    names = names or list(BOARDS)
    results = {}
    with BrowserSession(headless=headless, wait_ms=7000) as s:
        for name in names:
            cfg = BOARDS[name]
            if not s.html(cfg["check"], wait_ms=7000):
                results[name] = {"status": "page_failed"}
                continue
            s._page.evaluate(DECLINE_JS)
            s._page.wait_for_timeout(4000)
            try:
                body = (s._page.inner_text("body") or "").lower()
                links = s._page.evaluate(COUNT_JS, cfg["job_link"])
            except Exception as e:
                results[name] = {"status": "dom_error", "detail": str(e)[:80]}
                continue
            signed_out = any(m in body for m in cfg["signed_out"])
            if links > 0:
                results[name] = {"status": "ok", "job_links": links}
            elif signed_out:
                results[name] = {"status": "login_required", "job_links": 0}
            else:
                results[name] = {"status": "no_results", "job_links": 0}
    return results


def login(names=None):
    names = names or list(BOARDS)
    print("Opening each board in the automation Chrome profile.")
    print("Sign in on each, run a search so jobs render, then press Enter here.\n")
    with BrowserSession(headless=False, wait_ms=2500) as s:
        for name in names:
            print(f"--- {name}: {BOARDS[name]['login']}")
            s.html(BOARDS[name]["login"], wait_ms=2500)
            s._page.evaluate(DECLINE_JS)
            input(f"    Press Enter once signed in to {name} (or to skip)... ")
    print("\nNow verify with: python Scripts/board_sessions.py --check")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    p.add_argument("--login", action="store_true")
    p.add_argument("--only", default="", help="comma-separated board names")
    p.add_argument("--headless", action="store_true")
    args = p.parse_args()

    names = [n.strip() for n in args.only.split(",") if n.strip()] or list(BOARDS)
    bad = [n for n in names if n not in BOARDS]
    if bad:
        sys.exit(f"unknown board(s): {', '.join(bad)}. known: {', '.join(BOARDS)}")

    if args.login:
        login(names)
        sys.exit(0)

    res = check(names, headless=args.headless)
    print(json.dumps(res, indent=2))
    usable = [n for n, r in res.items() if r.get("status") == "ok"]
    _log(f"board_sessions: {len(usable)}/{len(names)} boards visible to the pipeline"
         + (f" ({', '.join(usable)})" if usable else ""))
