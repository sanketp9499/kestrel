# Scripts/tests/test_firecrawl_extract.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from firecrawl_extract import extract_jd, extract_custom_questions
from daily_log import load_profile
import pytest


def test_extract_jd_returns_string():
    """Scrape a public Greenhouse job posting and verify we get real content."""
    profile = load_profile()
    if not profile.get("firecrawl_key"):
        pytest.skip("FIRECRAWL_KEY not configured — set env var or add to Scripts/secrets.local.json")
    # Greenhouse test job (public, no auth)
    jd = extract_jd("https://boards.greenhouse.io/figma/jobs/5248420004")
    assert isinstance(jd, str)
    assert len(jd) > 100  # got some content


def test_extract_custom_questions_finds_prompts():
    """extract_custom_questions must detect lines ending with '?'."""
    sample = """
    ## About the role
    We are hiring a UX Designer.

    Please answer: Tell us about a project where you improved a user experience.
    Why do you want to work at our company?
    """
    questions = extract_custom_questions(sample)
    assert len(questions) >= 1
    assert any("project" in q.lower() for q in questions)


def test_extract_custom_questions_empty_on_no_questions():
    """Returns empty list when no question lines are present."""
    sample = "We are a great company. We value design."
    questions = extract_custom_questions(sample)
    assert questions == []


def test_extract_custom_questions_ignores_short_lines():
    """Short lines ending with '?' (e.g. 'Why?') must be ignored."""
    sample = "Why?\nTell us about a significant design challenge you overcame?"
    questions = extract_custom_questions(sample)
    assert len(questions) == 1
    assert "design challenge" in questions[0]


def test_extract_jd_returns_empty_without_key(monkeypatch):
    """extract_jd returns '' when no Firecrawl key is available."""
    import firecrawl_extract as fe
    # Patch load_profile to return a profile without a key
    monkeypatch.setattr(fe, "load_profile", lambda: {"name": "Test"})
    result = fe.extract_jd("https://example.com/job/123")
    assert result == ""
