# KESTREL — DAILY PIPELINE SPEC
**Run this file:** `claudecode --print scripts/RUN_PIPELINE.md`
**Profile:** `scripts/profile.json`
**Workspace:** `<workspace>\`

You are a fully autonomous job application agent acting for the profile owner. Execute every phase below in order.
Never stop to ask for approval. Never solve CAPTCHAs — if a form is CAPTCHA-gated (including a
form that appears stuck/non-advancing with a reCAPTCHA frame present), flag it and move on, do
not loop or retry. Account creation IS permitted where a site requires one: use email
you@example.com and the password stored in `scripts/secrets.local.json` under
`account_password` (loaded automatically via `daily_log.load_profile()` — every ATS script already
merges secrets.local.json into the profile dict passed to it). Log all actions to
`scripts/daily_log_<today>.txt`.

---

## Your Identity & Rules (memorise these)

All identity values come from `scripts/profile.json` (copy `profile.example.json`
and fill it in). The rules below are the SHAPE of what that file must answer —
the values themselves never live in this spec:

- Name / email / phone / portfolio / LinkedIn — from `profile.json`
- Work authorization and sponsorship answer — from `profile.json`
- **Years-of-experience answers on forms** — from `profile.json`. Decide these
  numbers once, deliberately, and never let the model improvise them per form.
- Salary: midpoint of the posted range, or the `salary_display` default from
  `profile.json` if none is posted
- Start date: 2 weeks from offer
- Geography rules (which country, which cities for on-site, what to skip) —
  from `profile.json`. Always skip: CAPTCHAs, hard requirements you don't meet.

---

## PHASE 1 — DISCOVER NEW JOBS

Run this Python script to get new jobs via Apify:

```bash
cd "$REPO_ROOT"
python scripts/apify_scraper.py --output scripts/daily_report.json
```

Also run the Greenhouse + Lever fallback scraper. This one now also sweeps Wellfound
(step `[4]` in its log) so you normally do not need the standalone command below:

```bash
python scripts/daily_auto_apply.py --dry-run --output scripts/daily_report_fallback.json
```

Wellfound on its own, if you want that source only (no API key, no login, free):

```bash
python scripts/wellfound_scraper.py --output scripts/daily_report_wellfound.json
```

Sources checked on 2026-09-06 and rejected, so nobody re-litigates them:

| Source | Verdict |
|---|---|
| authenticjobs.com | No listings in the page at all (34 links, all site nav), and `/feed` is the **blog**, not jobs. Board looks dormant. |
| designjobsboard.com | Server-rendered and easy to scrape (64 `/job/{id}` links), but it is a **UK board**: London x200, Manchester x4, Canada x0. |
| startup.jobs | Renders 100 job links in a real browser with **no login**, but Cloudflare challenges it intermittently — worked once, blocked ten minutes later. Same fragility as HiringCafe. |
| dribbble.com/browse-project-briefs | Loads in a browser but yields **1** link; briefs are Pro-gated freelance projects, not roles. |
| workatastartup.com | The real YC board. Returns 406 to plain HTTP but renders **30 design jobs in a browser with no login**. Parser not written yet — this is the best unclaimed source of the batch. |

Session state for the gated boards is checked by `scripts/board_sessions.py --check`. Run
`--login` once to sign in inside the automation Chrome profile, which is **separate** from
everyday Chrome: having an account is not the same as the pipeline being able to see it.

More scrapers that exist but are **not** in the daily run, each for a specific reason:

- `scripts/hiringcafe_scraper.py` — HiringCafe sits behind Cloudflare and its fetches proved
  unreliable. Run by hand if you want it.
- `scripts/yc_scraper.py` — works, no login needed, and parses cleanly (company, YC batch,
  salary band, location). But YC startups are overwhelmingly San Francisco / New York: on the
  first real sweep, **0 of 22** design jobs were Canada-eligible. Run it occasionally with
  `--worldwide` to eyeball the remote ones; wiring it into the 8 AM job would burn a browser
  launch every morning to return nothing.
- `scripts/wttj_scraper.py` — Welcome to the Jungle. See the note in that file: anonymous
  visitors get redirected into a signup funnel, so it needs a signed-in browser profile.
- `scripts/idealist_scraper.py` — works, no login, no Cloudflare, and the parser is solid
  (one clean pipe-delimited line per card). The board carries ~1,072 jobs, but it is a US
  nonprofit board: the entry-level Canada sweep returned exactly **1** role (Operations and
  Finance Manager, Human Rights Watch, Toronto, CAD 100-120k). Keep for occasional runs.
- `scripts/weworkremotely_scraper.py` — technically the cleanest source here: RSS, no key, no
  login, no Cloudflare, full JDs and a skills list included. The catch is policy, not
  plumbing: **every** WWR listing is "Anywhere in the World" (16/16 design, 89/91 overall),
  and profile rule 2 says to skip worldwide-remote. Default `canada_only=True` therefore
  returns nothing. Run with `--worldwide` if that rule should bend:
  `python scripts/weworkremotely_scraper.py --feeds design,all --worldwide`

Merge all reports. Deduplicate by URL against `the tracker spreadsheet (see `update_tracker.py`)`. Keep top 20 by score.

Wellfound records carry two extra fields worth using: `description` (the complete JD, so
Phase 2 can be skipped for them) and `ats_source` (ASHBY / GREENHOUSE / LEVER / WORKABLE, or
empty when the job is applied to natively on Wellfound). Roughly half are mirrors of a real
ATS posting. Wellfound listings stay live for months, so they use a 14-day age window instead
of the 3-day one, set by `WELLFOUND_MAX_AGE_DAYS` in `daily_auto_apply.py`.

---

## PHASE 2 — EXTRACT FULL JOB DESCRIPTIONS

For each job in your merged list, run Firecrawl to get the full JD:

```bash
firecrawl scrape "<job_url>" --only-main-content -o ".firecrawl/<slug>.md"
```

**Skip this call for any job that already has a non-empty `description` field** — every
Wellfound record does, and re-scraping it just burns Firecrawl credits on a JD you already
hold. Use `description` directly as the markdown.

Save the markdown. Extract any visible custom screening questions.

---

## PHASE 3 — ANALYSE EACH JOB (Sequential Thinking)

For each job, reason through these steps explicitly before proceeding:

**Step 1:** Hard requirements check — does the role require 5+ years, specific clearance, or on-site outside Ottawa? If yes → skip, log reason.

**Step 2:** Extract top 5 keywords from the JD to embed in the resume summary (e.g., "design systems", "Figma", "cross-functional", "product strategy").

**Step 3:** Choose cover letter angle: agency / fintech / enterprise / ecommerce / general.

**Step 4:** Identify custom questions and draft answers using ONLY real
experience listed in `profile.json` (`experience_notes`). Never invent projects,
employers, or metrics. If the profile has nothing relevant to a question, leave
it for manual review rather than guessing — a flagged application beats a
fabricated one.

**Step 5:** Confirm ATS type from URL pattern.

Output: one JSON object per job with `{keywords, cl_angle, custom_q_answers, ats_type, proceed: true/false, skip_reason}`.

---

## PHASE 4 — PREPARE DOCUMENTS

> **Note for this public repo:** the document-generation scripts referenced in
> this phase (`tailor_resume.py`, `generate_tailored_cl.js`,
> `generate_cold_email.py`) are deliberately not included — they contain the
> author's actual resume and cover-letter content. Bring your own generators
> that write a per-job resume PDF and cover letter into the application folder;
> everything downstream only needs the file paths recorded in
> `phase4_prepared.json`.

For each job where `proceed: true`:

1. **Resume (tailor_resume.py handles docx + PDF conversion automatically):**
   ```bash
   python scripts/tailor_resume.py \
     --company "X" --role "Y" --keywords "kw1,kw2,kw3,kw4,kw5" \
     --output "Applications/[Company] - [Role]/[Company]_Resume.docx"
   ```
   This saves both the .docx AND a .pdf in the same folder.

2. **Cover letter:**
   ```bash
   node scripts/generate_tailored_cl.js \
     --company "X" --role "Y" --desc "<first 400 chars of JD>" \
     --output "Applications/[Company] - [Role]/[Company]_CL.docx"
   ```

3. **Cold email — DRAFT ONLY, never `--send`:**
   ```bash
   python scripts/generate_cold_email.py \
     --company "X" --role "Y" --keywords "kw1,kw2,kw3" \
     --resume "Applications/[Company] - [Role]/[Company]_Resume.pdf" \
     --cover-letter "Applications/[Company] - [Role]/[Company]_CL.docx" \
     --output "Applications/[Company] - [Role]/[Company]_Cold_Email.docx"
   ```
   This phase used to pass `--send` while Phase 7 said drafts-only, and the two
   contradicted each other for weeks. Drafts-only wins: a cold email goes to a named
   human, and an unreviewed one cannot be taken back. the user sends them himself.

4. **Write phase4_prepared.json** with ALL of these fields per job:
   ```json
   {
     "company": "X", "title": "Y", "url": "...",
     "resume_pdf": "Applications/.../[Company]_Resume.pdf",
     "resume_docx": "Applications/.../[Company]_Resume.docx",
     "cover_letter_path": "Applications/.../[Company]_CL.docx",
     "folder": "Applications/[Company] - [Role]",
     "location": "...", "salary": "...",
     "keywords": ["kw1","kw2"], "cl_angle": "fintech",
     "ats_type": "GREENHOUSE", "custom_q_answers": {}
   }
   ```

---

## PHASE 5 — APPLY

Use `resume_pdf` and `cover_letter_path` from phase4_prepared.json in every ATS call.
Use the per-job PDF (not the master resume) — it has the tailored summary.

```bash
# Greenhouse
python scripts/ats/greenhouse.py \
  --url "<url>" \
  --resume "Applications/[Company] - [Role]/[Company]_Resume.pdf" \
  --cover-letter "Applications/[Company] - [Role]/[Company]_CL.docx" \
  --profile scripts/profile.json \
  --answers '<custom_q_answers json>' \
  --company "X" --role "Y"

# Lever (same pattern — --cover-letter flag)
python scripts/ats/lever.py \
  --url "<url>" --resume "<pdf_path>" --cover-letter "<cl_path>" \
  --profile scripts/profile.json --answers '<json>' --company "X" --role "Y"

# LinkedIn Easy Apply
python scripts/ats/linkedin.py \
  --url "<url>" --resume "<pdf_path>" \
  --profile scripts/profile.json --company "X" --role "Y"

# Wellfound (same pattern — --cover-letter is read as the note to the founder)
python scripts/ats/wellfound.py \
  --url "<url>" --resume "<pdf_path>" --cover-letter "<cl_path>" \
  --profile scripts/profile.json --answers '<json>' --company "X" --role "Y"

# Indeed / Workable / Workday / Direct — same pattern, add --cover-letter if script supports it
```

**Wellfound needs a signed-in session** in the persistent Chrome profile at
`~\AppData\Local\JobHunterAutomation\ChromeProfile`. There is no Wellfound account yet
so until an account exists every Wellfound job returns
`login_required` and gets flagged, not submitted. The discovery half of the source works
regardless.

**Handle results — MANDATORY after every job:**
- **On `success: true`:**
  1. Rename folder: `[Company] - [Role]` → `[Company] - [Role] (Applied Jul 3 2026)`
  2. Run: `python scripts/update_tracker.py --company "X" --role "Y" --url "<url>" --status "✅ APPLIED" --date "<today>" --location "<loc>" --mode "<Remote/Hybrid>" --salary "<salary>"`
- **On `"error": "login_required"`:** Log "LOGIN REQUIRED — flagged for the user". Add to errors list.
- **On `"error": "manual_required"`:** Log "MANUAL REVIEW NEEDED". Add to errors list.
- **On `"error": "captcha_detected"`:** Mark folder as `(CAPTCHA Pending)`. Add to CAPTCHA list. Do NOT retry.
- **On `"error": "external_ats"`** (Wellfound only): the posting is a mirror and Apply left the
  site. Re-run this job once against the adapter named in `external_ats`, using `redirect_url`
  as `--url`. Do not count it as applied until that second call returns `success: true`.
- **On `apply_type == "unknown"`:** Skip silently.
- **On any other error:** Log full error, add to errors list, continue to next job.

---

## PHASE 6 — MONITOR EMAIL

**First, check MyGreenhouse.** Email is a guess about what was submitted; the candidate
account is the record. This lists every Greenhouse application with its real `applied_at`,
current stage, and Greenhouse's own duplicate flags, then diffs it against the tracker:

```bash
python scripts/my_greenhouse.py --reconcile --output scripts/my_greenhouse_applications.json
```

Anything under `MISSING` was really submitted but never tracked — add it. Anything under
`DUPLICATE` was submitted twice; stop re-applying to it. If the command exits with
`login_required`, the automation Chrome profile is not signed in: that is a job for the user,
`python scripts/my_greenhouse.py --login`. Do not attempt to sign in on his behalf.

**Gmail is not the only inbox.** If the profile owner also uses a third-party auto-apply
service, replies to its submissions land in that service's proxy mailbox and Gmail never
sees them — interview requests included. `check_all_inboxes()` reads Gmail plus every
IMAP account listed under `imap_mailboxes` in `secrets.local.json`; configure any proxy
mailbox there so Phase 6 is not blind to half the replies.

Then use Gmail MCP to search for job-related emails received in the last 24 hours:

1. Search: `newer_than:1d (interview OR "next steps" OR "move forward" OR schedule OR assessment)`
   → For each match: apply label `Label_16`, update tracker status to `🟢 Interview`, add to responses list

2. Search: `newer_than:1d (unfortunately OR regret OR "not moving forward" OR "other candidates")`  
   → For each match: apply label `Label_19`, update tracker status to `❌ Rejected`, add to responses list

---

## PHASE 7 — SEND DAILY NOTIFICATION EMAIL

This is the **only** email you send automatically to you@example.com. It is a summary of today's pipeline activity.

**Cold emails (Phase 4) are saved as Gmail DRAFTS only** — never auto-sent. the user reviews and sends them manually.

Use Gmail MCP `create_draft` (then immediately send it) to you@example.com:
```bash
python scripts/email_monitor.py --applied '<json>' --captcha '<json>' --responses '<json>' --errors '<json>'
```

Send the email. the user reads this each morning to see: applications sent, CAPTCHAs pending, interview invites, rejections, and errors.

---

## END OF PIPELINE

Log a final summary line to `scripts/daily_log_<today>.txt`:
`PIPELINE COMPLETE — Applied: N | CAPTCHA: N | Interviews: N | Rejections: N | Errors: N`
