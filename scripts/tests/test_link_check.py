"""Is the posting still there, before we spend anything on it?

Nothing checked. The pipeline would resolve a job, spend a Firecrawl credit
extracting the JD, spend Claude calls tailoring a resume and writing a cover
letter, create the folder, and only discover at phase 5 that the posting was
gone. `ats_resolver.py` records the scale of it: "11 of 13 Lever slugs and 10 of
17 Greenhouse slugs now 404".

Borrowed from mayankjoshii/claude-job-skill, which verifies every URL loads
before presenting it.

The hard part is not the 200. It is that the interesting failures are not status
codes: an expired posting frequently returns 200 with "this job is no longer
accepting applications" in the body, and a live posting frequently returns 403
because a bot filter dislikes urllib. Getting either of those backwards is worse
than not checking - one wastes the day, the other silently drops real jobs.
"""
import os
import sys

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS)

from link_check import check_url, filter_alive  # noqa: E402


def fake(status, body="", error=None):
    """Stand in for the network: returns what a fetch would have returned."""
    def _fetch(url, timeout=15):
        if error:
            raise error
        return status, body
    return _fetch


LIVE_PAGE = "<html><body><h1>Senior Product Designer</h1>Apply now</body></html>"


def test_a_live_posting_passes():
    ok, why = check_url("https://example.com/job/1", fetch=fake(200, LIVE_PAGE))
    assert ok is True, why


def test_404_is_dead():
    ok, why = check_url("https://example.com/job/1", fetch=fake(404))
    assert ok is False and "404" in why


def test_410_is_dead():
    ok, why = check_url("https://example.com/job/1", fetch=fake(410))
    assert ok is False


def test_403_is_treated_as_alive():
    """A bot filter is not evidence the job is gone. Dropping these would throw
    away real postings - Cloudflare-fronted boards return 403 to urllib all day.
    """
    ok, why = check_url("https://example.com/job/1", fetch=fake(403))
    assert ok is True, why
    assert "403" in why


def test_429_is_treated_as_alive():
    ok, _ = check_url("https://example.com/job/1", fetch=fake(429))
    assert ok is True


def test_a_timeout_is_not_a_death_sentence():
    ok, why = check_url("https://example.com/job/1",
                        fetch=fake(0, error=TimeoutError("timed out")))
    assert ok is True
    assert "timeout" in why.lower() or "unreachable" in why.lower()


def test_200_but_the_posting_is_closed():
    """The common case, and the one a status check alone misses."""
    for phrase in ("This job is no longer accepting applications",
                   "This position has been filled",
                   "Job posting not found",
                   "no longer available",
                   "This role is closed"):
        body = f"<html><body><p>{phrase}</p></body></html>"
        ok, why = check_url("https://example.com/job/1", fetch=fake(200, body))
        assert ok is False, f"{phrase!r} passed as live"
        assert "closed" in why.lower() or "not found" in why.lower()


def test_a_jd_that_merely_mentions_closing_is_not_closed():
    """Postings say things like "applications close on Friday" and "we are
    closing the loop with candidates". Substring panic would drop them."""
    for phrase in ("Applications close on Friday",
                   "You will be closing the loop with stakeholders",
                   "Help us fill the gap in our design system"):
        body = f"<html><body><p>{phrase}</p></body></html>"
        ok, why = check_url("https://example.com/job/1", fetch=fake(200, body))
        assert ok is True, f"{phrase!r} was wrongly called dead: {why}"


def test_an_empty_body_with_200_is_alive():
    """JS-rendered boards return a near-empty shell. Not evidence of anything."""
    ok, _ = check_url("https://example.com/job/1", fetch=fake(200, ""))
    assert ok is True


def test_filter_alive_splits_the_batch_and_says_why():
    jobs = [{"company": "Live", "url": "https://example.com/1"},
            {"company": "Dead", "url": "https://example.com/2"}]

    def _fetch(url, timeout=15):
        return (404, "") if url.endswith("/2") else (200, LIVE_PAGE)

    kept, dropped = filter_alive(jobs, fetch=_fetch)
    assert [j["company"] for j in kept] == ["Live"]
    assert dropped[0]["company"] == "Dead"
    assert "404" in dropped[0]["dead_reason"]


def test_filter_alive_keeps_a_job_with_no_url_rather_than_guessing():
    kept, dropped = filter_alive([{"company": "NoUrl"}], fetch=fake(404))
    assert [j["company"] for j in kept] == ["NoUrl"]
