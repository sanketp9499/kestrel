import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from daily_log import load_profile

def test_profile_has_required_fields():
    profile = load_profile()
    required = ["name", "email", "phone", "portfolio"]
    for field in required:
        assert field in profile, f"Missing field: {field}"
    assert profile["email"] == "you@example.com"

def test_api_keys_available_via_env_or_secrets():
    import pytest
    profile = load_profile()
    if not profile.get("apify_token"):
        pytest.skip("APIFY_TOKEN not set — set env var or add to Scripts/secrets.local.json")
    if not profile.get("firecrawl_key"):
        pytest.skip("FIRECRAWL_KEY not set — set env var or add to Scripts/secrets.local.json")
