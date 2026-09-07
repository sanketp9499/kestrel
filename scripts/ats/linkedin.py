"""linkedin.py — LinkedIn Easy Apply using an existing logged-in Chrome profile.

Relies on the user's real Chrome profile so the LinkedIn session is already
active — no passwords are ever entered and no accounts are created.

If the browser is redirected to a login page the function returns immediately
with {"success": False, "error": "login_required", "dry_run": dry_run}.
"""
import asyncio
import os
import re
import sys

# Allow running from repo root: python Scripts/ats/linkedin.py ...
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ats.base import launch_browser, fill_if_exists, upload_file, click_if_exists, check_success, answer_custom_questions
from daily_log import log

# Dedicated automation profile — NOT the user's everyday Chrome profile.
# Sharing the real profile dir causes Playwright to collide with Chrome's
# per-profile SingletonLock whenever the user already has Chrome open,
# which crashes launch_persistent_context. Run setup_chrome_profile.py once
# to log in to LinkedIn inside this profile; the session then persists to disk
# and every headless run below reuses it independently of the user's browser.
CHROME_USER_DATA = os.path.expanduser(r"~\AppData\Local\JobHunterAutomation\ChromeProfile")

# Keywords that indicate LinkedIn redirected to login
_LOGIN_SIGNALS = ("linkedin.com/login", "linkedin.com/uas/login", "linkedin.com/checkpoint")


def _normalize_to_www(url: str) -> str:
    """Rewrite locale subdomains (ca.linkedin.com, uk.linkedin.com, ...) to
    www.linkedin.com. The auth session cookie (li_at) is scoped to
    .www.linkedin.com only, so locale subdomains render as logged-out even
    with a valid session, hiding the Easy Apply button entirely."""
    return re.sub(r'https://[a-z]{2,3}\.linkedin\.com/', 'https://www.linkedin.com/', url)


async def _apply_on_page(page, url: str, resume_pdf: str, profile: dict, custom_answers: dict, dry_run: bool,
                          company: str = "", role: str = ""):
    """Core Easy Apply flow against an already-open page. Does not launch or
    close any browser — callers own that lifecycle (see apply_linkedin for a
    single-job convenience wrapper, or run a shared page across many jobs)."""
    result = {"success": False, "error": None, "dry_run": dry_run, "answered_questions": [], "skipped_questions": []}

    try:
        url = _normalize_to_www(url)
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # Guard: redirected to login?
        current = page.url
        if any(sig in current for sig in _LOGIN_SIGNALS):
            result["error"] = "login_required"
            log(f"  LinkedIn: session not active — redirected to login: {current}")
            return result

        # Locate the Easy Apply button (stays on LinkedIn, not external redirect)
        easy_apply = page.locator('button:has-text("Easy Apply")').first
        if await easy_apply.count() == 0:
            result["error"] = "No Easy Apply button — not an Easy Apply job"
            log(f"  LinkedIn: no Easy Apply button at {url}")
            return result

        await easy_apply.click()
        await page.wait_for_timeout(2000)

        # --- Multi-step form loop — no step-count cap; bounded by wall-clock
        # time instead so a genuinely stuck form can't hang the browser forever ---
        import hashlib, time as _time
        _deadline = _time.monotonic() + 600  # 10 minutes
        step = 0
        _last_sig = None
        _stuck_count = 0
        while _time.monotonic() < _deadline:
            step += 1

            # Detect a form that isn't actually advancing (same visible content
            # after the previous click). Two consecutive stuck iterations +
            # an invisible reCAPTCHA present = the button's handler is gated
            # behind an unsatisfied challenge — a real case seen on some
            # LinkedIn->Workable bridges. Bail immediately rather than loop
            # to the time limit; never attempt to solve it (standing rule).
            body_text = await page.inner_text("body")
            sig = hashlib.md5(body_text[:2000].encode()).hexdigest()
            if sig == _last_sig:
                _stuck_count += 1
            else:
                _stuck_count = 0
            _last_sig = sig

            if _stuck_count >= 2:
                recaptcha_frame = any("recaptcha" in (fr.url or "") for fr in page.frames)
                if recaptcha_frame:
                    result["error"] = "captcha_detected — flagged, not submitted"
                    log(f"  LinkedIn: form stuck + reCAPTCHA present — flagging, not looping further: {url}")
                else:
                    result["error"] = f"stuck_no_progress at step {step} — same content after click, no CAPTCHA detected"
                    log(f"  LinkedIn: form stuck (no progress after click, no CAPTCHA) — flagging: {url}")
                return result
            # Guard against login redirect mid-flow
            if any(sig in page.url for sig in _LOGIN_SIGNALS):
                result["error"] = "login_required"
                return result

            # Fill phone number if a phone field appears
            await fill_if_exists(
                page,
                'input[id*="phoneNumber"], input[aria-label*="phone"], '
                'input[aria-label*="Phone"]',
                profile.get("phone", ""),
            )

            # Fill named fields from profile
            await fill_if_exists(
                page,
                'input[id*="firstName"], input[aria-label*="First name"]',
                profile.get("name", "").split()[0],
            )
            last_name = " ".join(profile.get("name", "").split()[1:])
            await fill_if_exists(
                page,
                'input[id*="lastName"], input[aria-label*="Last name"]',
                last_name,
            )

            # Upload resume if a file input is present
            await upload_file(page, 'input[type="file"]', resume_pdf)

            # Answer any caller-supplied overrides first (job-specific, if given)
            for q_text, answer in (custom_answers or {}).items():
                labels = await page.query_selector_all("label")
                for label in labels:
                    label_text = (await label.inner_text()).lower()
                    if q_text.lower()[:25] in label_text:
                        for_id = await label.get_attribute("for")
                        if for_id:
                            field = page.locator(f"#{for_id}").first
                            if await field.count() > 0:
                                await field.fill(answer)
                        break

            # Answer custom screening questions from the QA bank (real profile
            # facts — years of experience, work auth, salary, start date, etc.
            # EEO/identity questions are deliberately skipped, not guessed.)
            answered, skipped = await answer_custom_questions(page, profile, company, role)
            if answered:
                result["answered_questions"].extend(answered)
                for a in answered:
                    log(f"    Q&A: '{a['question']}' -> '{a['answer']}'")
            if skipped:
                result["skipped_questions"].extend(skipped)
                for s in skipped:
                    log(f"    Q&A SKIPPED (EEO/identity): '{s}'")

            # Fill "years of experience" numeric fields with "2" (fallback for
            # any not caught by label text above, e.g. unlabeled number inputs)
            for input_el in await page.query_selector_all(
                'input[type="text"], input[type="number"]'
            ):
                aria = (await input_el.get_attribute("aria-label") or "").lower()
                placeholder = (await input_el.get_attribute("placeholder") or "").lower()
                combined = aria + " " + placeholder
                if "year" in combined and "experience" in combined:
                    current = await input_el.input_value()
                    if not current:
                        await input_el.fill("2")

            # Detect Submit vs Next
            submit_btn = page.locator(
                'button[aria-label="Submit application"], '
                'button:has-text("Submit application")'
            ).first
            next_btn = page.locator(
                'button[aria-label="Continue to next step"], '
                'button:has-text("Next")'
            ).first
            review_btn = page.locator('button:has-text("Review")').first

            if await submit_btn.count() > 0:
                if dry_run:
                    log(f"  [DRY RUN] LinkedIn Easy Apply ready to submit: {url}")
                    result["success"] = True
                    return result
                # LinkedIn bug: submit button may be off-screen
                await submit_btn.scroll_into_view_if_needed()
                await submit_btn.click()
                await page.wait_for_timeout(3000)
                result["success"] = await check_success(page)
                if not result["success"]:
                    result["error"] = "No confirmation found after Submit"
                return result

            elif await review_btn.count() > 0:
                await review_btn.click()
                await page.wait_for_timeout(1500)

            elif await next_btn.count() > 0:
                await next_btn.click()
                await page.wait_for_timeout(1500)

            else:
                result["error"] = f"No Next / Review / Submit found at step {step}"
                return result

        result["error"] = f"Timed out after {step} steps / 10 minutes in Easy Apply flow"

    except Exception as e:
        result["error"] = str(e)
        log(f"  LinkedIn error: {e}")

    return result


async def _apply(url: str, resume_pdf: str, profile: dict, custom_answers: dict, dry_run: bool, headless: bool = True,
                  company: str = "", role: str = ""):
    try:
        pw, browser, page = await launch_browser(headless=headless, user_data_dir=CHROME_USER_DATA)
    except Exception as e:
        log(f"  LinkedIn: browser launch failed — {e}")
        return {"success": False, "error": f"Could not launch persistent Chrome context: {e}", "dry_run": dry_run}

    try:
        return await _apply_on_page(page, url, resume_pdf, profile, custom_answers, dry_run, company, role)
    finally:
        await browser.close()
        await pw.stop()


def apply_linkedin(url: str, resume_pdf: str, profile: dict,
                   custom_answers: dict = None, dry_run: bool = False, headless: bool = True,
                   company: str = "", role: str = "") -> dict:
    """Apply to a single LinkedIn Easy Apply job (launches and closes its own browser).

    Parameters
    ----------
    url:            LinkedIn job posting URL.
    resume_pdf:     Absolute path to the resume file (PDF or DOCX — LinkedIn accepts both).
    profile:        Applicant profile dict (name, email, phone, …).
    custom_answers: Mapping of question-text-prefix → answer string.
    dry_run:        If True, fill the form but do NOT click Submit.
    headless:       If False, opens a visible Chrome window so the user can watch.

    Returns
    -------
    dict with keys ``success`` (bool), ``error`` (str|None), ``dry_run`` (bool).
    """
    return asyncio.run(_apply(url, resume_pdf, profile, custom_answers or {}, dry_run, headless, company, role))


async def apply_linkedin_batch(jobs: list, profile: dict, headless: bool = False, dry_run: bool = False,
                                on_result=None):
    """Apply to many LinkedIn jobs using ONE shared browser window (no repeated
    open/close). ``jobs`` is a list of dicts with url/resume_path/custom_answers/
    company/title keys. Calls ``on_result(job, result)`` after each attempt."""
    pw, browser, page = await launch_browser(headless=headless, user_data_dir=CHROME_USER_DATA)
    results = []
    try:
        for job in jobs:
            r = await _apply_on_page(
                page, job["url"], job["resume_path"], profile,
                job.get("custom_answers", {}), dry_run,
                job.get("company", ""), job.get("title", ""),
            )
            r.update({"company": job.get("company"), "title": job.get("title"), "url": job["url"]})
            results.append(r)
            if on_result:
                on_result(job, r)
    finally:
        await browser.close()
        await pw.stop()
    return results


if __name__ == "__main__":
    import argparse, json

    p = argparse.ArgumentParser(description="LinkedIn Easy Apply applicator")
    p.add_argument("--url",      required=True,  help="LinkedIn job URL")
    p.add_argument("--resume",   required=True,  help="Path to resume PDF")
    p.add_argument("--profile",  default=os.path.join(
                       os.path.dirname(__file__), "..", "profile.json"))
    p.add_argument("--answers",  default="{}")
    p.add_argument("--dry-run",  action="store_true")
    p.add_argument("--headless", action="store_true", help="Run invisibly (default: visible window)")
    p.add_argument("--company",  default="", help="Company name (used by the Q&A bank for context)")
    p.add_argument("--role",     default="", help="Role title (used by the Q&A bank for context)")
    args = p.parse_args()

    profile = json.load(open(args.profile, encoding="utf-8"))
    secrets_path = os.path.join(os.path.dirname(args.profile), "secrets.local.json")
    if os.path.exists(secrets_path):
        profile.update(json.load(open(secrets_path, encoding="utf-8")))

    result = apply_linkedin(
        args.url,
        args.resume,
        profile,
        json.loads(args.answers),
        args.dry_run,
        headless=args.headless,
        company=args.company,
        role=args.role,
    )
    print(json.dumps(result, indent=2))
