#!/usr/bin/env python3
"""
Daily Job Application Automation — the user
================================================
Run every morning. Scrapes new Canada UX/Product Designer jobs,
compares against tracker to find only NEW jobs, and outputs a
JSON report for Claude to act on (apply, generate docs, update tracker).

Usage:
    python3 daily_auto_apply.py
    python3 daily_auto_apply.py --dry-run    # find jobs but don't update tracker
"""

import json, os, sys, datetime, re, urllib.request, urllib.parse, time, html
from openpyxl import load_workbook

# ── Paths ──────────────────────────────────────────────────────────────────
# Workspace = the repo root (parent of scripts/). Everything is relative to it,
# so the pipeline runs from wherever the repo is cloned.
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE   = os.path.dirname(SCRIPTS_DIR)
TRACKER     = os.path.join(WORKSPACE, "Job_Tracker.xlsx")
APPS_DIR    = os.path.join(WORKSPACE, "Applications")
REPORT_OUT  = os.path.join(SCRIPTS_DIR, "daily_report.json")
LOG_FILE    = os.path.join(SCRIPTS_DIR, "apply_log.txt")

# ── Search Config ──────────────────────────────────────────────────────────
SEARCH_TERMS = [
    "ux designer",
    "product designer",
    "ui ux designer",
    "ux ui designer",
    "learning experience designer",
    "digital designer",
    "interaction designer",
    "web designer",
]
MAX_AGE_DAYS   = 3    # Only jobs posted within 3 days
# Sources whose listings stay live far longer than a job-board posting, where a
# 3-day window would throw away almost everything they return.
SOURCE_MAX_AGE_DAYS = {
    "wellfound":  14,   # startups leave roles live for months
}
WELLFOUND_MAX_AGE_DAYS = SOURCE_MAX_AGE_DAYS["wellfound"]   # kept for callers
MAX_PER_TERM   = 15   # Max results per search term
SALARY_MIN     = 45000

# Roles to skip (not a good fit)
SKIP_PATTERNS  = [
    r'\bsenior\b.*\b(10|8|7)\+?\s*years?\b',
    r'game\s+(artist|designer)',
    r'fashion\s+designer',
    r'interior\s+designer',
    r'industrial\s+designer',
    r'director\s+of\s+design',
    r'head\s+of\s+(ux|design)',
    r'\bprint\s+only\b',
]

# Keywords that increase relevance score
HIGH_VALUE     = ["figma","ux","user experience","product design","ui/ux","wireframe",
                  "prototype","user research","design system","interaction design"]
BONUS_KEYWORDS = ["remote","canada","ottawa","ontario","hybrid","entry","junior",
                  "intermediate","associate","generalist"]


# ── Helpers ────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def http_get(url, headers=None, timeout=15):
    req = urllib.request.Request(url, headers=headers or {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-CA,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None

def strip_html(text):
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()

def days_ago(date_str):
    """Parse 'X days ago' or ISO date string → int days"""
    if not date_str:
        return 99
    m = re.search(r'(\d+)\s+day', date_str, re.I)
    if m: return int(m.group(1))
    m = re.search(r'(\d+)\s+hour', date_str, re.I)
    if m: return 0
    m = re.search(r'just\s+posted|today', date_str, re.I)
    if m: return 0
    m = re.search(r'(\d+)\s+week', date_str, re.I)
    if m: return int(m.group(1)) * 7
    try:
        d = datetime.datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return (datetime.datetime.now() - d).days
    except:
        return 99

def relevance_score(title, desc):
    text = (title + " " + desc).lower()
    score = 0
    for kw in HIGH_VALUE:
        if kw in text: score += 2
    for kw in BONUS_KEYWORDS:
        if kw in text: score += 1
    return score

CA_TOKENS = ["canada","canadian","ontario","british columbia","alberta","quebec",
             "québec","nova scotia","new brunswick","manitoba","saskatchewan",
             "newfoundland","prince edward island","yukon","nunavut",
             "northwest territories","toronto","ottawa","gatineau","vancouver","calgary",
             "montreal","montréal","edmonton","winnipeg","halifax","mississauga",
             "brampton","hamilton, on","kitchener","waterloo","burnaby","markham",
             "victoria, bc","quebec city"]

CA_ABBR_RE = re.compile(r"\b(on|bc|ab|qc|ns|nb|mb|sk|pe|pei|nl|yt|nt|nu)\b")

US_TOKENS = ["united states","u.s.","usa","new york","nyc","san francisco","seattle",
             "chicago","boston","austin","los angeles","denver","atlanta","miami",
             "dallas","houston","philadelphia","phoenix","portland, or","san diego",
             "washington, dc","california","texas","florida","massachusetts","illinois",
             "colorado","georgia","new jersey","virginia"]

US_RE = re.compile(r"\b(us|u\.s\.?)[ -]?(remote|only|based)\b|\bremote[ -]?(us|u\.s\.?)\b"
                   r"|\bus[ -]?(citizen|work authorization)\b")

REMOTE_RE = re.compile(r"\b(remote|hybrid|anywhere|work from home|wfh|télétravail)\b")


def is_canada(location):
    """True only when the posting is plausibly open to a Canadian applicant.

    Canada named anywhere wins outright (e.g. "US Remote, Toronto"). Otherwise an
    explicit US marker disqualifies it. A bare "remote" with no country named is
    treated as eligible and left for the JD check in Phase 3.
    """
    if not location: return False
    loc = location.lower()

    if any(t in loc for t in CA_TOKENS): return True
    if CA_ABBR_RE.search(loc):           return True

    if US_RE.search(loc):                        return False
    if any(t in loc for t in US_TOKENS):         return False

    return bool(REMOTE_RE.search(loc))

def is_skip(title, desc):
    text = (title + " " + desc).lower()
    for pat in SKIP_PATTERNS:
        if re.search(pat, text, re.I): return True
    return False

def determine_apply_type(url, desc):
    """Categorize how to apply"""
    if not url: return "MANUAL"
    u = url.lower()
    d = (desc or "").lower()
    if "greenhouse.io" in u or "boards.greenhouse" in u: return "GREENHOUSE"
    if "lever.co" in u or "jobs.lever" in u:             return "LEVER"
    if "workable.com" in u:                              return "WORKABLE"
    if "gem.com" in u or "jobs.gem" in u:                return "GEM"
    if "applytojobs.ca" in u:                            return "APPLYTOJOBS"
    if "jobbank.gc.ca" in u:                             return "JOBBANK"
    if "wellfound.com" in u or "angel.co" in u:          return "WELLFOUND"
    if "linkedin.com" in u:                              return "LINKEDIN"
    if "indeed.com" in u:
        if "apply on company site" in d or "apply on company" in d:
            return "JOBBANK_REDIRECT"
        return "INDEED"
    if "myworkdayjobs" in u:                             return "WORKDAY"
    if "taleo" in u:                                     return "TALEO"
    if "icims" in u:                                     return "ICIMS"
    if "bamboohr" in u:                                  return "BAMBOOHR"
    # Check for email in description
    email_m = re.search(r'[\w.+-]+@[\w-]+\.[a-z]{2,}', d)
    if email_m and "apply" in d:                         return f"EMAIL:{email_m.group()}"
    return "DIRECT"


# ── Job Sources ────────────────────────────────────────────────────────────
def search_indeed_ca(term, max_results=MAX_PER_TERM):
    """Scrape Indeed Canada using the public Jobs API (more reliable than HTML parsing)."""
    jobs = []
    q = urllib.parse.quote_plus(term)
    # Indeed's internal API endpoint — returns JSON directly
    api_url = (
        f"https://ca.indeed.com/jobs?q={q}&l=Canada&fromage=3&sort=date&limit=25"
        f"&format=json"
    )
    # Try JSON API first
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "en-CA,en;q=0.9",
        "Referer": "https://ca.indeed.com/",
    }
    html_text = http_get(api_url, headers=headers)
    if not html_text:
        return jobs

    # Extract embedded JSON blob (Indeed still embeds it in the page)
    for pattern in [
        r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});\s*window',
        r'"jobResults"\s*:\s*(\[.*?\])\s*[,}]',
        r'_initialData\s*=\s*(\{.*?"jobs".*?\})\s*;',
    ]:
        m = re.search(pattern, html_text, re.DOTALL)
        if m:
            try:
                raw = m.group(1)
                data = json.loads(raw)
                # Handle both dict-wrapped and bare list forms
                if isinstance(data, list):
                    results = data
                else:
                    results = (data.get("metaData", {})
                                   .get("mosaicProviderJobCardsModel", {})
                                   .get("results", []))
                for r in results[:max_results]:
                    job_key = r.get("jobkey", "") or r.get("id", "")
                    title   = r.get("displayTitle", r.get("title", ""))
                    company = r.get("company", "")
                    loc     = r.get("formattedLocation", r.get("jobLocationCity", ""))
                    salary  = r.get("extractedSalary", {}) or {}
                    sal_str = ""
                    if salary:
                        mn  = salary.get("min", 0)
                        mx  = salary.get("max", 0)
                        per = salary.get("type", "year")
                        if mn or mx:
                            sal_str = f"${mn:,}–${mx:,}/{per}"
                    snippet = strip_html(r.get("snippet", "") or r.get("jobSnippet", ""))
                    age_str = r.get("pubDate", "") or r.get("formattedRelativeTime", "")
                    apply_url = (r.get("thirdPartyApplyUrl")
                                 or f"https://ca.indeed.com/viewjob?jk={job_key}")
                    if not job_key or not title:
                        continue
                    jobs.append({
                        "title": title, "company": company, "location": loc,
                        "salary": sal_str, "snippet": snippet, "url": apply_url,
                        "age_str": age_str, "source": "indeed-ca",
                        "job_key": job_key, "apply_type": "",
                    })
                if jobs:
                    break
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

    # Hard fallback: parse visible HTML job cards
    if not jobs:
        selectors = [
            (r'data-testid="jobTitle"[^>]*><span[^>]*>([^<]+)<', "title"),
        ]
        job_blocks = re.findall(
            r'<div[^>]+data-jk="([a-f0-9]+)"[^>]*>(.*?)</li>',
            html_text, re.DOTALL
        )
        for jk, block in job_blocks[:max_results]:
            title_m   = re.search(r'data-testid="jobTitle"[^>]*>.*?<span[^>]*>([^<]+)<', block)
            company_m = re.search(r'data-testid="company-name"[^>]*>([^<]+)<', block)
            loc_m     = re.search(r'data-testid="text-location"[^>]*>([^<]+)<', block)
            if not title_m:
                continue
            jobs.append({
                "title":   strip_html(title_m.group(1)),
                "company": strip_html(company_m.group(1)) if company_m else "",
                "location":strip_html(loc_m.group(1))    if loc_m    else "",
                "salary": "", "snippet": "", "age_str": "",
                "url": f"https://ca.indeed.com/viewjob?jk={jk}",
                "source": "indeed-ca-html", "job_key": jk, "apply_type": "",
            })
    return jobs


def search_greenhouse_boards(term):
    """Search known Greenhouse job boards for UX/design roles in Canada"""
    jobs = []
    boards = [
        "shopify", "stripe", "notion", "figma", "webflow", "atlassian",
        "squarespace", "duolingo", "wayfair", "hootsuite", "freshbooks",
        "wealthsimple", "kinaxis", "corel", "d2l", "ptc", "introhive"
    ]
    for board in boards:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
        resp = http_get(url, timeout=8)
        if not resp: continue
        try:
            data = json.loads(resp)
            for job in data.get("jobs", []):
                title = job.get("title","")
                loc   = job.get("location",{}).get("name","")
                jurl  = job.get("absolute_url","")
                upd   = job.get("updated_at","")
                if not is_canada(loc): continue
                if not any(kw.lower() in title.lower() for kw in ["ux","design","product","ui","experience"]): continue
                jobs.append({
                    "title": title, "company": board.capitalize(),
                    "location": loc, "salary": "",
                    "snippet": strip_html(job.get("content","")[:300]),
                    "url": jurl, "age_str": upd,
                    "source": "greenhouse", "job_key": str(job.get("id","")),
                    "apply_type": "GREENHOUSE"
                })
        except:
            pass
        time.sleep(0.3)
    return jobs


def search_lever_boards(term):
    """Search Lever job postings"""
    jobs = []
    companies = ["shopify","unbounce","hootsuite","freshbooks","clio","wealthsimple",
                 "introhive","d2l","clearco","benevity","ssense","dialogue","snapcommerce"]
    for co in companies:
        url = f"https://api.lever.co/v0/postings/{co}?mode=json&state=published"
        resp = http_get(url, timeout=8)
        if not resp: continue
        try:
            postings = json.loads(resp)
            for p in postings:
                title = p.get("text","")
                cats  = p.get("categories",{})
                loc   = cats.get("location","") or cats.get("allLocations",[""])[0]
                dept  = cats.get("department","")
                purl  = p.get("hostedUrl","")
                ctime = p.get("createdAt",0)
                if not is_canada(loc): continue
                if not any(kw.lower() in (title+dept).lower() for kw in ["ux","design","product","ui","experience"]): continue
                age_days = (time.time() - ctime/1000) / 86400 if ctime else 99
                if age_days > 14: continue
                jobs.append({
                    "title": title, "company": co.capitalize(),
                    "location": loc, "salary": "",
                    "snippet": p.get("descriptionPlain","")[:300],
                    "url": purl, "age_str": f"{int(age_days)} days ago",
                    "source": "lever", "job_key": p.get("id",""),
                    "apply_type": "LEVER"
                })
        except:
            pass
        time.sleep(0.3)
    return jobs


# ── Tracker helpers ────────────────────────────────────────────────────────
def normalize_job_url(url: str) -> str:
    """Collapse a posting URL to a stable identity.

    LinkedIn re-issues every search with fresh ?position/refId/trackingId query
    params, so the raw string never matches between runs. Reduce LinkedIn URLs
    to their numeric job id and strip the query string everywhere else.
    """
    u = (url or "").strip().lower().rstrip("/")
    if not u:
        return ""
    m = re.search(r"linkedin\.com/jobs/view/(?:[^/?]*-)?(\d{6,})", u)
    if m:
        return f"linkedin:{m.group(1)}"
    m = re.search(r"currentjobid=(\d+)", u)
    if m:
        return f"linkedin:{m.group(1)}"
    return u.split("?")[0].split("#")[0]


def company_role_key(company: str, role: str) -> str:
    """Identity for a posting when the URL is missing or has been re-issued.

    Separators are dropped entirely rather than collapsed to spaces, so the
    punctuation a job title happens to use stops mattering: "UIUX Designer",
    "UI-UX Designer" and "UI/UX Designer" all reduce to the same key. They did
    not before, which is how one Fulfillment IQ posting got two folders.
    """
    norm = lambda s: re.sub(r"[^a-z0-9]+", "", (s or "").lower())
    return f"{norm(company)}|{norm(role)}"


def get_existing_entries():
    """Return (seen_urls, seen_company_role_keys) already in the tracker.

    Columns are resolved by header name — the sheet has been re-ordered before
    and a hardcoded index silently matched the wrong column, which let already
    tracked jobs through and caused duplicate applications.
    """
    urls = set()
    keys = set()
    try:
        wb = load_workbook(TRACKER)
        ws = wb.active
        header = [str(c.value or "").strip().lower() for c in ws[1]]

        def col(*names):
            for n in names:
                if n in header:
                    return header.index(n)
            return None

        i_url = col("url", "applyurl", "apply url", "link")
        i_comp = col("company", "employer")
        i_role = col("role", "title", "position")

        for row in ws.iter_rows(min_row=2, values_only=True):
            if i_url is not None and len(row) > i_url and row[i_url]:
                nu = normalize_job_url(str(row[i_url]))
                if nu:
                    urls.add(nu)
            if i_comp is not None and len(row) > i_comp and row[i_comp]:
                company = str(row[i_comp])
                keys.add(company.strip().lower())
                role = ""
                if i_role is not None and len(row) > i_role and row[i_role]:
                    role = str(row[i_role])
                if role:
                    keys.add(company_role_key(company, role))
    except Exception as e:
        log(f"Warning: could not read tracker — {e}")
    return urls, keys


def is_remote_or_ottawa(location: str, snippet: str) -> bool:
    """Return True only if the job is remote/hybrid Canada-wide OR on-site in Ottawa.
    Rejects on-site roles in Toronto, Vancouver, Montreal, etc.
    """
    combined = (location + " " + snippet).lower()
    # Explicit remote or hybrid signals — allow from anywhere in Canada
    if re.search(r'\b(remote|hybrid|work from home|wfh|télétravail)\b', combined):
        return True
    # Ottawa on-site is fine
    if "ottawa" in combined or "gatineau" in combined:
        return True
    # No remote signal and not Ottawa → skip
    return False


def score_and_filter(jobs, existing_urls, existing_companies=None):
    """Score jobs, remove duplicates, sort by relevance.

    *existing_companies* holds company|role keys already in the tracker.
    get_existing_entries() has always returned it, but main() dropped it on the
    floor and only the URL check ran — so the same job re-sourced under a
    different URL sailed through. That is how "Fulfillment IQ - UIUX Designer"
    (Aug 23) and "Fulfillment IQ - UI-UX Designer" (Aug 31) both got a full set
    of tailored documents generated for one posting.
    """
    existing_companies = existing_companies or set()
    seen_keys = set()
    seen_roles = set()
    results   = []
    for j in jobs:
        url = (j.get("url") or "").lower().strip()
        jk  = j.get("job_key","")
        role_key = company_role_key(j.get("company",""), j.get("title",""))
        if url in existing_urls:    continue  # already in tracker
        if jk  in seen_keys:        continue  # duplicate in this batch
        if role_key in existing_companies:
            continue                          # same company+role already tracked
        if role_key in seen_roles:
            continue                          # same company+role twice in this batch
        if not is_canada(j.get("location","")):
            continue
        # Only Ottawa on-site or remote/hybrid — skip Toronto/Vancouver/etc on-site
        if not is_remote_or_ottawa(j.get("location",""), j.get("snippet","")):
            continue
        if is_skip(j.get("title",""), j.get("snippet","")):
            continue
        j["score"] = relevance_score(j.get("title",""), j.get("snippet",""))
        j["days_old"] = days_ago(j.get("age_str",""))
        max_age = SOURCE_MAX_AGE_DAYS.get(j["source"], MAX_AGE_DAYS)
        if j["days_old"] > max_age and j["source"] not in ["greenhouse","lever"]:
            continue
        if not j.get("apply_type"):
            j["apply_type"] = determine_apply_type(j.get("url",""), j.get("snippet",""))
        seen_keys.add(jk)
        seen_roles.add(role_key)
        results.append(j)

    results.sort(key=lambda x: (-x["score"], x["days_old"]))

    # Tag anything at a company aiApply already applied to. Flag, not filter —
    # an interviewing company came from aiApply and turned into an interview, so a second
    # tailored application is sometimes right. Phase 3 decides; this just makes
    # sure the overlap is visible instead of invisible.
    try:
        from aiapply_overlap import mark_overlap
        overlaps = mark_overlap(results)
        if overlaps:
            log(f"    {overlaps} job(s) at companies aiApply already applied to (flagged, not skipped)")
    except Exception as e:
        log(f"    aiApply overlap check skipped: {e}")

    return results


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    dry_run = "--dry-run" in sys.argv
    today   = datetime.date.today().isoformat()

    log(f"\n{'='*60}")
    log(f"DAILY JOB SEARCH — {today}")
    log(f"{'='*60}")

    # Get existing tracker entries to skip duplicates
    existing_urls, existing_companies = get_existing_entries()
    log(f"Tracker has {len(existing_urls)} existing job URLs")

    # ── Scrape all sources ────────────────────────────────────────────────
    all_jobs = []
    log("\n[1] Searching Indeed CA...")
    for term in SEARCH_TERMS:
        batch = search_indeed_ca(term, MAX_PER_TERM)
        log(f"    '{term}' → {len(batch)} results")
        all_jobs.extend(batch)
        time.sleep(1.0)

    log("\n[2] Checking Greenhouse boards...")
    gh_jobs = search_greenhouse_boards("")
    log(f"    Found {len(gh_jobs)} Greenhouse postings")
    all_jobs.extend(gh_jobs)

    log("\n[3] Checking Lever boards...")
    lv_jobs = search_lever_boards("")
    log(f"    Found {len(lv_jobs)} Lever postings")
    all_jobs.extend(lv_jobs)

    # ── Filter and score ──────────────────────────────────────────────────
    log("\n[4] Checking Wellfound...")
    try:
        from wellfound_scraper import search_wellfound
        wf_jobs = search_wellfound()
        log(f"    Found {len(wf_jobs)} Wellfound postings")
        all_jobs.extend(wf_jobs)
    except Exception as e:
        log(f"    Wellfound source failed (non-fatal): {e}")

    log("\n[5] Filtering and scoring...")
    new_jobs = score_and_filter(all_jobs, existing_urls, existing_companies)
    log(f"    {len(new_jobs)} NEW, relevant Canada jobs found\n")

    # ── Categorise by apply type ──────────────────────────────────────────
    by_type = {}
    for j in new_jobs:
        t = j["apply_type"]
        by_type.setdefault(t, []).append(j)

    log("Apply type breakdown:")
    for t, lst in sorted(by_type.items(), key=lambda x: -len(x[1])):
        log(f"    {t:25s} — {len(lst)} jobs")

    # ── Write report ──────────────────────────────────────────────────────
    report = {
        "date": today,
        "total_new": len(new_jobs),
        "by_type": {k: len(v) for k,v in by_type.items()},
        "jobs": new_jobs,
        "summary_for_claude": [
            {
                "title":      j["title"],
                "company":    j["company"],
                "location":   j["location"],
                "salary":     j["salary"],
                "url":        j["url"],
                "apply_type": j["apply_type"],
                "score":      j["score"],
                "days_old":   j["days_old"],
                "snippet":    j["snippet"][:400],
            }
            for j in new_jobs
        ]
    }

    if not dry_run:
        with open(REPORT_OUT, "w") as f:
            json.dump(report, f, indent=2)
        log(f"\nReport saved → {REPORT_OUT}")
    else:
        log("\n[DRY RUN] Report NOT saved")
        print(json.dumps(report["summary_for_claude"][:10], indent=2))

    log(f"\nDone. Found {len(new_jobs)} new jobs to process.")
    return report

if __name__ == "__main__":
    main()
