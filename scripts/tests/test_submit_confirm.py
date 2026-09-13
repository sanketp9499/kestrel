"""Drive submit_and_confirm() against the four post-submit behaviours real ATS
forms actually show. The old check_success() scored 1/4 here."""
import asyncio, os, sys, tempfile

SCRIPTS = r"E:\Job Hunter 2026\Job Hunter\Scripts"
sys.path.insert(0, SCRIPTS)
sys.stdout.reconfigure(encoding="utf-8")

import safe_mode
from ats.base import launch_browser, submit_and_confirm, check_success

FORM = """
<form id="f">
  <input type="file" name="resume">
  <input type="text" id="q" name="q">
  <button type="submit">Submit Application</button>
</form>
"""

CASES = {
    # A required question was left blank: the ATS re-renders the form with an
    # error. Nothing was sent. Old code called this "submitted_unconfirmed".
    "blocked": """<body>""" + FORM + """
<script>
document.getElementById('f').onsubmit = (e) => { e.preventDefault();
  const d = document.createElement('div'); d.className = 'field-error';
  d.textContent = 'Years of experience is required'; document.body.appendChild(d); };
</script></body>""",

    # SPA ATS: posts over XHR, then swaps the form for a success panel, 6s later
    # than the old 3-second sleep allowed for.
    "applied_swap": """<body>""" + FORM + """
<script>
document.getElementById('f').onsubmit = (e) => { e.preventDefault();
  setTimeout(() => { document.body.innerHTML =
    '<h1>Application complete</h1><p>We will be in touch.</p>'; }, 6000); };
</script></body>""",

    # Classic redirect to a confirmation URL with no matching phrase on it.
    "applied_redirect": """<body>""" + FORM + """
<script>
document.getElementById('f').onsubmit = (e) => { e.preventDefault();
  setTimeout(() => { location.href = location.pathname.replace('redirect','done')
    + '?status=confirmation'; }, 1200); };
</script></body>""",

    # Submit swallowed, nothing changes. Genuinely unknowable from the page.
    "unconfirmed": """<body>""" + FORM + """
<script>document.getElementById('f').onsubmit = (e) => e.preventDefault();</script>
</body>""",
}

EXPECT = {"blocked": "blocked", "applied_swap": "applied",
          "applied_redirect": "applied", "unconfirmed": "unconfirmed"}


async def main():
    tmp = tempfile.mkdtemp(prefix="kestrel-fixtures-")
    for name, html in CASES.items():
        open(os.path.join(tmp, name + ".html"), "w", encoding="utf-8").write(html)
    # the redirect target
    open(os.path.join(tmp, "applied_done.html"), "w", encoding="utf-8").write(
        "<body><h1>All set</h1><p>Nothing here says the magic words.</p></body>")

    # These fixtures are local file:// forms, not employers. Safe mode correctly
    # blocks every submit, so it is lifted for the test and restored afterwards.
    prior = safe_mode.state()
    # The browser is launched BEFORE the flag is touched, and the flag is
    # restored as the FIRST thing in the finally. Both orderings matter: with
    # set_mode(False) ahead of launch_browser(), a launch failure left safe mode
    # off for good with no log line, and with the restore behind
    # browser.close(), a close failure did the same. That is how the flag
    # vanished on 2026-09-12 between the 00:24 and 02:34 test passes.
    pw, browser, page = await launch_browser(headless=True)
    rows, failures = [], 0
    try:
        safe_mode.set_mode(False)
        for name, expected in EXPECT.items():
            await page.goto("file:///" + os.path.join(tmp, name + ".html").replace("\\", "/"))
            await page.wait_for_timeout(300)
            old = await check_success(page)
            v = await submit_and_confirm(page, 'button[type="submit"]',
                                         timeout_ms=12000, label=name)
            ok = v["verdict"] == expected
            failures += 0 if ok else 1
            rows.append((name, expected, v["verdict"], "PASS" if ok else "FAIL",
                         (v["signal"] or "")[:52], "; ".join(v["errors"])[:40]))
    finally:
        safe_mode.set_mode(bool(prior.get('on')), prior.get('note', ''),
                           prior.get('allow'))
        await browser.close()
        await pw.stop()

    w = max(len(r[0]) for r in rows)
    print(f"\n{'case'.ljust(w)}  expected      got           result  signal")
    print("-" * (w + 62))
    for name, exp, got, res, sig, err in rows:
        print(f"{name.ljust(w)}  {exp.ljust(12)}  {got.ljust(12)}  {res:6}  {sig or err}")
    print()
    print("FAILURES:", failures)
    print("safe mode restored:", "ON" if safe_mode.state().get("on") else "OFF")
    return failures


# Runner script, not a pytest module: it drives a real browser and flips the
# global SAFE_MODE flag. Importing it must never do either. Without this guard
# pytest collected the file, hit sys.exit at import, and aborted the entire
# suite with INTERNALERROR before a single test ran.
if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
