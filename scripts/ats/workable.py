"""workable.py — Apply to Workable ATS jobs."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import asyncio
from ats.base import launch_browser, fill_if_exists, upload_file, click_if_exists, check_success, upload_cover_letter
from daily_log import log

async def _apply(url, resume_pdf, profile, custom_answers, dry_run):
    pw, browser, page = await launch_browser()
    result = {"success": False, "error": None, "dry_run": dry_run}
    try:
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        await click_if_exists(page, 'button:has-text("Apply"), a:has-text("Apply Now")')
        await page.wait_for_timeout(1500)

        first, last = (profile["name"].split(maxsplit=1) + [profile["name"]])[:2]
        await fill_if_exists(page, 'input[name="firstname"], input[placeholder*="First"]', first)
        await fill_if_exists(page, 'input[name="lastname"],  input[placeholder*="Last"]',  last)
        await fill_if_exists(page, 'input[name="email"],     input[type="email"]',          profile["email"])
        await fill_if_exists(page, 'input[name="phone"],     input[type="tel"]',            profile["phone"])
        await fill_if_exists(page, 'input[placeholder*="LinkedIn"]',                        profile.get("linkedin", ""))
        await fill_if_exists(page, 'input[placeholder*="portfolio"], input[placeholder*="website"]',
                             profile.get("portfolio", ""))

        await upload_file(page, 'input[type="file"]', resume_pdf)
        await upload_cover_letter(page, profile)
        await page.wait_for_timeout(1000)

        # Custom questions — match labels by text prefix
        for question_text, answer in (custom_answers or {}).items():
            labels = await page.query_selector_all("label")
            for label in labels:
                if question_text.lower()[:30] in (await label.inner_text()).lower():
                    for_id = await label.get_attribute("for")
                    if for_id:
                        await fill_if_exists(page, f"#{for_id}", answer)
                    break

        if dry_run:
            log(f"  [DRY RUN] Workable form filled — not submitting: {url}")
            result["success"] = True
            return result

        await click_if_exists(page, 'button[type="submit"]')
        await page.wait_for_timeout(3000)
        result["success"] = await check_success(page)
        if not result["success"]:
            result["error"] = "No confirmation found"

    except Exception as e:
        result["error"] = str(e)
        log(f"  Workable error: {e}")
    finally:
        await browser.close()
        await pw.stop()
    return result

def apply_workable(url, resume_pdf, profile, custom_answers=None, dry_run=False):
    return asyncio.run(_apply(url, resume_pdf, profile, custom_answers or {}, dry_run))

if __name__ == "__main__":
    import argparse, json
    p = argparse.ArgumentParser()
    p.add_argument("--url",      required=True)
    p.add_argument("--resume",   required=True)
    p.add_argument("--cover-letter", default="", dest="cover_letter")
    p.add_argument("--profile",  default="scripts/profile.json")
    p.add_argument("--answers",  default="{}")
    p.add_argument("--dry-run",  action="store_true")
    args = p.parse_args()
    profile = json.load(open(args.profile))
    secrets_path = os.path.join(os.path.dirname(args.profile), "secrets.local.json")
    if os.path.exists(secrets_path):
        profile.update(json.load(open(secrets_path)))
    if args.cover_letter:
        profile["cover_letter_path"] = args.cover_letter
    answers = json.loads(args.answers)
    result  = apply_workable(args.url, args.resume, profile, answers, args.dry_run)
    print(json.dumps(result, indent=2))
