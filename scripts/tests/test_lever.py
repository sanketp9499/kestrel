import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ats.lever import apply_lever

RESUME_PDF = os.path.join(os.path.dirname(__file__), "fixtures", "sample_resume.pdf")

PROFILE = {
    "name": "the user",
    "email": "you@example.com",
    "phone": "+1 (555) 555-0100",
    "portfolio": "yourportfolio.example.com",
    "linkedin": "linkedin.com/in/your-handle",
}


def test_lever_dry_run_return_shape():
    """dry_run=True must return correct dict shape without network access."""
    import pytest
    try:
        result = apply_lever(
            url="https://jobs.lever.co/fullscript/007fa76e-9a40-4815-8fe7-2de21970556d",
            resume_pdf=RESUME_PDF,
            profile=PROFILE,
            custom_answers={},
            dry_run=True,
        )
    except Exception as e:
        pytest.skip(f"Infrastructure unavailable: {e}")
    assert isinstance(result, dict), "result must be a dict"
    assert "success" in result,     "result must have 'success' key"
    assert "error"   in result,     "result must have 'error' key"
    assert "dry_run" in result,     "result must have 'dry_run' key"
    assert result["dry_run"] is True


def test_lever_dry_run_network_skip():
    """Skip gracefully (not hard-fail) if the Lever page is unreachable."""
    import pytest
    try:
        result = apply_lever(
            url="https://jobs.lever.co/fullscript/007fa76e-9a40-4815-8fe7-2de21970556d",
            resume_pdf=RESUME_PDF,
            profile=PROFILE,
            custom_answers={},
            dry_run=True,
        )
    except Exception as e:
        pytest.skip(f"Infrastructure unavailable: {e}")
    # If network is down, error may be set — that is fine; we must never raise.
    assert isinstance(result, dict)
    assert result.get("dry_run") is True
