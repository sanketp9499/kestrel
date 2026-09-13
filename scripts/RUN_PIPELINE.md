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

**Run the ATS board sweep FIRST. It is the primary source.**

```bash
cd "E:\Job Hunter 2026\Job Hunter"
python Scripts/board_sweep.py --json > Scripts/daily_report_boards.json
```

It reads the Greenhouse, Lever, Ashby and Workable boards that `ats_resolver.py`
has already mapped: **64 boards, 3,450 open postings**, over plain HTTP. No API
key, no quota, no browser, no CAPTCHA, and every one of them is a board the
adapters can actually submit to. Verified 2026-09-13: 3,450 scanned, 51 kept,
0 boards unreachable.

Grow the board list as companies appear, so the primary source keeps widening:

```bash
python Scripts/ats_resolver.py --backfill --limit 25   # map new companies to boards
python Scripts/ats_resolver.py --report                # cache size and coverage
```

Then Apify, as a **secondary** source for LinkedIn and Indeed:

```bash
python Scripts/apify_scraper.py --output Scripts/daily_report.json
```

Apify is a FREE plan with $5 of monthly credit and a hard stop when it runs out.
It exhausted the September allowance on 2026-09-12; the cycle resets on the 28th
(signup day of month). While it is out, `apify_scraper` returns an empty list and
logs `APIFY UNAVAILABLE`. **That line means the run is degraded, not that the
market is quiet — log it as an error and say so in the phase 1 summary.** Do not
treat a small pool as a normal day when that line is present.

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

**Then drop the postings that are already gone, before anything is spent on them:**

```python
from link_check import filter_alive
jobs, dead = filter_alive(jobs)      # dead rows carry dead_reason
```

A dead posting otherwise costs a Firecrawl extraction, two Claude document calls,
a folder and a tracker row before phase 5 finds out. `ats_resolver.py` measured
it: 11 of 13 Lever slugs and 10 of 17 Greenhouse slugs were 404.

Only 404 and 410 are dropped. 403, 429 and timeouts are **kept** - a bot filter
is not evidence a job is gone, and dropping those would silently delete real
postings. A 200 whose body says "no longer accepting applications" is dropped.
Log every drop with its `dead_reason`.

Known limit: LinkedIn renders that message in JS, so an expired LinkedIn posting
still returns a clean 200 here. The check is strongest on real ATS boards.

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

**Step 1:** Hard requirements check — clearance, citizenship, or on-site outside the GTA? If yes → skip, log reason.

For years of experience, **do not judge by the title and do not skip on 5+ alone.**
Sanket's rule: he is not hunting senior roles, but if he is eligible then why
not, and he wants every design discipline in the net — brand, creative, graphic,
learning design included. A title is a bad proxy anyway: "Senior Product
Designer" at a startup can ask for 3 years while "Product Designer" at a bank
asks for 8.

Read the number the posting actually states:

```python
from experience_gate import assess
band = assess(jd_text)     # {"years", "band", "keep", "reason"}
```

- `match` — at or near his ~2 years. Proceed.
- `stretch` — asks more than he has and is still worth applying to. **Proceed**,
  and put the band in the log so the report can rank it.
- `out of band` — 9+ years. The only case that skips, with `reason` as the
  `skip_reason`.
- `unstated` — most good postings never name a number. Proceed.

On 2026-09-12 this step skipped 11 of 13 jobs on "5+ years" and the day ended
with two applications. Those were stretch applications being thrown away.

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

   **Then score it against the posting before moving on:**
   ```bash
   python Scripts/ats_match.py \
     --jd-file "Applications/[Company] - [Role]/Job_Description.md" \
     --resume  "Applications/[Company] - [Role]/[Company]_Resume_Sanket_Pawar.docx" \
     --company "X"
   ```
   Exits 0 at or above 0.70 coverage, 1 below, and prints `missing` either way.

   Every ATS on the receiving end runs this comparison before a human sees the
   file, and nothing here ran it before. Scored against the 12 real application
   folders on disk, the median was **0.68** and 7 of 12 were below the gate,
   missing things the postings explicitly asked for: style guide, Photoshop,
   Illustrator, Sketch, InVision, motion design, component library, Agile.

   Below the gate: re-run `tailor_resume.py` with the missing terms added to
   `--keywords`, then score again. **Only add terms that are true.** The missing
   list says what the posting asked for, not what Sanket has done. If a missing
   keyword is a skill he does not have, leave it missing, log it, and move on -
   a resume that passes the gate by lying fails the interview instead.

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
     "apply_url": "...",
     "resume_pdf": "Applications/.../[Company]_Resume_Sanket_Pawar.pdf",
     "resume_docx": "Applications/.../[Company]_Resume_Sanket_Pawar.docx",
     "cover_letter_path": "Applications/.../[Company]_CL_Sanket_Pawar.docx",
     "folder": "Applications/[Company] - [Role]",
     "location": "...", "salary": "...",
     "keywords": ["kw1","kw2"], "cl_angle": "fintech",
     "ats_type": "GREENHOUSE", "custom_q_answers": {}
   }
   ```

   `url` is the posting. `apply_url` is the page the adapter is driven against,
   and the two differ whenever Apply leaves the listing site - a LinkedIn or
   Wellfound post whose form is hosted on Greenhouse. **Set `apply_url` to the
   posting URL when they are the same; never leave it blank.** On 2026-09-12
   all 18 phase 3 records and both prepared records had `"apply_url": ""`,
   which only escaped notice because that day's phase 5 script read `url`.

   Validate before phase 5 starts, and let it raise - it names every bad record
   at once:
   ```python
   from job_record import load_prepared, apply_url_for
   jobs = load_prepared()          # validates, and fills apply_url from url
   ```
   Use `apply_url_for(job)` for the adapter's `--url`.

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

**Reading an adapter's result — do NOT write your own parser:**

```python
from ats.base import parse_result
p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=900)
res = parse_result(p.stdout, p.stderr)
```

Every adapter ends with `emit_result()`, which prints the verdict twice: indented
for the log, then a single `KESTREL_RESULT {...}` line for this parser.
`parse_result` never raises.

Two rules this exists to enforce:

1. **Never hand-roll the parse.** On 2026-09-12 this phase's script accepted a
   result only if one line both started with `{` and ended with `}`. Adapters
   pretty-print, so that matched nothing — both verdicts that day were thrown
   away as `no_json_result` despite the adapters working correctly.
2. **Never re-run an adapter to recover a verdict.** That is what happened next
   on 2026-09-12, and Wellfound uploaded the resume a second time. With safe
   mode off it would have been a second submission. If `parse_result` returns
   `error: "no_adapter_result"`, record the job as failed, log the `raw` field,
   and move to the next job. The only sanctioned second call is the bounded
   `external_ats` redirect below.

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

Run it. These four flags now exist, take JSON lists, and the command builds the
report and sends it through the same guarded path as everything else:

```bash
python Scripts/email_monitor.py --applied '<json>' --captcha '<json>' --responses '<json>' --errors '<json>'
```

Add `--dry-run` to print the report without sending. Unknown flags are an error
rather than being ignored, so if this command ever fails, the mismatch is real
and belongs in the log - do not silently substitute a different call. Until
2026-09-12 these flags were documented but undefined, `parse_known_args()` threw
them away, and the command printed a fake sample report for a Shopify
application nobody made.

If Gmail OAuth is unavailable the send returns False and nothing is sent; in
that case fall back to Gmail MCP `create_draft` (then send it) to
sanketp9499@gmail.com, and log that you did.

Sanket reads this each morning to see: applications sent, CAPTCHAs pending,
interview invites, rejections, and errors.

---

## END OF PIPELINE

Log a final summary line to `Scripts/daily_log_<today>.txt`:
`PIPELINE COMPLETE — Applied: N | CAPTCHA: N | Interviews: N | Rejections: N | Errors: N`
