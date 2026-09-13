# Scripts/tests/test_apify_scraper.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from apify_scraper import scrape_all, filter_canada
from daily_log import load_profile
import pytest

def test_filter_canada_keeps_canada():
    jobs = [
        {"location": "Toronto, ON", "title": "UX Designer", "snippet": ""},
        {"location": "New York, NY", "title": "UX Designer", "snippet": ""},
        {"location": "Remote (Canada)", "title": "Product Designer", "snippet": ""},
    ]
    result = filter_canada(jobs)
    assert len(result) == 2
    assert all("NY" not in j["location"] for j in result)

def test_scrape_all_returns_list():
    """Opt-in: this spends real money.

    It used to run on every `pytest` invocation, firing two paid actor runs each
    time. The account is a FREE plan with a $5/month hard cap, and on 2026-09-13
    it was sitting at $5.16 used with actor calls returning
    ForbiddenError("Monthly usage hard limit exceeded"). Six suite runs in one
    debugging session is twelve billed actor runs.

    Set KESTREL_LIVE_APIFY=1 to actually check the live integration.
    """
    if not os.environ.get("KESTREL_LIVE_APIFY"):
        pytest.skip("live Apify call costs credit; set KESTREL_LIVE_APIFY=1 to run")
    profile = load_profile()
    if not profile.get("apify_token"):
        pytest.skip("Apify token not configured")
    results = scrape_all(["ux designer"], max_per_term=3)
    assert isinstance(results, list)
    if results:
        assert "title" in results[0]
        assert "url" in results[0]
