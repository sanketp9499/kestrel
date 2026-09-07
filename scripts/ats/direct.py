"""direct.py — Apply to company career pages directly (best-effort form detection).
Also the fallback for one-off ATSs without a dedicated script (SmartRecruiters,
iCIMS, BambooHR, ApplyToJob, Jobvite, and similar)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import asyncio
from ats.base import (launch_browser, fill_if_exists, upload_file, click_if_exists, check_success,
                       answer_custom_questions, maybe_create_account, captcha_blocking, upload_cover_letter)
from daily_log import log


# Maps CSS selector groups to profile keys.
# Each value in the dict is tried left-to-right; the first match wins (via fill_if_exists).
FIELD_MAP = {
    'input[name*="first"], input[placeholder*="First"], input[id*="first"]': "first_name",
    'input[name*="last"],  input[placeholder*="Last"],  input[id*="last"]':  "last_name",
    'input[type="email"],  input[name*="email"],         input[id*="email"]': "email",
    'input[type="tel"],    input[name*="phone"],          input[id*="phone"]': "phone",
    'input[name*="linkedin"], input[placeholder*="LinkedIn"]':                "linkedin",
    'input[name*="portfolio"],input[placeholder*="portfolio"],input[placeholder*="website"]': "portfolio",
}


async def _apply(url, resume_pdf, profile, custom_answers, dry_run, headless=True, company="", role=""):
    pw, browser, page = await launch_browser(headless=headless)
    result = {"success": False, "error": None, "dry_run": dry_run, "answered_questions": [],
               "skipped_questions": [], "account_created": False, "captcha_detected": False}
    try:
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # Some job-board pages (YC jobs, listing pages) need one more Apply
        # click before the real form appears
        await click_if_exists(page, 'a:has-text("Apply"), button:has-text("Apply")')
        await page.wait_for_timeout(1500)

        if await captcha_blocking(page):
            result["captcha_detected"] = True
            result["error"] = "captcha_detected — flagged, not submitted"
            log(f"  Direct: CAPTCHA detected — flagging, not attempting: {url}")
            return result

        if await maybe_create_account(page, profile["email"], profile.get("account_password", "")):
            result["account_created"] = True
            log(f"  Direct: account fields detected and filled at {url}")

        flat_profile = {
            "first_name": profile["name"].split()[0],
            "last_name":  " ".join(profile["name"].split()[1:]),
            "email":      profile["email"],
            "phone":      profile["phone"],
            "linkedin":   profile.get("linkedin", ""),
            "portfolio":  profile.get("portfolio", ""),
        }

        for selector_group, key in FIELD_MAP.items():
            for sel in selector_group.split(","):
                await fill_if_exists(page, sel.strip(), flat_profile.get(key, ""))

        # Upload resume to first file input found
        uploaded = await upload_file(page, 'input[type="file"]', resume_pdf)
        await upload_cover_letter(page, profile)
        if not uploaded:
            result["error"] = "manual_required — no file input (not submitted)"
            log(f"  Direct: no file input found — manual required: {url}")
            return result

        await page.wait_for_timeout(1000)

        answered, skipped = await answer_custom_questions(page, profile, company, role)
        result["answered_questions"] = answered
        result["skipped_questions"] = skipped
        for a in answered:
            log(f"    Q&A: '{a['question']}' -> '{a['answer']}'")
        for s in skipped:
            log(f"    Q&A SKIPPED (EEO/identity): '{s}'")

        if dry_run:
            log(f"  [DRY RUN] Direct form filled — not submitting: {url}")
            result["success"] = True
            return result

        await click_if_exists(
            page,
            'button[type="submit"], input[type="submit"], '
            'button:has-text("Submit"), button:has-text("Apply")',
        )
        await page.wait_for_timeout(3000)
        result["success"] = await check_success(page)
        if not result["success"]:
            # Submit WAS clicked — never auto-retry this state, it duplicates applications
            result["error"] = "submitted_unconfirmed — no confirmation after submit"
            result["submit_clicked"] = True
            log(f"  Direct: no confirmation detected — marking MANUAL: {url}")

    except Exception as e:
        result["error"] = str(e)
        log(f"  Direct error at {url}: {e}")
    finally:
        await browser.close()
        await pw.stop()
    return result


def apply_direct(url, resume_pdf, profile, custom_answers=None, dry_run=False, headless=True, company="", role=""):
    return asyncio.run(_apply(url, resume_pdf, profile, custom_answers or {}, dry_run, headless, company, role))


if __name__ == "__main__":
    import argparse, json
    p = argparse.ArgumentParser()
    p.add_argument("--url",      required=True)
    p.add_argument("--resume",   required=True)
    p.add_argument("--cover-letter", default="", dest="cover_letter")
    p.add_argument("--profile",  default="scripts/profile.json")
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
    result = apply_direct(args.url, args.resume, profile, dry_run=args.dry_run, headless=args.headless, company=args.company, role=args.role)
    print(json.dumps(result, indent=2))
