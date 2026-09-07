# Kestrel

An autonomous job-application pipeline. It wakes up at 8 AM, finds new design
roles, filters them against a profile, prepares tailored documents, applies
through eight different ATS platforms, reads the replies, and emails a summary
— then documents, honestly, everywhere it breaks.

A kestrel hovers, watches, then drops. The architecture matches: the **scan
engine** (finding and scoring jobs) and the **apply engine** (driving ATS forms)
are deliberately separate.

**[Live demo →](https://sanketp9499.github.io/kestrel/)** — the real Command
Center interface running on fabricated data. Every company on that board is
fictional.

---

## The pipeline

```
08:00  Task Scheduler fires run_daily_job.ps1 (3 attempts, backoff)
   │
   ▼
[1] SOURCE     Wellfound · Indeed CA · LinkedIn · Greenhouse boards · Lever boards
               → dedupe by URL AND by company|role (punctuation-insensitive)
[2] EXTRACT    full job description — skipped when the source already ships one
[3] SCORE      hard-requirement filter · keyword extraction · cover-letter angle
[4] PREPARE    tailored resume + cover letter per job (generators not included — see below)
[5] APPLY      Greenhouse · Lever · Ashby · Workable · Workday · LinkedIn · Indeed · direct
[6] MONITOR    Gmail + any IMAP mailbox (proxy inboxes included) for replies
[7] REPORT     daily summary email: applied / CAPTCHA-blocked / interviews / errors
```

The full agent spec lives in [`scripts/RUN_PIPELINE.md`](scripts/RUN_PIPELINE.md)
— it is written to be executed by an LLM agent (`claude --print`), with every
rule the agent must not improvise on pinned to `profile.json`.

## What's in here

```
scripts/
  RUN_PIPELINE.md            the seven-phase agent spec
  daily_auto_apply.py        source aggregation, scoring, dedup
  wellfound_scraper.py       ┐
  weworkremotely_scraper.py  │
  yc_scraper.py              │  source scrapers — see "Sources that
  idealist_scraper.py        │  didn't make the cut" below
  hiringcafe_scraper.py      │
  wttj_scraper.py            ┘
  board_sessions.py          login-session manager for gated boards
  browser_fetch.py           persistent-profile browser layer (Cloudflare, auth)
  ats/                       eight Playwright ATS adapters + shared base
  qa_bank.py                 pattern-matched answers for screening questions
  email_monitor.py           Gmail + IMAP reply classification
  update_tracker.py          spreadsheet tracker updates
  run_daily_job.ps1          the scheduler entry point
  tests/                     the test suite
  profile.example.json       who is applying — copy to profile.json
  secrets.example.json       API keys and mail credentials — copy to secrets.local.json
docs/                        the live demo (GitHub Pages)
```

## What it deliberately won't do

- **CAPTCHAs.** Detected, flagged, never solved. The application folder is
  marked and a human finishes it.
- **EEO / identity questions.** Left blank on purpose (`qa_bank.py`). Guessing
  on someone's behalf about race, gender, disability, or veteran status is not
  a bot's call to make.
- **Send cold emails.** Drafted only. A cold email goes to a named human and
  cannot be recalled; a human reviews and sends.
- **Invent experience.** The QA answerer only draws on `experience_notes` in
  the profile. No relevant fact → the question is flagged for manual review,
  not answered.

## Sources that didn't make the cut

Most "add more job boards" work ends in deletion. Measurements from real runs,
kept so the same dead ends don't get re-explored:

| Source | Verdict |
|---|---|
| **Wellfound** | ✅ In the daily run. Free, no login, full JDs embedded in `__NEXT_DATA__` so the extract phase is skipped entirely. 14-day window (startups leave posts up for months). |
| We Work Remotely | Cleanest source technically (RSS, no auth) — but **every** listing is "Anywhere in the World" (16/16 design, 89/91 overall), which a country-restricted profile rejects wholesale. `--worldwide` flag if your rules differ. |
| Y Combinator | Parses beautifully (company, batch, salary band). **0 of 22** design roles were Canada-eligible. Also: in YC location strings, **"CA" means California** — a naive Canada filter becomes a California filter. |
| Idealist | Solid parser, ~1,072 jobs on the board, exactly **1** Canadian entry-level hit. US nonprofit board. |
| HiringCafe | Richest records of any source (real ATS apply URL, structured salary, min-YOE field) — behind Cloudflare, which passes one request and challenges the next. Too flaky to schedule. |
| Welcome to the Jungle | Anonymous visitors get a signup funnel, not results. Needs a signed-in browser profile. |
| startup.jobs | 100 job links in a real browser, no login — but Cloudflare challenges intermittently. Same fragility as HiringCafe. |
| workatastartup.com | Returns 406 to plain HTTP, renders 30 design jobs in a browser. Best unclaimed source; parser not yet written. |
| authenticjobs.com | The `/feed` is the blog, not jobs. Board appears dormant. |
| designjobsboard.com | Easy scrape, wrong country: London ×200, Canada ×0. |

## Hard-won details

- **The pipeline drives its own Chrome profile.** Being signed in to a job
  board in your everyday browser does nothing for the bot — sessions live in a
  separate persistent profile (`board_sessions.py --login` to set them up once).
- **Success detection is conservative.** "Thank you" appears on plenty of
  unsubmitted pages; only post-submit confirmation phrases count. False
  "applied" records are worse than false "failed" ones.
- **Dedup needs two keys.** The same job resurfaces under different URLs, and
  the same title arrives as "UIUX", "UI-UX", and "UI/UX". Dedup by URL alone
  and you will apply twice.
- **Replies don't all land in your inbox.** Third-party auto-apply services
  answer from proxy mailboxes; the monitor reads any IMAP account you list, so
  interview requests can't expire unseen.
- **PowerShell 5.1 reads BOM-less UTF-8 as ANSI** — an em dash inside a string
  literal decodes into a smart quote and silently terminates the string. The
  scheduler script keeps its literals ASCII.

## What's not included

The document generators (`tailor_resume.py`, cover-letter and cold-email
builders) contain the author's actual resume content and are private. Bring
your own — downstream phases only need the file paths they write.

## Run it

```
pip install playwright openpyxl apify-client
playwright install chrome
cp scripts/profile.example.json  scripts/profile.json     # fill in
cp scripts/secrets.example.json  scripts/secrets.local.json
python scripts/daily_auto_apply.py --dry-run              # scan only, no writes
```

Schedule `scripts/run_daily_job.ps1` (Windows Task Scheduler) for the full
daily loop — it expects the [Claude Code CLI](https://claude.com/claude-code)
on PATH to execute `RUN_PIPELINE.md`.

---

Built by [Sanket Pawar](https://sanketp.webflow.io) as working infrastructure
for a real job search. The search data stays private; the machine is public.
