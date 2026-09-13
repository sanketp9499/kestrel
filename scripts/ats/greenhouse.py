"""greenhouse.py — Apply to Greenhouse ATS jobs."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import asyncio
from ats.base import (launch_browser, fill_if_exists, upload_file, click_if_exists, check_success, submit_and_confirm, evidence_dir_for,
                       answer_custom_questions, maybe_create_account)
from ats.base import emit_result
from daily_log import log
import daily_log

async def _apply(url, resume_pdf, profile, custom_answers, dry_run, headless=True, company="", role=""):
    pw, browser, page = await launch_browser(headless=headless)
    result = {"success": False, "error": None, "dry_run": dry_run, "answered_questions": [], "skipped_questions": [], "account_created": False}
    try:
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # Some Greenhouse boards land on a listing page with an "Apply" button
        # before the actual form.
        await click_if_exists(page, 'a:has-text("Apply for this job"), button:has-text("Apply for this job")')
        await page.wait_for_timeout(1000)

        # Account creation, if this board requires one (approved by user)
        if await maybe_create_account(page, profile["email"], profile.get("account_password", "")):
            result["account_created"] = True
            log(f"  Greenhouse: account fields detected and filled at {url}")

        # Standard fields
        first, *rest = profile["name"].split()
        last = " ".join(rest) if rest else first
        await fill_if_exists(page, 'input#first_name, input[name="first_name"]', first)
        await fill_if_exists(page, 'input#last_name,  input[name="last_name"]',  last)
        await fill_if_exists(page, 'input#email,       input[name="email"]',      profile["email"])
        await fill_if_exists(page, 'input#phone,       input[name="phone"]',      profile["phone"])

        # Resume upload
        uploaded = await upload_file(page, 'input[type="file"]', resume_pdf)
        if not uploaded:
            result["error"] = "Resume upload failed — no file input found"
            log(f"  Greenhouse: resume upload failed at {url}")
            return result
        await page.wait_for_timeout(1000)

        # Cover letter upload (if a second file field exists and CL path is provided)
        inputs = await page.query_selector_all('input[type="file"]')
        cl_path = profile.get("cover_letter") or profile.get("cover_letter_path")
        if len(inputs) > 1 and cl_path and os.path.exists(cl_path):
            await inputs[1].set_input_files(cl_path)
            log(f"  Greenhouse: cover letter uploaded from {cl_path}")

        # Caller-supplied overrides first
        for question_text, answer in (custom_answers or {}).items():
            labels = await page.query_selector_all("label")
            for label in labels:
                txt = (await label.inner_text()).strip().lower()
                if question_text.lower()[:30] in txt:
                    for_id = await label.get_attribute("for")
                    if for_id:
                        await fill_if_exists(page, f"#{for_id}", answer)
                    break

        # QA bank for anything else (real profile facts; EEO questions skipped)
        answered, skipped = await answer_custom_questions(page, profile, company, role)
        result["answered_questions"] = answered
        result["skipped_questions"] = skipped
        for a in answered:
            log(f"    Q&A: '{a['question']}' -> '{a['answer']}'")
        for s in skipped:
            log(f"    Q&A SKIPPED (EEO/identity): '{s}'")

        if dry_run:
            log(f"  [DRY RUN] Greenhouse form filled — not submitting: {url}")
            result["success"] = True
            return result

        evidence_dir = evidence_dir_for(company, role)
        verdict = await submit_and_confirm(page, 'button[type="submit"], input[type="submit"]',
                                           evidence_dir=evidence_dir, label="Greenhouse")
        result["verdict"] = verdict["verdict"]
        result["confirm_signal"] = verdict["signal"]
        result["validation_errors"] = verdict["errors"]
        result["evidence"] = verdict["evidence"]
        result["success"] = verdict["verdict"] == "applied"
        result["submit_clicked"] = verdict["verdict"] in ("applied", "unconfirmed")
        result["retry_safe"] = verdict["verdict"] in ("blocked", "no_button", "held_safe_mode")
        if verdict["verdict"] == "blocked":
            result["error"] = "blocked - nothing sent: " + "; ".join(verdict["errors"])[:180]
        elif verdict["verdict"] == "no_button":
            result["error"] = "manual_required - no submit control (not submitted)"
        elif verdict["verdict"] == "unconfirmed":
            result["error"] = "submitted_unconfirmed - verify by hand, do not resubmit"

    except Exception as e:
        result["error"] = str(e)
        log(f"  Greenhouse error: {e}")
    finally:
        await browser.close()
        await pw.stop()
    return result

def apply_greenhouse(url, resume_pdf, profile, custom_answers=None, dry_run=False, headless=True, company="", role=""):
    return asyncio.run(_apply(url, resume_pdf, profile, custom_answers or {}, dry_run, headless, company, role))

if __name__ == "__main__":
    import argparse, json
    p = argparse.ArgumentParser()
    p.add_argument("--url",           required=True)
    p.add_argument("--resume",        required=True)
    p.add_argument("--cover-letter",  default="", dest="cover_letter")
    p.add_argument("--profile",       default="Scripts/sanket_profile.json")
    p.add_argument("--answers",       default="{}")
    p.add_argument("--dry-run",       action="store_true")
    p.add_argument("--headless",      action="store_true")
    p.add_argument("--company",       default="")
    p.add_argument("--role",          default="")
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
    result  = apply_greenhouse(args.url, args.resume, profile, answers, args.dry_run, args.headless, args.company, args.role)
    emit_result(result)
