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
    # Requires real Apify token — skip if not set
    profile = load_profile()
    if not profile.get("apify_token"):
        pytest.skip("Apify token not configured")
    results = scrape_all(["ux designer"], max_per_term=3)
    assert isinstance(results, list)
    if results:
        assert "title" in results[0]
        assert "url" in results[0]
