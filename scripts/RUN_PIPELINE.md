# DAILY JOB HUNT PIPELINE — Sanket Pawar
**Run this file:** `claudecode --print Scripts/RUN_PIPELINE.md`
**Profile:** `Scripts/sanket_profile.json`
**Workspace:** `E:\Job Hunter 2026\Job Hunter\`

## SAFE MODE — check this first, every run

Run `python Scripts/safe_mode.py --status` before Phase 5.

While safe mode is on, Sanket is reviewing the tailored documents before
anything reaches an employer. **Two actions are held: submitting application
forms, and sending any outbound email** (cold emails and the daily summary).

Everything else runs normally — discovery, JD scraping, scoring, and writing
the tailored resume, cover letter and cold email into each application folder.
That is the point: he wants to read those documents.

The hold is enforced in code, at the submit click in `ats/base.py` and at the
SMTP call sites, so it applies no matter which script runs. Do not route around
it — do not call SMTP directly, do not use an MCP mail tool, and do not click
submit through a browser tool. A held application is reported as
`held_safe_mode`; it is **not** a failure and **not** an application, and it is
deliberately kept out of `apply_ledger.json` so the real submission can still
happen later.

Report at the end of the run how many applications were prepared and held, and
where their documents are. Only Sanket turns this off, with
`python Scripts/safe_mode.py --off`.

---

You are Sanket's fully autonomous job application agent. Execute every phase below in order.
Never stop to ask for approval. Never solve CAPTCHAs — if a form is CAPTCHA-gated (including a
form that appears stuck/non-advancing with a reCAPTCHA frame present), flag it and move on, do
not loop or retry. Account creation IS permitted where a site requires one: use email
sanketp9499@gmail.com and the password stored in `Scripts/secrets.local.json` under
`account_password` (loaded automatically via `daily_log.load_profile()` — every ATS script already
merges secrets.local.json into the profile dict passed to it). Log all actions to
`Scripts/daily_log_<today>.txt`.

---

## Your Identity & Rules (memorise these)

- Name: Sanket Pawar | Email: sanketp9499@gmail.com | Phone: +1 (365) 378-9855
- Portfolio: sanketpawar.com | LinkedIn: linkedin.com/in/-sanket-pawar
- Work auth: Open Work Permit, Canada, no sponsorship needed
- **Years of experience on forms: 1–2 (NEVER 6). Exception: Graphic Design/Adobe = 5, Figma = 2–3**
- Salary: midpoint of posted range, or $65,000 CAD if none posted
- Start date: 2 weeks from offer
- Current role on forms: Product Designer at Synkora
- Resume PDF: `Resumes/Sanket_Pawar_Resume_UX_Designer.pdf`
- Canada only. Skip: on-site outside Ottawa, US-only, worldwide-only, CAPTCHAs, 5+ yr hard requirements

---

## PHASE 1 — DISCOVER NEW JOBS

Run this Python script to get new jobs via Apify:

```bash
cd "E:\Job Hunter 2026\Job Hunter"
python Scripts/apify_scraper.py --output Scripts/daily_report.json
```

Also run the Greenhouse + Lever fallback scraper. This one now also sweeps Wellfound
(step `[4]` in its log) so you normally do not need the standalone command below:

```bash
python Scripts/daily_auto_apply.py --dry-run --output Scripts/daily_report_fallback.json
```

Wellfound on its own, if you want that source only (no API key, no login, free):

```bash
python Scripts/wellfound_scraper.py --output Scripts/daily_report_wellfound.json
```

Sources checked on 2026-09-06 and rejected, so nobody re-litigates them:

| Source | Verdict |
|---|---|
| authenticjobs.com | No listings in the page at all (34 links, all site nav), and `/feed` is the **blog**, not jobs. Board looks dormant. |
| designjobsboard.com | Server-rendered and easy to scrape (64 `/job/{id}` links), but it is a **UK board**: London x200, Manchester x4, Canada x0. |
| startup.jobs | Renders 100 job links in a real browser with **no login**, but Cloudflare challenges it intermittently — worked once, blocked ten minutes later. Same fragility as HiringCafe. |
| dribbble.com/browse-project-briefs | Loads in a browser but yields **1** link; briefs are Pro-gated freelance projects, not roles. |
| workatastartup.com | The real YC board. Returns 406 to plain HTTP but renders **30 design jobs in a browser with no login**. Parser not written yet — this is the best unclaimed source of the batch. |

Session state for the gated boards is checked by `Scripts/board_sessions.py --check`. Run
`--login` once to sign in inside the automation Chrome profile, which is **separate** from
everyday Chrome: having an account is not the same as the pipeline being able to see it.

More scrapers that exist but are **not** in the daily run, each for a specific reason:

- `Scripts/hiringcafe_scraper.py` — HiringCafe sits behind Cloudflare and its fetches proved
  unreliable. Run by hand if you want it.
- `Scripts/yc_scraper.py` — works, no login needed, and parses cleanly (company, YC batch,
  salary band, location). But YC startups are overwhelmingly San Francisco / New York: on the
  first real sweep, **0 of 22** design jobs were Canada-eligible. Run it occasionally with
  `--worldwide` to eyeball the remote ones; wiring it into the 8 AM job would burn a browser
  launch every morning to return nothing.
- `Scripts/wttj_scraper.py` — Welcome to the Jungle. See the note in that file: anonymous
  visitors get redirected into a signup funnel, so it needs a signed-in browser profile.
- `Scripts/idealist_scraper.py` — works, no login, no Cloudflare, and the parser is solid
  (one clean pipe-delimited line per card). The board carries ~1,072 jobs, but it is a US
  nonprofit board: the entry-level Canada sweep returned exactly **1** role (Operations and
  Finance Manager, Human Rights Watch, Toronto, CAD 100-120k). Keep for occasional runs.
- `Scripts/weworkremotely_scraper.py` — technically the cleanest source here: RSS, no key, no
  login, no Cloudflare, full JDs and a skills list included. The catch is policy, not
  plumbing: **every** WWR listing is "Anywhere in the World" (16/16 design, 89/91 overall),
  and profile rule 2 says to skip worldwide-remote. Default `canada_only=True` therefore
  returns nothing. Run with `--worldwide` if that rule should bend:
  `python Scripts/weworkremotely_scraper.py --feeds design,all --worldwide`

Merge all reports. Deduplicate by URL against `Sanket_Job_Tracker_2026.xlsx`. Keep top 20 by score.

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

Save the markdown **into the application folder as `Job_Description.md`** — not only to
the scratch dir. The Command Center's detail drawer reads it from there; before Sep 2026
JDs were discarded after scoring, which is why older applications show no description.

Also record the posting age: every source carries it (`age_str` / `days_old` /
`estimated_publish_date`). Write it as a `| Posted | <date or "N days ago at discovery"> |`
row in the folder's Job_Details.md field table. It is the one field that cannot be
recovered later — a job's posted date disappears from most boards once it closes.

Extract any visible custom screening questions.

---

## PHASE 3 — ANALYSE EACH JOB (Sequential Thinking)

For each job, reason through these steps explicitly before proceeding:

**Step 1:** Hard requirements check — does the role require 5+ years, specific clearance, or on-site outside Ottawa? If yes → skip, log reason.

**Step 2:** Extract top 5 keywords from the JD to embed in the resume summary (e.g., "design systems", "Figma", "cross-functional", "product strategy").

**Step 3:** Choose cover letter angle: agency / fintech / enterprise / ecommerce / general.

**Step 4:** Identify custom questions and draft answers using real experience:
- Centennial College PGD projects (usability testing with 10 participants, website rebuild)
- 7 years freelance visual/branding work
- LandSeed design volunteer (Figma design system maintenance)
- Portfolio projects at sanketpawar.com
- Amazon Fulfillment Associate (current role Sept 2025–present, shows reliability and work ethic)
NEVER mention Synkora as portfolio work — nothing to show. Lead with Mastery Workshops internship, LandSeed, and Freelance. Never mention Ahmedabad University internationally (just say MCA). Never say 6+ years of experience — always say 1–2 years.

**Step 5:** Confirm ATS type from URL pattern.

Output: one JSON object per job with `{keywords, cl_angle, custom_q_answers, ats_type, proceed: true/false, skip_reason}`.

---

## PHASE 4 — PREPARE DOCUMENTS

For each job where `proceed: true`:

1. **Resume (tailor_resume.py handles docx + PDF conversion automatically):**
   ```bash
   python Scripts/tailor_resume.py \
     --company "X" --role "Y" --keywords "kw1,kw2,kw3,kw4,kw5" \
     --output "Applications/[Company] - [Role]/[Company]_Resume_Sanket_Pawar.docx"
   ```
   This saves both the .docx AND a .pdf in the same folder.

2. **Cover letter — pass the FULL JD file, not an excerpt:**
   ```bash
   node Scripts/generate_tailored_cl.js \
     --company "X" --role "Y" \
     --desc-file "Applications/[Company] - [Role]/Job_Description.md" \
     --output "Applications/[Company] - [Role]/[Company]_CL_Sanket_Pawar.docx"
   ```
   This step used to pass `--desc "<first 400 chars>"`. The opening paragraph is
   chosen from evidence in the description, and 400 characters is rarely enough
   to judge from — part of how AltaML, an applied-AI company, received a letter
   opening "Working at a creative agency is exactly the kind of environment I
   thrive in". Fall back to `--desc` only when Phase 2 saved no
   `Job_Description.md`; on thin evidence the generator deliberately says less
   rather than guessing.

3. **Cold email — DRAFT ONLY, never `--send`:**
   ```bash
   python Scripts/generate_cold_email.py \
     --company "X" --role "Y" --keywords "kw1,kw2,kw3" \
     --resume "Applications/[Company] - [Role]/[Company]_Resume_Sanket_Pawar.pdf" \
     --cover-letter "Applications/[Company] - [Role]/[Company]_CL_Sanket_Pawar.docx" \
     --output "Applications/[Company] - [Role]/[Company]_Cold_Email_Sanket_Pawar.docx"
   ```
   This phase used to pass `--send` while Phase 7 said drafts-only, and the two
   contradicted each other for weeks. Drafts-only wins: a cold email goes to a named
   human, and an unreviewed one cannot be taken back. Sanket sends them himself.

4. **Write Job_Details.md — do not hand-roll it.** Call the shared writer,
   once per job, before anything else in this phase:
   ```bash
   python Scripts/job_folder.py \
     --company "[Company]" --role "[Role]" --status "Not Applied" \
     --url "[posting url]" --apply-url "[apply url]" \
     --location "[location]" --pay "[salary or blank]" \
     --posted "[posted date]" --source "[apply_type]" --ats "[ATS]" \
     --cl-angle "[angle]" --keywords "kw1, kw2, kw3"
   ```
   It creates the folder and the file together, and merges rather than
   overwrites, so re-running it is safe and never destroys a field it has no
   value for.

   This step exists because it used to be improvised. Phase 4 listed the resume,
   the cover letter and the cold email but never this file, so whether a job
   ever recorded its own URL depended on what the agent felt like writing that
   morning. **55 of 189 folders ended up with no Job_Details.md**, including six
   of the nine CAPTCHA-blocked applications — the exact rows whose only job is
   to send a human to a posting. The tracker is rebuilt from this file. If it is
   missing, the job's URL is gone.

5. **Verify before leaving the phase.** This must exit 0:
   ```bash
   python Scripts/job_folder.py --check
   ```
   It lists every application folder with no Job_Details.md and exits non-zero
   if there are any. A non-zero exit here is a failed phase, not a warning.

6. **Write phase4_prepared.json** with ALL of these fields per job:
   ```json
   {
     "company": "X", "title": "Y", "url": "...",
     "resume_pdf": "Applications/.../[Company]_Resume_Sanket_Pawar.pdf",
     "resume_docx": "Applications/.../[Company]_Resume_Sanket_Pawar.docx",
     "cover_letter_path": "Applications/.../[Company]_CL_Sanket_Pawar.docx",
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
python Scripts/ats/greenhouse.py \
  --url "<url>" \
  --resume "Applications/[Company] - [Role]/[Company]_Resume_Sanket_Pawar.pdf" \
  --cover-letter "Applications/[Company] - [Role]/[Company]_CL_Sanket_Pawar.docx" \
  --profile Scripts/sanket_profile.json \
  --answers '<custom_q_answers json>' \
  --company "X" --role "Y"

# Lever (same pattern — --cover-letter flag)
python Scripts/ats/lever.py \
  --url "<url>" --resume "<pdf_path>" --cover-letter "<cl_path>" \
  --profile Scripts/sanket_profile.json --answers '<json>' --company "X" --role "Y"

# LinkedIn Easy Apply
python Scripts/ats/linkedin.py \
  --url "<url>" --resume "<pdf_path>" \
  --profile Scripts/sanket_profile.json --company "X" --role "Y"

# Wellfound (same pattern — --cover-letter is read as the note to the founder)
python Scripts/ats/wellfound.py \
  --url "<url>" --resume "<pdf_path>" --cover-letter "<cl_path>" \
  --profile Scripts/sanket_profile.json --answers '<json>' --company "X" --role "Y"

# Indeed / Workable / Workday / Direct — same pattern, add --cover-letter if script supports it
```

**Wellfound needs a signed-in session** in the persistent Chrome profile at
`~\AppData\Local\JobHunterAutomation\ChromeProfile`. There is no Wellfound account yet
(see `ACCOUNTS_TO_CREATE.md`), so until Sanket creates one every Wellfound job returns
`login_required` and gets flagged, not submitted. The discovery half of the source works
regardless.

**Handle results — MANDATORY after every job:**
- **On `success: true`:**
  1. Rename folder: `[Company] - [Role]` → `[Company] - [Role] (Applied Jul 3 2026)`
  2. Run: `python Scripts/update_tracker.py --company "X" --role "Y" --url "<url>" --status "✅ APPLIED" --date "<today>" --location "<loc>" --mode "<Remote/Hybrid>" --salary "<salary>"`
- **On `"error": "login_required"`:** Log "LOGIN REQUIRED — flagged for Sanket". Add to errors list.
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
python Scripts/my_greenhouse.py --reconcile --output Scripts/my_greenhouse_applications.json
```

Anything under `MISSING` was really submitted but never tracked — add it. Anything under
`DUPLICATE` was submitted twice; stop re-applying to it. If the command exits with
`login_required`, the automation Chrome profile is not signed in: that is a job for Sanket,
`python Scripts/my_greenhouse.py --login`. Do not attempt to sign in on his behalf.

**Gmail is not the only inbox.** aiApply applies from a proxy mailbox it issues Sanket,
`sanketp9499@mailboxcore.com`, and every reply to an aiApply submission lands there. That is
where ventureLAB's interview request went (Aug 12) and where a Huzzle video interview expired
unattempted. Read both:

```bash
python Scripts/email_monitor.py --check-mail --days 7
```

That calls `check_all_inboxes()` — Gmail plus every mailbox in `imap_mailboxes` in
`secrets.local.json`. If it reports nothing configured, the credentials still need adding;
they are shown at `aiapply.co/app/inbox` and the host is `imap.migadu.com:993`.

Then use Gmail MCP to search for job-related emails received in the last 24 hours:

1. Search: `newer_than:1d (interview OR "next steps" OR "move forward" OR schedule OR assessment)`
   → For each match: apply label `Label_16`, update tracker status to `🟢 Interview`, add to responses list

2. Search: `newer_than:1d (unfortunately OR regret OR "not moving forward" OR "other candidates")`  
   → For each match: apply label `Label_19`, update tracker status to `❌ Rejected`, add to responses list

---

## PHASE 7 — SEND DAILY NOTIFICATION EMAIL

This is the **only** email you send automatically to sanketp9499@gmail.com. It is a summary of today's pipeline activity.

**Cold emails (Phase 4) are saved as Gmail DRAFTS only** — never auto-sent. Sanket reviews and sends them manually.

Use Gmail MCP `create_draft` (then immediately send it) to sanketp9499@gmail.com:
```bash
python Scripts/email_monitor.py --applied '<json>' --captcha '<json>' --responses '<json>' --errors '<json>'
```

Send the email. Sanket reads this each morning to see: applications sent, CAPTCHAs pending, interview invites, rejections, and errors.

---

## END OF PIPELINE

Log a final summary line to `Scripts/daily_log_<today>.txt`:
`PIPELINE COMPLETE — Applied: N | CAPTCHA: N | Interviews: N | Rejections: N | Errors: N`
