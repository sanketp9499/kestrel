"""workday.py — Apply via Workday ATS (best-effort; marks MANUAL if login wall or CAPTCHA detected).

Supported URL patterns:
  https://*.myworkdayjobs.com/
  https://*.wd1.myworkday.com/
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import asyncio
from ats.base import (launch_browser, fill_if_exists, upload_file, click_if_exists, check_success, submit_and_confirm, evidence_dir_for,
                       answer_custom_questions, maybe_create_account, captcha_blocking, upload_cover_letter)
from ats.base import emit_result
from daily_log import log
import daily_log



async def _apply(url, resume_pdf, profile, custom_answers, dry_run, headless=True, company="", role=""):
    pw, browser, page = await launch_browser(headless=headless)
    result = {"success": False, "error": None, "dry_run": dry_run, "answered_questions": [],
               "skipped_questions": [], "account_created": False}
    try:
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")

        # Use selector-based wait instead of a fixed sleep where possible
        try:
            await page.wait_for_selector(
                'button:has-text("Apply"), a:has-text("Apply")',
                timeout=10000,
            )
        except Exception:
            # Apply button not found — page may already be the form, or it may need JS
            pass

        # Detect CAPTCHA before doing anything else — never solved, always a hard stop
        if await captcha_blocking(page):
            result["error"] = "captcha_required"
            log(f"  Workday: CAPTCHA detected — marking MANUAL: {url}")
            return result

        # Click the Apply button to open the form
        await click_if_exists(page, 'a:has-text("Apply"), button:has-text("Apply")')
        await page.wait_for_timeout(1000)

        # Workday often gates the form behind a "Create Account" step — attempt
        # it (approved by user) rather than bailing to manual review
        create_btn = page.locator('button:has-text("Create Account"), a:has-text("Create Account")').first
        if await create_btn.count() > 0:
            await create_btn.click()
            await page.wait_for_timeout(1500)
        if await maybe_create_account(page, profile["email"], profile.get("account_password", "")):
            result["account_created"] = True
            log(f"  Workday: account fields detected and filled at {url}")
            await click_if_exists(page, 'button:has-text("Create Account"), button[type="submit"]')
            await page.wait_for_timeout(2000)

        # Wait for the first Workday form field to appear
        try:
            await page.wait_for_selector(
                'input[data-automation-id="legalNameSection_firstName"], '
                'input[data-automation-id="email"], '
                'input[type="file"]',
                timeout=10000,
            )
        except Exception:
            pass

        # Fill standard Workday fields
        first, *rest = profile["name"].split()
        last = " ".join(rest) if rest else first
        await fill_if_exists(
            page,
            'input[data-automation-id="legalNameSection_firstName"]',
            first,
        )
        await fill_if_exists(
            page,
            'input[data-automation-id="legalNameSection_lastName"]',
            last,
        )
        await fill_if_exists(
            page,
            'input[data-automation-id="email"]',
            profile["email"],
        )
        await fill_if_exists(
            page,
            'input[data-automation-id="phone"]',
            profile["phone"],
        )

        # Resume upload
        await upload_file(page, 'input[type="file"]', resume_pdf)
        await upload_cover_letter(page, profile)

        # Wait for upload processing
        try:
            await page.wait_for_selector(
                'button[data-automation-id="bottom-navigation-next-button"]',
                timeout=8000,
            )
        except Exception:
            pass

        if dry_run:
            log(f"  [DRY RUN] Workday form filled — not submitting: {url}")
            result["success"] = True
            return result

        # Navigate through multi-step Workday form — no step-count cap;
        # bounded by wall-clock time instead. Exits early via `break` the
        # moment there's no more Next button, so this only matters for
        # genuinely long multi-page forms.
        import time as _time
        _deadline = _time.monotonic() + 600  # 10 minutes
        while _time.monotonic() < _deadline:
            answered, skipped = await answer_custom_questions(page, profile, company, role)
            result["answered_questions"].extend(answered)
            result["skipped_questions"].extend(skipped)
            for a in answered:
                log(f"    Q&A: '{a['question']}' -> '{a['answer']}'")
            for s in skipped:
                log(f"    Q&A SKIPPED (EEO/identity): '{s}'")

            clicked = await click_if_exists(
                page,
                'button[data-automation-id="bottom-navigation-next-button"]',
            )
            if not clicked:
                break
            try:
                await page.wait_for_selector(
                    'button[data-automation-id="bottom-navigation-next-button"], '
                    'button[data-automation-id="bottom-navigation-submit-button"]',
                    timeout=8000,
                )
            except Exception:
                pass

        # Final submit
        evidence_dir = evidence_dir_for(company, role)
        verdict = await submit_and_confirm(page, 'button[data-automation-id="bottom-navigation-submit-button"]',
                                           evidence_dir=evidence_dir, label="Workday")
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
        log(f"  Workday error at {url}: {e}")
    finally:
        await browser.close()
        await pw.stop()
    return result


def apply_workday(url, resume_pdf, profile, custom_answers=None, dry_run=False, headless=True, company="", role=""):
    return asyncio.run(_apply(url, resume_pdf, profile, custom_answers or {}, dry_run, headless, company, role))


if __name__ == "__main__":
    import argparse, json
    p = argparse.ArgumentParser()
    p.add_argument("--url",      required=True)
    p.add_argument("--resume",   required=True)
    p.add_argument("--cover-letter", default="", dest="cover_letter")
    p.add_argument("--profile",  default="Scripts/sanket_profile.json")
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
    result = apply_workday(args.url, args.resume, profile, dry_run=args.dry_run, headless=args.headless, company=args.company, role=args.role)
    emit_result(result)
