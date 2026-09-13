"""base.py — Shared Playwright utilities for all ATS scripts."""
import asyncio
import datetime
import json
import os
import re
import sys
from playwright.async_api import async_playwright, Page

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from qa_bank import build_qa_bank, match_answer, is_excluded


# ---------------------------------------------------------------- result contract
#
# An adapter's verdict has to survive the trip back to the phase 5 runner. It
# did not on 2026-09-12: adapters pretty-printed their JSON, the runner accepted
# only a single-line object, so every verdict was discarded as "no_json_result"
# and the adapters were re-run by hand to recover them. Re-running an adapter is
# a second submission.
#
# The runner is regenerated from the runbook on every run, so the contract
# cannot live in the runner. Both sides import these two functions instead.

RESULT_MARKER = "KESTREL_RESULT"


def emit_result(result: dict) -> None:
    """End an adapter with its verdict, in both the forms that are needed.

    The indented copy is for whoever reads the log. The marker line is the
    machine contract: one line, compact, always last, and impossible to confuse
    with an adapter's own progress output.
    """
    print(json.dumps(result, indent=2))
    print(RESULT_MARKER, json.dumps(result, separators=(",", ":")), flush=True)


def parse_result(stdout: str, stderr: str = "") -> dict:
    """Recover an adapter's verdict from its output. Never raises.

    Falls back to scanning for a bare JSON object so that output captured
    before the marker existed, or from a third-party script, still reads. The
    fallback deliberately picks the object that ends LAST rather than the first
    "{" it sees: adapters log lines like ``uploaded from {folder}\\x.pdf`` and
    ``answered {"years": "3"}``, and the greedy parsers this replaces started
    matching at those and then raised on the malformed span.
    """
    streams = [s for s in (stdout, stderr) if s]
    for text in streams:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith(RESULT_MARKER):
                try:
                    return json.loads(line[len(RESULT_MARKER):].strip())
                except ValueError:
                    pass  # truncated marker line: keep looking, then fall back

    decoder = json.JSONDecoder()
    best = None
    for text in streams:
        for i, ch in enumerate(text):
            if ch != "{":
                continue
            try:
                obj, end = decoder.raw_decode(text[i:])
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            # Widest object wins, so a nested dict never outranks its parent.
            if best is None or (i + end) > best[0] or ((i + end) == best[0] and i < best[1]):
                best = (i + end, i, obj)
    if best:
        return best[2]

    return {"success": False, "error": "no_adapter_result",
            "raw": ("\n".join(streams))[-600:]}


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

# Phrases must be specific to a POST-SUBMIT confirmation. Loose fragments like
# "your application" or a bare "thank you" also appear on unsubmitted job pages
# ("Start Your Application"), which produced false "applied" records, so they
# stay out. Everything here only makes sense after a submission.
CONFIRM_PHRASES = [
    "application submitted", "application received", "application complete",
    "application has been received", "application is complete",
    "we received your application", "we have received your application",
    "we've received your application", "successfully submitted",
    "submitted successfully", "thank you for applying", "thanks for applying",
    "thank you for your application", "thanks for your application",
    "your application has been submitted", "application was submitted",
    "you have applied", "you've applied", "already applied",
    "submission received", "we'll be in touch", "we will be in touch",
    "we'll review your application", "review your application and get back",
]

# An ATS that redirects rather than swapping the DOM lands somewhere like
# .../confirmation, .../thank-you, ?success=true, /application/complete.
CONFIRM_URL_RE = re.compile(
    r"(thank[-_]?you|confirmation|confirmed|success|submitted|applied|complete)", re.I)

# Text that means the form refused the submission. Kept narrow: these are
# validation phrases, not words that merely appear near a form.
BLOCK_PHRASES = [
    "is required", "are required", "required field", "this field is required",
    "please complete", "please fill", "please enter", "please select",
    "please answer", "must be provided", "cannot be blank", "can't be blank",
    "invalid email", "enter a valid",
]


async def _visible_text(page: Page, timeout: int = 5000) -> str:
    try:
        return (await page.locator("body").inner_text(timeout=timeout)).lower()
    except Exception:
        return ""


async def find_validation_errors(page: Page, limit: int = 8) -> list:
    """Visible field-level errors that stopped the form from submitting.

    Without this the engine could not tell "submitted, confirmation not
    recognised" from "never submitted, a required question was blank" — and it
    recorded both as the former, which is how blocked applications became
    silent no-ops.
    """
    errors, seen = [], set()
    selectors = ('[aria-invalid="true"], [role="alert"], .error, .errors, '
                 '.error-message, .field-error, .invalid-feedback, '
                 '[class*="errorMessage"], [class*="ErrorMessage"], '
                 '[data-error], [id*="error" i]')
    try:
        nodes = page.locator(selectors)
        count = min(await nodes.count(), 40)
    except Exception:
        return errors
    for i in range(count):
        node = nodes.nth(i)
        try:
            if not await node.is_visible():
                continue
            text = " ".join((await node.inner_text(timeout=2000) or "").split())
        except Exception:
            continue
        if not text or len(text) > 200:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        errors.append(text)
        if len(errors) >= limit:
            break
    return errors


async def _confirmed(page: Page, before_url: str, body: str) -> str:
    """Name the confirmation signal, or return '' when there is none."""
    for phrase in CONFIRM_PHRASES:
        if phrase in body:
            return f"text:{phrase}"
    if page.url != before_url and CONFIRM_URL_RE.search(page.url):
        return f"url:{page.url[:120]}"
    return ""


async def _form_present(page: Page) -> bool:
    """Is the application form still on screen?"""
    try:
        for sel in ('input[type="file"]', 'button[type="submit"]',
                    'input[type="submit"]'):
            if await page.locator(sel).first.count() > 0:
                return True
    except Exception:
        return True          # unknown means "assume still there", never guess success
    return False


def evidence_dir_for(company: str = "", role: str = "") -> str:
    """Where a submission's proof screenshot goes.

    A submission nobody can verify is the failure this engine kept producing,
    so every applied/unconfirmed outcome leaves a full-page screenshot behind.
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "-", f"{company} {role}".strip()).strip("-") or "unknown"
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apply_evidence", slug[:80])


async def unanswered_required(page: Page, limit: int = 25) -> list:
    """Required fields still empty, checked BEFORE the submit click.

    This is the missing diagnostic. A live Lever form asks for country of work,
    work authorization, earliest start date, referral source and a 50-word essay,
    all marked required and none of them reachable by the label[for=id] matching
    in answer_custom_questions(). The form then refuses the submission, and the
    old engine recorded that refusal as "submitted, no confirmation".

    Returns a list of {"label", "kind"} for every required control left empty.
    """
    try:
        return await page.evaluate(r"""() => {
          const out = [];
          const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
          const labelFor = (el) => {
            if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                         if (l) return l.innerText; }
            const w = el.closest('label'); if (w) return w.innerText;
            const grp = el.closest('.application-question, [class*="question"], fieldset, li, .field');
            return grp ? grp.innerText : (el.name || el.placeholder || '');
          };
          const clean = (t) => (t || '').replace(/\s+/g, ' ').trim().slice(0, 110);
          const required = (el, text) => el.required || el.getAttribute('aria-required') === 'true'
            || /\*\s*$/.test((text || '').trim()) || (text || '').includes('*');

          const seenGroups = new Set();
          document.querySelectorAll('input, select, textarea').forEach(el => {
            if (!visible(el) || el.disabled || el.type === 'hidden') return;
            const text = clean(labelFor(el));
            if (!text || !required(el, text)) return;
            if (el.type === 'radio' || el.type === 'checkbox') {
              const name = el.name || text;
              if (seenGroups.has(name)) return;
              seenGroups.add(name);
              const group = el.name
                ? document.querySelectorAll(`input[name="${CSS.escape(el.name)}"]`) : [el];
              if (![...group].some(g => g.checked)) out.push({ label: text, kind: el.type });
              return;
            }
            if (el.tagName === 'SELECT') {
              const v = el.value;
              if (!v || /^select/i.test(el.options[el.selectedIndex]?.text || ''))
                out.push({ label: text, kind: 'select' });
              return;
            }
            if (el.type === 'file') {
              if (!el.files || el.files.length === 0) out.push({ label: text, kind: 'file' });
              return;
            }
            if (!el.value || !el.value.trim()) out.push({ label: text, kind: el.tagName.toLowerCase() });
          });
          return out;
        }""")
    except Exception:
        return []


async def submit_and_confirm(page: Page, submit_selector: str, *,
                             timeout_ms: int = 25000, evidence_dir: str = None,
                             label: str = "") -> dict:
    """Click submit, then wait for a real outcome instead of a fixed 3 seconds.

    Returns {"verdict", "signal", "errors", "url", "responses", "evidence"} where
    verdict is one of:

      applied      a confirmation signal was seen. Safe to count as applied.
      blocked      the form rejected the submission and is still on screen with
                   validation errors. Nothing was sent, so it IS safe to retry
                   once the named fields are handled.
      unconfirmed  submit was clicked and nothing conclusive appeared before the
                   timeout. Never auto-retry this: it may already be in.
      no_button    no enabled submit control was found. Nothing was clicked.
    """
    from daily_log import log

    before_url = page.url
    posts = []

    def _on_response(resp):
        try:
            if resp.request.method in ("POST", "PUT", "PATCH"):
                posts.append({"url": resp.url[:160], "status": resp.status})
        except Exception:
            pass

    page.on("response", _on_response)
    out = {"verdict": "unconfirmed", "signal": None, "errors": [],
           "url": before_url, "responses": posts, "evidence": None,
           "unanswered_required": []}
    try:
        button = page.locator(submit_selector).first
        if await button.count() == 0 or not await button.is_enabled():
            out["verdict"] = "no_button"
            out["signal"] = "no enabled submit control matched " + submit_selector[:60]
            return out

        # Safe mode is checked here, immediately before the click, because every
        # adapter reaches the outside world through this one line. The form is
        # already filled at this point, so the run still proves it could apply.
        out["unanswered_required"] = await unanswered_required(page)
        if out["unanswered_required"]:
            names = "; ".join(u["label"] for u in out["unanswered_required"])[:200]
            log(f"  {label or 'submit'}: {len(out['unanswered_required'])} required field(s) still empty - {names}")

        import safe_mode
        if safe_mode.guard("submit"):
            out["verdict"] = "held_safe_mode"
            out["signal"] = safe_mode.reason("submit")
            if evidence_dir:
                try:
                    os.makedirs(evidence_dir, exist_ok=True)
                    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                    shot = os.path.join(evidence_dir, f"filled-not-submitted-{stamp}.png")
                    await page.screenshot(path=shot, full_page=True)
                    out["evidence"] = shot
                except Exception:
                    pass
            return out

        had_form = await _form_present(page)
        out["unanswered_required"] = await unanswered_required(page)
        if out["unanswered_required"]:
            names = "; ".join(u["label"] for u in out["unanswered_required"])[:200]
            log(f"  {label or 'submit'}: {len(out['unanswered_required'])} required field(s) still empty - {names}")
        await button.click()

        # Poll for whichever lands first: a confirmation, a validation error, or
        # the form being replaced. Anything is better than sleeping 3s and
        # guessing from whatever happens to be in the DOM at that instant.
        deadline = timeout_ms
        step = 700
        waited = 0
        while waited < deadline:
            await page.wait_for_timeout(step)
            waited += step

            body = await _visible_text(page)
            signal = await _confirmed(page, before_url, body)
            if signal:
                out.update(verdict="applied", signal=signal, url=page.url)
                break

            errors = await find_validation_errors(page)
            phrase_hit = next((p for p in BLOCK_PHRASES if p in body), None)
            if (errors or phrase_hit) and await _form_present(page):
                out.update(verdict="blocked", url=page.url,
                           errors=errors or [phrase_hit],
                           signal="validation:" + (errors[0][:80] if errors else phrase_hit))
                break

            # The form vanished with no error anywhere: the ATS replaced it with
            # its own success view. Weaker than a phrase, stronger than nothing.
            if had_form and waited >= 3000 and not await _form_present(page) and not errors:
                out.update(verdict="applied", signal="form_replaced", url=page.url)
                break

        if out["verdict"] == "unconfirmed":
            ok_post = next((p for p in posts if 200 <= p["status"] < 300
                            and re.search(r"appl|submit|candidate", p["url"], re.I)), None)
            if ok_post:
                # Not proof the ATS accepted it, but proof something was posted:
                # worth recording so a human verification has somewhere to start.
                out["signal"] = f"post {ok_post['status']} {ok_post['url'][:90]}"
            out["url"] = page.url

        if evidence_dir and out["verdict"] in ("applied", "unconfirmed"):
            try:
                os.makedirs(evidence_dir, exist_ok=True)
                stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                shot = os.path.join(evidence_dir, f"submit-{out['verdict']}-{stamp}.png")
                await page.screenshot(path=shot, full_page=True)
                out["evidence"] = shot
            except Exception as e:
                log(f"  evidence screenshot failed: {str(e)[:80]}")

        tag = label or "submit"
        if out["verdict"] == "applied":
            log(f"  {tag}: CONFIRMED ({out['signal']})")
        elif out["verdict"] == "blocked":
            log(f"  {tag}: BLOCKED, nothing sent - {'; '.join(out['errors'])[:160]}")
        elif out["verdict"] == "no_button":
            log(f"  {tag}: no submit control found, nothing sent")
        else:
            log(f"  {tag}: submitted, no confirmation in {timeout_ms // 1000}s"
                + (f" [{out['signal']}]" if out["signal"] else "")
                + " - verify by hand, do NOT resubmit")
        return out
    finally:
        try:
            page.remove_listener("response", _on_response)
        except Exception:
            pass


async def check_success(page: Page) -> bool:
    """Back-compat wrapper: True only when a confirmation signal is present."""
    body = await _visible_text(page)
    # page.url as "before" so only the text signal can fire: a job URL that
    # happens to contain "complete" must never read as a confirmation.
    return bool(await _confirmed(page, page.url, body))


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
