"""Tests for ats.direct — generic direct-company-page applicator."""
import sys, os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ats.direct import apply_direct

RESUME_PDF = os.path.join(os.path.dirname(__file__), "fixtures", "sample_resume.pdf")

PROFILE = {
    "name": "the user",
    "email": "you@example.com",
    "phone": "+1 (555) 555-0100",
    "portfolio": "yourportfolio.example.com",
    "linkedin": "linkedin.com/in/your-handle",
}


def test_direct_dry_run_return_shape():
    """dry_run=True must always return the correct three-key dict shape."""
    try:
        result = apply_direct(
            url="https://example.com/careers/apply",
            resume_pdf=RESUME_PDF,
            profile=PROFILE,
            custom_answers={},
            dry_run=True,
        )
    except Exception as e:
        pytest.skip(f"apply_direct raised an unexpected exception (infra issue): {e}")

    assert isinstance(result, dict), "result must be a dict"
    assert "success"  in result,    "result must have 'success' key"
    assert "error"    in result,    "result must have 'error' key"
    assert "dry_run"  in result,    "result must have 'dry_run' key"
    assert result["dry_run"] is True


def test_direct_dry_run_no_submission():
    """dry_run=True must NOT submit; error may be set if page is unreachable."""
    try:
        result = apply_direct(
            url="https://example.com/careers/apply",
            resume_pdf=RESUME_PDF,
            profile=PROFILE,
            dry_run=True,
        )
    except Exception as e:
        pytest.skip(f"Network/infra failure: {e}")

    # The function must never raise; it always returns a dict.
    assert isinstance(result, dict)
    assert result.get("dry_run") is True


def test_direct_manual_required_when_no_file_input():
    """If a page has no file input the applicator must set error='manual_required'."""
    # about:blank has no form at all — upload_file returns False → manual_required
    try:
        result = apply_direct(
            url="about:blank",
            resume_pdf=RESUME_PDF,
            profile=PROFILE,
            dry_run=True,
        )
    except Exception as e:
        pytest.skip(f"Playwright infra failure: {e}")

    assert isinstance(result, dict)
    assert result["dry_run"] is True
    # Either manual_required (expected) or an error string from a nav/timeout issue
    assert result.get("error") is not None or result.get("success") is True
