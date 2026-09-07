"""lever.py — Apply to Lever ATS jobs."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import asyncio
from ats.base import (launch_browser, fill_if_exists, upload_file, click_if_exists, check_success,
                       answer_custom_questions, maybe_create_account, upload_cover_letter)
from daily_log import log

async def _apply(url, resume_pdf, profile, custom_answers, dry_run, headless=True, company="", role=""):
    pw, browser, page = await launch_browser(headless=headless)
    result = {"success": False, "error": None, "dry_run": dry_run, "answered_questions": [], "skipped_questions": [], "account_created": False}
    try:
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # Click Apply button if this is a posting page (not the form yet)
        await click_if_exists(page, 'a[href*="/apply"], button:has-text("Apply")')
        await page.wait_for_timeout(1500)

        if await maybe_create_account(page, profile["email"], profile.get("account_password", "")):
            result["account_created"] = True
            log(f"  Lever: account fields detected and filled at {url}")

        await fill_if_exists(page, 'input[name="name"]',            profile["name"])
        await fill_if_exists(page, 'input[name="email"]',           profile["email"])
        await fill_if_exists(page, 'input[name="phone"]',           profile["phone"])
        await fill_if_exists(page, 'input[name="org"]',             profile.get("current_company", "ExampleCo"))
        await fill_if_exists(page, 'input[name="urls[LinkedIn]"]',  profile.get("linkedin", ""))
        await fill_if_exists(page, 'input[name="urls[Portfolio]"]', profile.get("portfolio", ""))

        await upload_file(page, 'input[type="file"]', resume_pdf)
        await upload_cover_letter(page, profile)
        await page.wait_for_timeout(1000)

        for question_text, answer in (custom_answers or {}).items():
            labels = await page.query_selector_all("label")
            for label in labels:
                txt = (await label.inner_text()).strip().lower()
                if question_text.lower()[:30] in txt:
                    for_id = await label.get_attribute("for")
                    if for_id:
                        await fill_if_exists(page, f"#{for_id}", answer)
                    break

        answered, skipped = await answer_custom_questions(page, profile, company, role)
        result["answered_questions"] = answered
        result["skipped_questions"] = skipped
        for a in answered:
            log(f"    Q&A: '{a['question']}' -> '{a['answer']}'")
        for s in skipped:
            log(f"    Q&A SKIPPED (EEO/identity): '{s}'")

        if dry_run:
            log(f"  [DRY RUN] Lever form filled — not submitting: {url}")
            result["success"] = True
            return result

        await click_if_exists(page, 'button[type="submit"]')
        await page.wait_for_timeout(3000)
        result["success"] = await check_success(page)
        if not result["success"]:
            result["error"] = "No confirmation found"

    except Exception as e:
        result["error"] = str(e)
        log(f"  Lever error: {e}")
    finally:
        await browser.close()
        await pw.stop()
    return result

def apply_lever(url, resume_pdf, profile, custom_answers=None, dry_run=False, headless=True, company="", role=""):
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
    result  = apply_lever(args.url, args.resume, profile, answers, args.dry_run, args.headless, args.company, args.role)
    print(json.dumps(result, indent=2))
