"""What the Apify scraper lets through, and what it costs when Apify is down.

Three separate problems, all found on 2026-09-13:

1. `SKIP_TITLES` in apify_scraper.py catches nothing. Run over the 67 distinct
   titles in the recent pool it matched **0**. It looks for "staff designer"
   (real title: "Staff Product Designer"), "director", "head of" - and never
   mentions "senior" or "sr", which is 26% of everything the scan returns.
   Every one of these passed the filter:

       Senior Product Designer          Staff Product Designer
       Senior UX Designer               Sr Learning and Experience Designer
       Senior Product Designer, Payments

   They then cost a Firecrawl extraction and a Claude read each, before phase 3
   rejected them on "6+ years required". That is the inaccuracy: not that the
   wrong jobs are found, but that nothing drops them until after they are paid
   for.

2. `role_filter.py` already does this correctly and is imported by `board_sweep`
   and `cloud_scan` - the two scrapers that are NOT in the daily run. The one
   that IS wired in uses its own broken copy.

3. The quota failure is silent. `scrape_indeed` catches every exception and
   returns `[]`, so "Apify is out of credit" and "Apify found nothing today"
   produce the same log line and the same empty pool.
"""
import os
import sys

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS)

import apify_scraper  # noqa: E402
from apify_scraper import filter_canada, filter_roles  # noqa: E402


def _job(title, location="Toronto, ON"):
    return {"title": title, "location": location, "snippet": "", "url": "u"}


# The exact titles that passed the old filter, from the real pool.
SENIOR_TITLES = [
    "Senior Product Designer (Systems + UX) - Equity only",
    "Senior UX Designer",
    "Staff Product Designer",
    "Senior Product Designer, Payments",
    "Senior UX/UI Designer",
    "Senior Service Designer",
    "Sr Learning and Experience Designer",
    "Lead Product Designer",
    "Principal Designer",
]

KEEP_TITLES = [
    "UX Designer",
    "Product Designer",
    "UI/UX Designer",
    "Junior Product Designer",
    "Interaction Designer",
    "Digital Designer",
]


def test_senior_titles_are_kept_but_labelled():
    """Corrected 2026-09-13. Seniority is not a drop reason - "if eligible, why
    not" - so these stay in the pool. What matters is that the label is right,
    because phase 3 ranks on it and experience_gate.py decides eligibility from
    the number the posting states, not from the word in its title.
    """
    from role_filter import seniority
    kept = [j["title"] for j in filter_roles([_job(t) for t in SENIOR_TITLES])]
    assert kept == SENIOR_TITLES, f"wrongly dropped: {set(SENIOR_TITLES) - set(kept)}"
    for t in SENIOR_TITLES:
        assert seniority(t) == "senior", f"{t} was not labelled senior"


def test_the_roles_he_can_actually_get_survive():
    kept = [j["title"] for j in filter_roles([_job(t) for t in KEEP_TITLES])]
    assert kept == KEEP_TITLES, f"dropped a real target: {set(KEEP_TITLES) - set(kept)}"


def test_non_design_roles_are_dropped():
    for title in ("Mobile App Tester - User Experience & Feedback",
                  "Backend Engineer, Developer & End-user Experience Platform",
                  "Manager, Learning & Development",
                  "Seasonal Sales Associate (McArthurGlen Designer Outlet)"):
        assert filter_roles([_job(title)]) == [], title


def test_a_drop_is_explained_not_silent():
    """Phase 1 has to be able to log why the pool shrank."""
    off_role = [_job("Backend Engineer, Developer & End-user Experience Platform"),
                _job("Seasonal Sales Associate (McArthurGlen Designer Outlet)"),
                _job("Mobile App Tester - User Experience & Feedback")]
    kept, dropped = apify_scraper.filter_roles_verbose(off_role)
    assert kept == []
    assert len(dropped) == 3
    assert all(d["drop_reason"] for d in dropped)


def test_french_postings_are_judged_too():
    """Quebec postings are a real share of the pool and were being misread.

        "UX/UI Designer senior"  - accented "senior" missed the pattern, so the
                                   role was labelled mid when it is senior
        "Chercheur experience utilisateur (UX) - Stage/Co-op 4 mois"
                                 - "Stage" is French for internship, and an
                                   internship is genuinely not applicable
    """
    from role_filter import seniority
    assert seniority("UX/UI Designer sénior") == "senior"
    assert seniority("UX/UI Designer senior") == "senior"
    assert len(filter_roles([_job("UX/UI Designer sénior")])) == 1  # kept, just labelled

    # Internships are still dropped: he has graduated.
    assert filter_roles([_job(
        "Chercheur expérience utilisateur (UX)– Stage/Co-op 4 mois (H/F)")]) == []
    assert filter_roles([_job("Designer UX - Stage")]) == []

    # ...without dropping a real French mid-level posting
    assert len(filter_roles([_job("Designer web")])) == 1
    assert len(filter_roles([_job("Concepteur UX")])) == 1


def test_filter_canada_still_works():
    jobs = [_job("UX Designer", "Toronto, ON"),
            _job("UX Designer", "New York, NY"),
            _job("Product Designer", "Remote (Canada)")]
    assert len(filter_canada(jobs)) == 2


def test_quota_failure_is_distinguishable_from_an_empty_day(monkeypatch):
    """"Out of credit" and "no jobs matched" must not look the same.

    Verified live on 2026-09-13: the account is FREE plan, $5/month, sitting at
    $5.16 used, and a real actor call raises ForbiddenError("Monthly usage hard
    limit exceeded"). The old code swallowed it and returned [].
    """
    class Boom(Exception):
        pass

    def explode(*a, **kw):
        raise Boom("Monthly usage hard limit exceeded")

    monkeypatch.setattr(apify_scraper, "_run_actor", explode, raising=False)
    apify_scraper.reset_status()
    jobs = apify_scraper.scrape_indeed(object(), "UX Designer", max_items=5)
    assert jobs == []
    status = apify_scraper.last_status()
    assert status["quota_exceeded"] is True
    assert "hard limit" in status["error"].lower()


def test_a_normal_empty_result_is_not_reported_as_quota(monkeypatch):
    def empty(*a, **kw):
        return []

    monkeypatch.setattr(apify_scraper, "_run_actor", empty, raising=False)
    apify_scraper.reset_status()
    assert apify_scraper.scrape_indeed(object(), "UX Designer", max_items=5) == []
    assert apify_scraper.last_status()["quota_exceeded"] is False


def test_the_test_suite_does_not_bill_apify():
    """A live actor call per test run is real money on a $5/month plan, and the
    suite ran six times in one evening while this was being debugged. The live
    check is opt-in now.
    """
    src = open(os.path.join(SCRIPTS, "tests", "test_apify_scraper.py"),
               encoding="utf-8").read()
    assert "KESTREL_LIVE_APIFY" in src, (
        "test_apify_scraper.py still calls the paid API on every run")
