"""base.py — Shared Playwright utilities for all ATS scripts."""
import asyncio
import os
import sys
from playwright.async_api import async_playwright, Page

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from qa_bank import build_qa_bank, match_answer, is_excluded


async def launch_browser(headless: bool = True, user_data_dir: str = None):
    """Launch a Chromium browser context.

    If *user_data_dir* is provided the browser is launched as a persistent
    context so that an existing Chrome login session is reused (needed for
    LinkedIn / Indeed Easy Apply).  Returns ``(pw, browser, page)`` in both
    cases so call-sites are identical.
    """
    pw = await async_playwright().start()
    if user_data_dir:
        # Persistent context — reuses the user's real Chrome profile so they
        # are already logged in to LinkedIn / Indeed / etc.
        browser = await pw.chromium.launch_persistent_context(
            user_data_dir,
            headless=headless,
            channel="chrome",
            args=["--profile-directory=Default"],
        )
        page = await browser.new_page()
        return pw, browser, page
    browser = await pw.chromium.launch(headless=headless)
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
    page = await context.new_page()
    return pw, browser, page

async def fill_if_exists(page: Page, selector: str, value: str):
    try:
        el = page.locator(selector).first
        if await el.count() > 0:
            await el.fill(str(value), timeout=8000)
    except Exception as e:
        from daily_log import log
        log(f"  fill_if_exists({selector[:40]}): {e}")

async def upload_cover_letter(page: Page, profile: dict) -> bool:
    """Attach the cover letter to a second file input, when the form has one.

    Plenty of forms take a resume and nothing else, so a missing second input
    is a normal outcome, not a failure. Call this after the resume upload —
    the resume must already hold the first input.
    """
    path = profile.get("cover_letter") or profile.get("cover_letter_path")
    if not path or not os.path.exists(path):
        return False
    inputs = await page.query_selector_all('input[type="file"]')
    if len(inputs) < 2:
        return False
    try:
        await inputs[1].set_input_files(path)
        from daily_log import log
        log(f"  cover letter uploaded from {path}")
        return True
    except Exception as e:
        from daily_log import log
        log(f"  cover letter upload failed ({str(e)[:60]})")
        return False


async def upload_file(page: Page, selector: str, file_path: str):
    try:
        el = page.locator(selector).first
        if await el.count() > 0:
            await el.set_input_files(file_path)
            return True
    except Exception:
        pass
    return False

async def click_if_exists(page: Page, selector: str):
    try:
        el = page.locator(selector).first
        if await el.count() > 0:
            await el.click()
            return True
    except Exception:
        pass
    return False

async def check_success(page: Page) -> bool:
    content = await page.content()
    # Phrases must be specific to a POST-SUBMIT confirmation. Loose fragments
    # like "your application" or a bare "thank you" also appear on unsubmitted
    # job pages ("Start Your Application"), which produced false "applied"
    # records, so they are deliberately excluded.
    return any(kw in content.lower() for kw in [
        "application submitted", "application received",
        "we received your application", "we have received your application",
        "successfully submitted", "thank you for applying",
        "thanks for applying", "your application has been submitted",
        "application was submitted",
    ])


async def answer_custom_questions(page: Page, profile: dict, company: str = "", role: str = "") -> tuple:
    """Scan every label on the page, match against the shared QA bank, and
    fill/select/check the associated field. EEO/identity questions are
    skipped on purpose — logged, not guessed. Returns (answered, skipped)."""
    bank = build_qa_bank(profile, company, role)
    answered, skipped = [], []
    labels = await page.query_selector_all("label")
    for label in labels:
        try:
            label_text = (await label.inner_text() or "").strip()
        except Exception:
            continue
        if not label_text or len(label_text) < 5:
            continue
        if is_excluded(label_text):
            skipped.append(label_text[:60])
            continue
        kind, value = match_answer(label_text, bank)
        if not kind:
            continue
        for_id = await label.get_attribute("for")
        if not for_id:
            continue
        field = page.locator(f'[id="{for_id}"]').first
        if await field.count() == 0:
            continue
        try:
            tag = await field.evaluate("el => el.tagName.toLowerCase()")
            if kind == "text" and tag in ("input", "textarea"):
                current = await field.input_value()
                if not current:
                    await field.fill(str(value))
                    answered.append({"question": label_text[:80], "answer": str(value)})
            elif kind == "choice" and tag == "select":
                options = await field.locator("option").all_inner_texts()
                match = next((o for o in options if value.lower() in o.lower()), None)
                if match:
                    await field.select_option(label=match)
                    answered.append({"question": label_text[:80], "answer": match})
            elif kind == "choice" and tag == "input":
                input_type = await field.get_attribute("type")
                if input_type == "radio":
                    name = await field.get_attribute("name")
                    if name:
                        group = page.locator(f'input[type="radio"][name="{name}"]')
                        for gi in range(await group.count()):
                            radio = group.nth(gi)
                            rid = await radio.get_attribute("id")
                            if not rid:
                                continue
                            rlabel = page.locator(f'label[for="{rid}"]').first
                            if await rlabel.count() > 0:
                                rtext = (await rlabel.inner_text() or "").strip()
                                if value.lower() in rtext.lower():
                                    await radio.check()
                                    answered.append({"question": label_text[:80], "answer": rtext})
                                    break
        except Exception:
            continue
    return answered, skipped


async def maybe_create_account(page: Page, email: str, password: str) -> bool:
    """Detect an account-creation / sign-up form (presence of a password
    field) and fill it in with the given credentials. Returns True if an
    account-creation form was detected and filled."""
    pw_fields = await page.query_selector_all('input[type="password"]')
    if not pw_fields:
        return False
    email_field = page.locator('input[type="email"], input[name*="email" i], input[id*="email" i]').first
    filled = False
    try:
        if await email_field.count() > 0:
            current = await email_field.input_value(timeout=5000)
            if not current:
                await email_field.fill(email, timeout=8000)
                filled = True
    except Exception as e:
        # A hidden/disabled sign-in field must not abort the whole application
        from daily_log import log
        log(f"  maybe_create_account: email field not fillable ({str(e)[:60]})")
    for pf in pw_fields:
        try:
            await pf.fill(password, timeout=8000)
            filled = True
        except Exception:
            continue
    return filled


_CAPTCHA_TEXT = ["i'm not a robot", "i am not a robot", "are you a robot",
                 "verify you are human", "verify you're human"]


async def captcha_blocking(page) -> bool:
    """True only for a captcha widget actually rendered on the page.

    Scanning raw HTML for "recaptcha", or looking for .grecaptcha-badge,
    false-positives on every site that loads the reCAPTCHA script or shows the
    invisible-reCAPTCHA badge (256x60) — neither blocks a submission."""
    frames = page.locator('iframe[src*="recaptcha"], iframe[src*="hcaptcha"]')
    for i in range(await frames.count()):
        fr = frames.nth(i)
        try:
            if not await fr.is_visible():
                continue
            if await fr.evaluate("e => !!e.closest('.grecaptcha-badge')"):
                continue
            box = await fr.bounding_box()
        except Exception:
            continue
        if box and box["width"] >= 200 and box["height"] > 65:
            return True
    try:
        body = (await page.locator("body").inner_text(timeout=5000)).lower()
    except Exception:
        return False
    return any(t in body for t in _CAPTCHA_TEXT)
