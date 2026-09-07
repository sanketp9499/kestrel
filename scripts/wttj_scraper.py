#!/usr/bin/env python3
"""wttj_scraper.py — Scrape Welcome to the Jungle job search.

**Status: needs a signed-in browser profile before it can return anything.**

What was verified on 2026-09-06:

  * www.welcometothejungle.com/en/jobs?query=...&aroundQuery=... returns HTTP 200
    and ~576KB, no Cloudflare challenge, but the content is an Axeptio cookie wall
    ("C is for COOKIE"). Declining it with the "No, thanks" button works.
  * After declining, an anonymous visitor does NOT get search results. The page
    becomes a signup funnel ("3 steps to the job that fits / Tell us about
    yourself / Upload"), with 0 job links in the DOM.
  * app.welcometothejungle.com/jobs is the logged-in SPA — a 43KB shell for
    anonymous clients.
  * Search is Algolia-backed (app id csekhvms53, e.g. the
    wk_cms_organizations_production index). The search key is injected at runtime
    from env vars, not present in the static Next.js chunks, so there is no
    key to lift for a keyless API path.

So the route is the same one my_greenhouse.py takes: drive the persistent Chrome
profile at ~\\AppData\\Local\\JobHunterAutomation\\ChromeProfile with a signed-in
WTTJ session. Sign in once with --login, then the card parser can be written
against the real logged-in DOM.

Usage:
    python Scripts/wttj_scraper.py --login     # sign in once, in a visible window
    python Scripts/wttj_scraper.py --check     # report whether the session works
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_fetch import BrowserSession, _log

BASE = "https://www.welcometothejungle.com"
APP = "https://app.welcometothejungle.com"

SEARCH_TERMS = ["product designer", "ux designer", "ui designer", "web designer"]
LOCATIONS = ["Toronto", "Vancouver", "Montreal", "Canada"]

# Axeptio consent wall. Choose the most private option available.
DECLINE_JS = """() => {
  const words = /^(no,? thanks|decline|refuse|reject all|only necessary|essential only)$/i;
  const b = [...document.querySelectorAll('button,a')]
    .find(e => words.test((e.innerText || '').trim()));
  if (b) { b.click(); return b.innerText.trim(); }
  return null;
}"""

# A signed-out session lands on the onboarding funnel instead of results.
SIGNED_OUT_MARKERS = [
    "3 steps to the job that fits",
    "tell us about yourself",
    "what job are you looking for?",
]


def search_url(term, location):
    from urllib.parse import quote
    return f"{BASE}/en/jobs?query={quote(term)}&aroundQuery={quote(location)}"


def _signed_out(page) -> bool:
    try:
        body = (page.inner_text("body") or "").lower()
    except Exception:
        return True
    return any(m in body for m in SIGNED_OUT_MARKERS)


def check_session(headless=False):
    """Report whether the automation profile has a usable WTTJ session."""
    with BrowserSession(headless=headless, wait_ms=8000) as s:
        if not s.html(search_url("product designer", "Toronto"), wait_ms=8000):
            return {"ok": False, "error": "page_failed"}
        declined = s._page.evaluate(DECLINE_JS)
        s._page.wait_for_timeout(5000)
        out = _signed_out(s._page)
        links = s._page.evaluate(
            """() => [...document.querySelectorAll('a')]
                  .map(a => a.getAttribute('href') || '')
                  .filter(h => /\\/jobs\\//.test(h) && !/collections|get-started|authenticate/.test(h)).length""")
        return {"ok": (not out) and links > 0, "consent_declined": declined,
                "signed_out": out, "job_links": links}


def login(headless=False):
    print("Opening Welcome to the Jungle in the automation Chrome profile.")
    print("Sign in, run a job search so results render, then close the window.")
    with BrowserSession(headless=headless, wait_ms=2000) as s:
        s.html(APP + "/jobs", wait_ms=2000)
        input("Press Enter here once you are signed in and seeing jobs... ")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--login", action="store_true")
    p.add_argument("--check", action="store_true")
    p.add_argument("--headless", action="store_true")
    args = p.parse_args()

    if args.login:
        login(headless=False)
        sys.exit(0)

    result = check_session(headless=args.headless)
    print(json.dumps(result, indent=2))
    if not result.get("ok"):
        _log("WTTJ: no usable session — run: python Scripts/wttj_scraper.py --login")
        sys.exit(2)
    _log("WTTJ: session works; the card parser can now be written against the real DOM.")
