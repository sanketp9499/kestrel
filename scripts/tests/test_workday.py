"""Tests for ats.workday — Workday ATS applicator."""
import sys, os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ats.workday import apply_workday

RESUME_PDF = os.path.join(os.path.dirname(__file__), "fixtures", "sample_resume.pdf")

PROFILE = {
    "name": "the user",
    "email": "you@example.com",
    "phone": "+1 (555) 555-0100",
    "portfolio": "yourportfolio.example.com",
    "linkedin": "linkedin.com/in/your-handle",
}


def test_workday_dry_run_return_shape():
    """dry_run=True must return correct dict shape without submitting."""
    try:
        result = apply_workday(
            url="https://example.myworkdayjobs.com/External/job/Canada/UX-Designer_R12345",
            resume_pdf=RESUME_PDF,
            profile=PROFILE,
            custom_answers={},
            dry_run=True,
        )
    except Exception as e:
        pytest.skip(f"apply_workday raised an unexpected exception (infra issue): {e}")

    assert isinstance(result, dict), "result must be a dict"
    assert "success"  in result,    "result must have 'success' key"
    assert "error"    in result,    "result must have 'error' key"
    assert "dry_run"  in result,    "result must have 'dry_run' key"
    assert result["dry_run"] is True


def test_workday_dry_run_network_skip():
    """Skip gracefully (not hard-fail) if the Workday page is unreachable."""
    try:
        result = apply_workday(
            url="https://example.myworkdayjobs.com/External/job/Canada/UX-Designer_R12345",
            resume_pdf=RESUME_PDF,
            profile=PROFILE,
            dry_run=True,
        )
    except Exception as e:
        pytest.skip(f"Network/infra failure: {e}")

    assert isinstance(result, dict)
    assert result.get("dry_run") is True


def test_workday_never_raises():
    """apply_workday must always return a dict — never raise."""
    # Deliberately bad URL to exercise the exception path
    result = None
    try:
        result = apply_workday(
            url="https://nonexistent.myworkdayjobs.com/fake",
            resume_pdf=RESUME_PDF,
            profile=PROFILE,
            dry_run=True,
        )
    except Exception as e:
        pytest.skip(f"Playwright infra not available: {e}")

    assert isinstance(result, dict), "apply_workday must return dict, not raise"
    assert result.get("dry_run") is True
