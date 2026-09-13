"""indeed.py — Indeed Easy Apply using an existing logged-in Chrome profile.

Relies on the user's real Chrome profile so the Indeed session is already
active — no passwords are ever entered and no accounts are created.

If the browser is redirected to a login page the function returns immediately
with {"success": False, "error": "login_required", "dry_run": dry_run}.

Indeed Easy Apply jobs keep the user on the Indeed domain throughout.  Jobs
that redirect to an external ATS are NOT supported by this module.
"""
import asyncio
import os
import sys

# Allow running from repo root: python Scripts/ats/indeed.py ...
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ats.base import launch_browser, fill_if_exists, upload_file, click_if_exists, check_success
from daily_log import log

# Dedicated automation profile — NOT the user's everyday Chrome profile.
# Sharing the real profile dir causes Playwright to collide with Chrome's
# per-profile SingletonLock whenever the user already has Chrome open,
# which crashes launch_persistent_context. Run setup_chrome_profile.py once
# to log in to Indeed inside this profile; the session then persists to disk
# and every headless run below reuses it independently of the user's browser.
CHROME_USER_DATA = os.path.expanduser(r"~\AppData\Local\JobHunterAutomation\ChromeProfile")

# URL fragments that indicate Indeed redirected to login
_LOGIN_SIGNALS = ("indeed.com/account/login", "secure.indeed.com/account", "/login?")

# Confirmation phrases Indeed shows after a successful Easy Apply
_SUCCESS_PHRASES = ("application submitted", "you applied", "your application", "application sent")


async def _apply(url: str, resume_pdf: str, profile: dict, custom_answers: dict, dry_run: bool):
    result = {"success": False, "error": None, "dry_run": dry_run}

    try:
        pw, browser, page = await launch_browser(user_data_dir=CHROME_USER_DATA)
    except Exception as e:
        result["error"] = f"Could not launch persistent Chrome context: {e}"
        log(f"  Indeed: browser launch failed — {e}")
        return result

    try:
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # Guard: redirected to login?
        current = page.url
        if any(sig in current for sig in _LOGIN_SIGNALS):
            result["error"] = "login_required"
            log(f"  Indeed: session not active — redirected to login: {current}")
            return result

        # Locate Indeed Easy Apply button — stays on Indeed (not external)
        apply_btn = page.locator(
            'button#indeedApplyButton, '
            'button:has-text("Easily apply"), '
            'a:has-text("Easily apply")'
        ).first
        if await apply_btn.count() == 0:
            result["error"] = "No Indeed Easy Apply button — may be external application"
            log(f"  Indeed: no Easy Apply button at {url}")
            return result

        await apply_btn.click()
        await page.wait_for_timeout(2000)

        # Guard again after modal/redirect
        if any(sig in page.url for sig in _LOGIN_SIGNALS):
            result["error"] = "login_required"
            return result

        # --- Step 1: Resume selection ---
        # Indeed auto-selects the resume on file; just continue.
        continue_btn = page.locator(
            'button:has-text("Continue"), button[type="submit"]:has-text("Continue")'
        ).first
        if await continue_btn.count() > 0:
            await continue_btn.click()
            await page.wait_for_timeout(1500)

        # Upload resume if Indeed exposes a file input
        await upload_file(page, 'input[type="file"]', resume_pdf)

        # --- Step 2: Experience / Work history ---
        await fill_if_exists(
            page,
            'input[name="jobTitle"], input[placeholder*="Job title"], '
            'input[aria-label*="Job title"]',
            profile.get("target_roles", ["Product Designer"])[0],
        )
        await fill_if_exists(
            page,
            'input[name="company"], input[placeholder*="Company"], '
            'input[aria-label*="Company"]',
            profile.get("current_company", "Synkora"),
        )

        # Years of experience
        await fill_if_exists(
            page,
            'input[name="yearsOfExperience"], input[aria-label*="year"], '
            'input[aria-label*="Year"]',
            "2",
        )

        # --- Custom Q&A ---
        for question_text, answer in (custom_answers or {}).items():
            labels = await page.query_selector_all("label")
            for label in labels:
                label_txt = (await label.inner_text()).lower()
                if question_text.lower()[:25] in label_txt:
                    for_id = await label.get_attribute("for")
                    if for_id:
                        el = page.locator(f"#{for_id}").first
                        if await el.count() > 0:
                            await el.fill(answer)
                    break

        if dry_run:
            log(f"  [DRY RUN] Indeed Easy Apply ready (not submitting): {url}")
            result["success"] = True
            return result

        # Safe mode is checked immediately before the click, the same way
        # ats/base.py does it for the adapters that go through
        # submit_and_confirm(). This adapter does not, so without this the hold
        # documented in RUN_PIPELINE.md simply did not apply to it.
        import safe_mode
        if safe_mode.guard("submit"):
            result["error"] = "held_safe_mode"
            result["verdict"] = "held_safe_mode"
            result["signal"] = safe_mode.reason("submit")
            return result

        # --- Submit ---
        # Try labelled submit first, then fall back to any submit-type button
        submit_btn = page.locator(
            'button:has-text("Submit your application"), '
            'button:has-text("Submit"), '
            'button[type="submit"]'
        ).last
        if await submit_btn.count() == 0:
            result["error"] = "No Submit button found"
            return result

        await submit_btn.click()
        await page.wait_for_timeout(3000)

        result["success"] = await check_success(page)
        if not result["success"]:
            result["error"] = "No confirmation found after Submit"

    except Exception as e:
        result["error"] = str(e)
        log(f"  Indeed error: {e}")
    finally:
        await browser.close()
        await pw.stop()

    return result


def apply_indeed(url: str, resume_pdf: str, profile: dict,
                 custom_answers: dict = None, dry_run: bool = False) -> dict:
    """Apply to an Indeed Easy Apply job.

    Parameters
    ----------
    url:            Indeed job posting URL.
    resume_pdf:     Path to the resume PDF (used if Indeed exposes a file
                    upload — typically Indeed uses the on-file resume).
    profile:        Applicant profile dict (name, email, phone, …).
    custom_answers: Mapping of question-text-prefix → answer string.
    dry_run:        If True, fill the form but do NOT click Submit.

    Returns
    -------
    dict with keys ``success`` (bool), ``error`` (str|None), ``dry_run`` (bool).
    """
    return asyncio.run(_apply(url, resume_pdf, profile, custom_answers or {}, dry_run))


if __name__ == "__main__":
    import argparse, json

    p = argparse.ArgumentParser(description="Indeed Easy Apply applicator")
    p.add_argument("--url",      required=True,  help="Indeed job URL")
    p.add_argument("--resume",   required=True,  help="Path to resume PDF")
    p.add_argument("--profile",  default=os.path.join(
                       os.path.dirname(__file__), "..", "sanket_profile.json"))
    p.add_argument("--answers",  default="{}")
    p.add_argument("--dry-run",  action="store_true")
    args = p.parse_args()

    result = apply_indeed(
        args.url,
        args.resume,
        json.load(open(args.profile, encoding="utf-8")),
        json.loads(args.answers),
        args.dry_run,
    )
    print(json.dumps(result, indent=2))
