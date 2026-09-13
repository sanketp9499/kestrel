"""Prove safe mode actually stops the click, and that turning it off restores it.

The fixture form records into the DOM whether submit ever fired, so this tests
the real behaviour rather than the return value alone.
"""
import asyncio, os, sys, tempfile

SCRIPTS = r"E:\Job Hunter 2026\Job Hunter\Scripts"
sys.path.insert(0, SCRIPTS)
sys.stdout.reconfigure(encoding="utf-8")

import safe_mode
from ats.base import launch_browser, submit_and_confirm

PAGE = """<body>
<form id="f">
  <input type="file" name="resume">
  <button type="submit">Submit Application</button>
</form>
<script>
window.SUBMITTED = false;
document.getElementById('f').onsubmit = (e) => { e.preventDefault();
  window.SUBMITTED = true;
  document.body.innerHTML = '<h1>Application submitted</h1>'; };
</script></body>"""


async def run(page, path, label):
    await page.goto("file:///" + path.replace("\\", "/"))
    await page.wait_for_timeout(200)
    v = await submit_and_confirm(page, 'button[type="submit"]', timeout_ms=6000, label=label)
    fired = await page.evaluate("() => !!window.SUBMITTED")
    return v["verdict"], fired


async def main():
    tmp = tempfile.mkdtemp(prefix="kestrel-safe-")
    path = os.path.join(tmp, "form.html")
    open(path, "w", encoding="utf-8").write(PAGE)

    was_on = safe_mode.state().get("on")
    note = safe_mode.state().get("note", "")
    allow = safe_mode.state().get("allow")
    pw, browser, page = await launch_browser(headless=True)
    fails = 0
    try:
        safe_mode.set_mode(True, "test")
        verdict, fired = await run(page, path, "safe-on")
        ok1 = verdict == "held_safe_mode" and fired is False
        print(f"safe mode ON   -> verdict={verdict:16s} form submitted={fired}   "
              f"{'PASS' if ok1 else 'FAIL'}")
        fails += 0 if ok1 else 1

        safe_mode.set_mode(False)
        verdict, fired = await run(page, path, "safe-off")
        ok2 = verdict == "applied" and fired is True
        print(f"safe mode OFF  -> verdict={verdict:16s} form submitted={fired}    "
              f"{'PASS' if ok2 else 'FAIL'}")
        fails += 0 if ok2 else 1
    finally:
        # Restore FIRST. Behind browser.close(), a close failure skipped this
        # line and left safe mode off silently.
        safe_mode.set_mode(bool(was_on), note, allow)
        await browser.close()
        await pw.stop()

    print("\nFAILURES:", fails)
    print("restored:", "ON" if safe_mode.state().get("on") else "OFF")
    return fails


# Runner script, not a pytest module: it drives a real browser and flips the
# global SAFE_MODE flag. Importing it must never do either. Without this guard
# pytest collected the file, hit sys.exit at import, and aborted the entire
# suite with INTERNALERROR before a single test ran.
if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
