"""wellfound.py — Apply to Wellfound (ex-AngelList) jobs.

Two things make Wellfound different from every other adapter here:

1. **It always needs a logged-in session.** Job pages render a shell for
   anonymous visitors, so this runs against the persistent Chrome profile the
   LinkedIn and Indeed adapters already use. No session, no application — the
   adapter reports ``login_required`` rather than pretending.

2. **About half of Wellfound's postings are mirrors.** ``atsSource`` on the
   scraped record says whether a job actually lives on Ashby / Greenhouse /
   Lever / Workable, and clicking Apply on those sends you off-site. When that
   happens this adapter does NOT try to drive the foreign form — it returns
   ``external_ats`` plus the resolved URL so Phase 5 can re-dispatch to the
   adapter that already knows that ATS.

Native postings are applied to in-page: a note to the founder plus whatever
extra questions the company added.
"""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import asyncio
from ats.base import (launch_browser, fill_if_exists, upload_file, click_if_exists,
                      check_success, answer_custom_questions, captcha_blocking)
from ats.base import emit_result
from daily_log import log
import daily_log

CHROME_USER_DATA = os.path.expanduser(r"~\AppData\Local\JobHunterAutomation\ChromeProfile")

# Domains Wellfound hands off to, mapped to the adapter that handles them.
EXTERNAL_ATS = {
    "ashbyhq.com":   "ASHBY",
    "greenhouse.io": "GREENHOUSE",
    "lever.co":      "LEVER",
    "workable.com":  "WORKABLE",
    "myworkdayjobs.com": "WORKDAY",
}

# Signed-out state is an auth control in the nav, not a phrase in the page.
#
# This list used to be prose markers - "log in to wellfound", "sign up to
# apply" - scanned against the whole body. On 2026-09-12, checked against the
# live Palette posting, NONE of them matched a page that was plainly signed
# out, so the adapter opened the apply flow and clicked submit with no session.
#
# Widening the substrings would reintroduce the role filter's "user experience"
# bug in a new place: a posting that says "users log in to the dashboard" would
# read as signed out. So match the control as an element, and only when its
# entire text is the control - "Log In", not "Log in to see salary details".
AUTH_CONTROL = re.compile(r"^\s*(log\s?in|sign\s?in|sign\s?up|register|join now)\s*$", re.I)

# Positive proof of a session. Outranks any auth-looking control elsewhere,
# because some layouts keep a "Sign in" affordance in the footer regardless.
ACCOUNT_MENU_SEL = (
    '[data-test*="avatar" i], [class*="avatar" i], img[alt*="profile" i], '
    '[data-test*="account-menu" i], a[href*="/profile"]'
)


def is_logged_out_from(control_texts, has_account_menu=False):
    """Pure decision so it can be tested without a browser."""
    if has_account_menu:
        return False
    return any(AUTH_CONTROL.match(t) for t in control_texts if isinstance(t, str))


def _cover_letter_text(profile) -> str:
    """Plain text for the note field. The pipeline writes cover letters as
    .docx, so unpack one when python-docx is available; a .txt sibling wins."""
    path = profile.get("cover_letter") or profile.get("cover_letter_path") or ""
    if not path:
        return ""
    txt_sibling = os.path.splitext(path)[0] + ".txt"
    if os.path.exists(txt_sibling):
        with open(txt_sibling, encoding="utf-8") as f:
            return f.read().strip()
    if path.lower().endswith(".docx") and os.path.exists(path):
        try:
            import docx
            doc = docx.Document(path)
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()
        except Exception as e:
            log(f"  Wellfound: could not read cover letter {path}: {e}")
    return ""


async def _logged_out(page) -> bool:
    """Read the nav's auth controls, not the page's prose.

    Fails CLOSED on an error: if we cannot tell whether there is a session, the
    safe answer is "not signed in", because the alternative is submitting an
    application into a logged-out page. The old version returned False here,
    which is what let a broken read look like a valid session.
    """
    try:
        has_account = await page.locator(ACCOUNT_MENU_SEL).count() > 0
        texts = await page.locator("a, button").all_inner_texts()
    except Exception as e:
        log(f"  Wellfound: could not read auth state ({str(e)[:60]}) - "
            f"assuming signed out")
        return True
    return is_logged_out_from(texts, has_account_menu=has_account)


def _external_match(url: str):
    u = (url or "").lower()
    for domain, ats in EXTERNAL_ATS.items():
        if domain in u:
            return ats
    return None


async def _apply(url, resume_pdf, profile, custom_answers, dry_run, headless=True,
                 company="", role=""):
    pw, browser, page = await launch_browser(headless=headless,
                                             user_data_dir=CHROME_USER_DATA)
    result = {"success": False, "error": None, "dry_run": dry_run,
              "answered_questions": [], "skipped_questions": [], "account_created": False}
    try:
        await page.goto(url, timeout=45000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)

        if await _logged_out(page):
            result["error"] = "login_required"
            log(f"  Wellfound: not signed in — cannot apply to {url}")
            return result

        # Open the apply flow. Wellfound labels this button several ways.
        opened = await click_if_exists(
            page,
            'button:has-text("Apply"), a:has-text("Apply"), '
            'button:has-text("I\'m interested"), button:has-text("Interested")')
        if not opened:
            result["error"] = "manual_required"
            log(f"  Wellfound: no apply button found at {url}")
            return result
        await page.wait_for_timeout(3000)

        # A mirrored posting bounces off-site. Hand it back rather than guess.
        ats = _external_match(page.url)
        if ats:
            result["error"] = "external_ats"
            result["external_ats"] = ats
            result["redirect_url"] = page.url
            log(f"  Wellfound: {url} redirects to {ats} — re-dispatch to that adapter")
            return result

        if await captcha_blocking(page):
            result["error"] = "captcha_detected"
            log(f"  Wellfound: captcha blocking {url}")
            return result

        # Note to the founder — Wellfound's stand-in for a cover letter.
        note = _cover_letter_text(profile)
        if note:
            await fill_if_exists(
                page,
                'textarea[name="note"], textarea[id*="note" i], '
                'textarea[placeholder*="note" i], textarea[placeholder*="message" i], textarea',
                note)

        # Most Wellfound profiles carry the resume already; upload only when asked.
        if await page.locator('input[type="file"]').count() > 0:
            if await upload_file(page, 'input[type="file"]', resume_pdf):
                log(f"  Wellfound: resume uploaded from {resume_pdf}")
            await page.wait_for_timeout(1000)

        # Caller-supplied answers first, then the shared QA bank.
        for question_text, answer in (custom_answers or {}).items():
            labels = await page.query_selector_all("label")
            for label in labels:
                txt = (await label.inner_text()).strip().lower()
                if question_text.lower()[:30] in txt:
                    for_id = await label.get_attribute("for")
                    if for_id:
                        await fill_if_exists(page, f'[id="{for_id}"]', answer)
                    break

        answered, skipped = await answer_custom_questions(page, profile, company, role)
        result["answered_questions"] = answered
        result["skipped_questions"] = skipped

        if dry_run:
            log(f"  [DRY RUN] Wellfound form filled — not submitting: {url}")
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

        submitted = await click_if_exists(
            page,
            'button:has-text("Send"), button:has-text("Submit"), '
            'button:has-text("Send application"), button[type="submit"]')
        if not submitted:
            result["error"] = "manual_required"
            log(f"  Wellfound: no submit button found at {url}")
            return result
        await page.wait_for_timeout(4000)

        result["success"] = await check_success(page)
        if not result["success"]:
            # Wellfound confirms in its own words, which check_success does not cover.
            try:
                body = (await page.locator("body").inner_text(timeout=8000)).lower()
            except Exception:
                body = ""
            if any(m in body for m in ("application sent", "you applied", "applied on",
                                       "your application is on its way")):
                result["success"] = True
        if not result["success"]:
            result["error"] = "No confirmation found after submit"

    except Exception as e:
        result["error"] = str(e)
        log(f"  Wellfound error: {e}")
    finally:
        await browser.close()
        await pw.stop()
    return result


def apply_wellfound(url, resume_pdf, profile, custom_answers=None, dry_run=False,
                    headless=True, company="", role=""):
    return asyncio.run(_apply(url, resume_pdf, profile, custom_answers or {}, dry_run,
                              headless, company, role))


if __name__ == "__main__":
    import argparse, json
    p = argparse.ArgumentParser()
    p.add_argument("--url",      required=True)
    p.add_argument("--resume",   required=True)
    p.add_argument("--cover-letter", default="", dest="cover_letter")
    p.add_argument("--profile",  default="Scripts/sanket_profile.json")
    p.add_argument("--answers",  default="{}")
    p.add_argument("--dry-run",  action="store_true")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--company",  default="")
    p.add_argument("--role",     default="")
    args = p.parse_args()
    if args.dry_run:
        # Not an application: keep it out of the published run record.
        daily_log.use_test_log()
    profile = json.load(open(args.profile))
    secrets_path = os.path.join(os.path.dirname(args.profile), "secrets.local.json")
    if os.path.exists(secrets_path):
        profile.update(json.load(open(secrets_path)))
    if args.cover_letter:
        profile["cover_letter_path"] = args.cover_letter
    answers = json.loads(args.answers)
    result = apply_wellfound(args.url, args.resume, profile, answers, args.dry_run,
                             args.headless, args.company, args.role)
    emit_result(result)
