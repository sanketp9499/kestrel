#!/usr/bin/env python3
"""browser_fetch.py — Fetch a page through a real browser instead of urllib.

Some sources cannot be read with plain HTTP:

  * hiringcafe.com sits behind Cloudflare. A cold curl sometimes succeeds, but a
    second request from the same client gets a "Just a moment..." challenge, so
    a scraper built on urllib works right up until it silently stops working.
  * my.greenhouse.io needs the user's signed-in session cookie.

Both are solved the same way: drive the persistent Chrome profile the LinkedIn
and Indeed adapters already use, let the real browser satisfy the challenge and
carry the cookies, and read the rendered page back out.

This is deliberately synchronous — the discovery scripts are plain scripts, not
the async ATS adapters.
"""
import json
import os
import re
import time

CHROME_USER_DATA = os.path.expanduser(r"~\AppData\Local\JobHunterAutomation\ChromeProfile")

NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _log(msg):
    try:
        from daily_log import log
        log(msg)
    except Exception:
        print(msg)


class BrowserSession:
    """One browser for many fetches. Use as a context manager."""

    def __init__(self, headless=True, user_data_dir=None, wait_ms=2500):
        self.headless = headless
        self.user_data_dir = user_data_dir or CHROME_USER_DATA
        self.wait_ms = wait_ms
        self._pw = None
        self._ctx = None
        self._page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            self.user_data_dir,
            headless=self.headless,
            channel="chrome",
            args=["--profile-directory=Default"],
        )
        self._page = self._ctx.new_page()
        return self

    def __exit__(self, *exc):
        for closer in (getattr(self._ctx, "close", None), getattr(self._pw, "stop", None)):
            try:
                if closer:
                    closer()
            except Exception:
                pass
        return False

    def html(self, url, wait_ms=None, timeout=45000, challenge_wait_ms=20000):
        """Rendered HTML for *url*, or "" if the load failed.

        A Cloudflare interstitial is given time to clear itself. Note that a
        headless browser is usually failed outright by that check no matter how
        long it waits — run headed for challenged sites.
        """
        try:
            self._page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            self._page.wait_for_timeout(wait_ms if wait_ms is not None else self.wait_ms)
            content = self._page.content()
            if "Just a moment" in content or "challenge-platform" in content:
                deadline = time.time() + challenge_wait_ms / 1000.0
                while time.time() < deadline:
                    self._page.wait_for_timeout(2000)
                    content = self._page.content()
                    if "Just a moment" not in content:
                        break
                else:
                    _log(f"  browser_fetch: challenge not cleared for {url[:80]}"
                         f"{' (headless — try headed)' if self.headless else ''}")
            return content
        except Exception as e:
            _log(f"  browser_fetch: {url[:90]} failed: {e}")
            return ""

    def next_data(self, url, wait_ms=None):
        """__NEXT_DATA__ props.pageProps for a Next.js page, or {}."""
        html = self.html(url, wait_ms=wait_ms)
        if not html:
            return {}
        m = NEXT_DATA_RE.search(html)
        if not m:
            return {}
        try:
            return json.loads(m.group(1))["props"]["pageProps"]
        except (ValueError, KeyError, TypeError):
            return {}

    def json_api(self, origin, path):
        """GET a same-origin JSON endpoint with the session's cookies attached.

        Navigates to *origin* first so the fetch is same-origin and authenticated.
        Returns the decoded JSON, or None when the call fails or is not JSON.
        """
        if not self._page.url.startswith(origin):
            if not self.html(origin, wait_ms=1500):
                return None
        try:
            return self._page.evaluate(
                """async (p) => {
                    const r = await fetch(p, {credentials: 'include',
                                              headers: {'Accept': 'application/json'}});
                    if (!r.ok) return {__http_error: r.status};
                    const ct = r.headers.get('content-type') || '';
                    if (!ct.includes('json')) return {__http_error: 'not-json'};
                    return await r.json();
                }""",
                path,
            )
        except Exception as e:
            _log(f"  browser_fetch: JSON call {path} failed: {e}")
            return None

    def sleep(self, seconds):
        time.sleep(seconds)
