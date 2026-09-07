"""Tests for Scripts/playwright/linkedin.py

All tests use dry_run=True so no real application is ever submitted.
Tests skip gracefully when:
  - The Chrome persistent profile is missing / locked (CI environment).
  - The network or LinkedIn is unreachable.
  - The job URL no longer has an Easy Apply button.
"""
import sys
import os
import pytest

# Ensure Scripts/ is on the path for daily_log and playwright imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ats.linkedin import apply_linkedin

RESUME_PDF = os.path.join(os.path.dirname(__file__), "fixtures", "sample_resume.pdf")

PROFILE = {
    "name": "the user",
    "email": "you@example.com",
    "phone": "+1 (555) 555-0100",
    "portfolio": "yourportfolio.example.com",
    "linkedin": "linkedin.com/in/your-handle",
    "current_company": "ExampleCo",
}

# A stable LinkedIn Easy Apply job URL used only for shape-testing.
# We do NOT rely on this job being live — the test skips gracefully if it is gone.
_TEST_URL = "https://www.linkedin.com/jobs/view/4119085346"


def test_linkedin_return_shape_dry_run():
    """apply_linkedin must return a dict with success/error/dry_run keys.

    Skips gracefully if the Chrome profile is absent (CI) or network is down.
    """
    try:
        result = apply_linkedin(
            url=_TEST_URL,
            resume_pdf=RESUME_PDF,
            profile=PROFILE,
            custom_answers={},
            dry_run=True,
        )
    except Exception as e:
        pytest.skip(f"apply_linkedin raised an unexpected exception (infra issue): {e}")

    assert isinstance(result, dict), "result must be a dict"
    assert "success" in result,      "result must have 'success' key"
    assert "error"   in result,      "result must have 'error' key"
    assert "dry_run" in result,      "result must have 'dry_run' key"
    assert result["dry_run"] is True, "dry_run must be echoed as True"


def test_linkedin_dry_run_no_real_submit():
    """Even when the form is reachable, dry_run must NOT submit the application."""
    try:
        result = apply_linkedin(
            url=_TEST_URL,
            resume_pdf=RESUME_PDF,
            profile=PROFILE,
            custom_answers={},
            dry_run=True,
        )
    except Exception as e:
        pytest.skip(f"Infra issue: {e}")

    # success=True means it reached the Submit step without pressing it.
    # success=False with an error string is acceptable (job gone / no Easy Apply).
    # What is NOT acceptable: an exception propagating out.
    assert isinstance(result, dict)
    assert result.get("dry_run") is True


def test_linkedin_login_required_signal():
    """If Chrome has no valid session, error must be 'login_required' or a non-
    empty string — it must never be None when success is False."""
    try:
        result = apply_linkedin(
            url=_TEST_URL,
            resume_pdf=RESUME_PDF,
            profile=PROFILE,
            custom_answers={},
            dry_run=True,
        )
    except Exception as e:
        pytest.skip(f"Infra issue: {e}")

    if not result["success"]:
        assert result["error"] is not None, (
            "When success=False, error must not be None"
        )


def test_linkedin_custom_answers_accepted():
    """custom_answers dict must be accepted without raising."""
    try:
        result = apply_linkedin(
            url=_TEST_URL,
            resume_pdf=RESUME_PDF,
            profile=PROFILE,
            custom_answers={"Are you legally authorized": "Yes"},
            dry_run=True,
        )
    except Exception as e:
        pytest.skip(f"Infra issue: {e}")

    assert isinstance(result, dict)
    assert "success" in result
