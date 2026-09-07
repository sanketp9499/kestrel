"""ashby.py — Apply to Ashby ATS jobs.

Ashby forms use opaque UUID field ids (no semantic name/id hints), so every
field must be matched by its <label> text. Ashby also commonly embeds a
reCAPTCHA — per the standing rule ("never solve CAPTCHAs"), this script
detects it and refuses to submit, same treatment as a CAPTCHA-blocked direct
apply. Any custom textarea question the QA bank can't confidently answer
(bespoke essay prompts like "what's a project you're proud of") is left
blank and reported back rather than guessed.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import asyncio, re
from ats.base import (launch_browser, fill_if_exists, upload_file, click_if_exists, check_success,
                      captcha_blocking,
                       answer_custom_questions, maybe_create_account, upload_cover_letter)
from qa_bank import is_excluded

# Conditional/optional prompts must not block an otherwise complete form
_OPTIONAL_RE = re.compile(r'if you selected|if applicable|\(optional\)|optional')
from daily_log import log


async def _apply(url, resume_pdf, profile, custom_answers, dry_run, headless=True, company="", role=""):
    pw, browser, page = await launch_browser(headless=headless)
    result = {"success": False, "error": None, "dry_run": dry_run, "answered_questions": [],
               "skipped_questions": [], "unanswered_questions": [], "captcha_detected": False,
               "account_created": False}
    try:
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # Ashby keeps the form collapsed behind an "Apply for this Job" button on
        # many boards — reveal it before looking for any field.
        if await page.locator('input[type="file"]').count() == 0:
            await click_if_exists(page, 'button:has-text("Apply"), a:has-text("Apply")')
            await page.wait_for_timeout(2500)

        if await maybe_create_account(page, profile["email"], profile.get("account_password", "")):
            result["account_created"] = True
            log(f"  Ashby: account fields detected and filled at {url}")

        await fill_if_exists(page, '#_systemfield_name', profile["name"])
        await fill_if_exists(page, '#_systemfield_email', profile["email"])

        uploaded = await upload_file(page, '#_systemfield_resume', resume_pdf)
        if not uploaded:
            uploaded = await upload_file(page, 'input[type="file"]', resume_pdf)
            await upload_cover_letter(page, profile)
        if not uploaded:
            result["error"] = "Resume upload failed — no file input found"
            log(f"  Ashby: resume upload failed at {url}")
            return result

        # Cover letter, LinkedIn, portfolio — matched by label text since Ashby
        # ids are opaque UUIDs
        labels = await page.query_selector_all("label")
        handled_ids = set()
        for label in labels:
            text = (await label.inner_text() or "").strip().lower()
            for_id = await label.get_attribute("for")
            if not for_id or not text:
                continue
            field = page.locator(f'[id="{for_id}"]').first
            if await field.count() == 0:
                continue
            tag = await field.evaluate("el => el.tagName.toLowerCase()")
            input_type = await field.get_attribute("type") if tag == "input" else None

            if "linkedin" in text:
                await field.fill(profile.get("linkedin", ""))
                handled_ids.add(for_id)
            elif "portfolio" in text or "website" in text:
                await field.fill(profile.get("portfolio", ""))
                handled_ids.add(for_id)
            elif "cover letter" in text and input_type == "file":
                cl = profile.get("cover_letter_path")
                if cl:
                    await field.set_input_files(cl)
                handled_ids.add(for_id)

        for question_text, answer in (custom_answers or {}).items():
            for label in labels:
                txt = (await label.inner_text()).strip().lower()
                if question_text.lower()[:30] in txt:
                    for_id = await label.get_attribute("for")
                    if for_id and for_id not in handled_ids:
                        await fill_if_exists(page, f'[id="{for_id}"]', answer)
                        handled_ids.add(for_id)
                    break

        answered, skipped = await answer_custom_questions(page, profile, company, role)
        result["answered_questions"] = answered
        result["skipped_questions"] = skipped
        for a in answered:
            log(f"    Q&A: '{a['question']}' -> '{a['answer']}'")
            handled_ids.add(a["question"])  # best-effort de-dup, harmless if unmatched
        for s in skipped:
            log(f"    Q&A SKIPPED (EEO/identity): '{s}'")

        # Report any remaining unanswered textarea/text questions rather than
        # guess at bespoke essay prompts
        for label in labels:
            text = (await label.inner_text() or "").strip()
            for_id = await label.get_attribute("for")
            if not for_id or not text or for_id in handled_ids:
                continue
            if is_excluded(text) or _OPTIONAL_RE.search(text.lower()):
                continue
            field = page.locator(f'[id="{for_id}"]').first
            if await field.count() == 0:
                continue
            tag = await field.evaluate("el => el.tagName.toLowerCase()")
            if tag in ("textarea", "input"):
                try:
                    current = await field.input_value()
                except Exception:
                    current = ""
                if not current:
                    result["unanswered_questions"].append(text[:100])
                    log(f"    UNANSWERED (needs manual): '{text[:80]}'")

        # CAPTCHA check — never solve it, never submit through it
        if await captcha_blocking(page):
            result["captcha_detected"] = True
            result["error"] = "captcha_detected — flagged, not submitted"
            log(f"  Ashby: reCAPTCHA detected — flagging, not submitting: {url}")
            return result

        if result["unanswered_questions"]:
            result["error"] = "manual_required — unanswered bespoke questions"
            log(f"  Ashby: {len(result['unanswered_questions'])} bespoke question(s) unanswered — flagging for manual review")
            return result

        if dry_run:
            log(f"  [DRY RUN] Ashby form filled — not submitting: {url}")
            result["success"] = True
            return result

        await click_if_exists(page, 'button[type="submit"], button:has-text("Submit Application")')
        await page.wait_for_timeout(3000)
        result["success"] = await check_success(page)
        if not result["success"]:
            result["error"] = "No confirmation found after submit"

    except Exception as e:
        result["error"] = str(e)
        log(f"  Ashby error: {e}")
    finally:
        await browser.close()
        await pw.stop()
    return result


def apply_ashby(url, resume_pdf, profile, custom_answers=None, dry_run=False, headless=True, company="", role=""):
    return asyncio.run(_apply(url, resume_pdf, profile, custom_answers or {}, dry_run, headless, company, role))


if __name__ == "__main__":
    import argparse, json
    p = argparse.ArgumentParser()
    p.add_argument("--url",      required=True)
    p.add_argument("--resume",   required=True)
    p.add_argument("--cover-letter", default="", dest="cover_letter")
    p.add_argument("--profile",  default="scripts/profile.json")
    p.add_argument("--answers",  default="{}")
    p.add_argument("--dry-run",  action="store_true")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--company",  default="")
    p.add_argument("--role",     default="")
    args = p.parse_args()
    profile = json.load(open(args.profile))
    secrets_path = os.path.join(os.path.dirname(args.profile), "secrets.local.json")
    if os.path.exists(secrets_path):
        profile.update(json.load(open(secrets_path)))
    if args.cover_letter:
        profile["cover_letter_path"] = args.cover_letter
    answers = json.loads(args.answers)
    result = apply_ashby(args.url, args.resume, profile, answers, args.dry_run, args.headless, args.company, args.role)
    print(json.dumps(result, indent=2))
