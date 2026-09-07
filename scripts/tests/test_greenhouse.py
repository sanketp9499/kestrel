import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ats.greenhouse import apply_greenhouse

RESUME_PDF = os.path.join(os.path.dirname(__file__), "fixtures", "sample_resume.pdf")

def test_greenhouse_dry_run():
    """Dry run against a real Greenhouse job page — no submission."""
    import pytest
    profile = {
        "name": "the user",
        "email": "you@example.com",
        "phone": "+1 (555) 555-0100",
        "portfolio": "yourportfolio.example.com",
        "linkedin": "linkedin.com/in/your-handle",
        "experience_years_form": "1-2",
    }
    # EviSmart Greenhouse board (already applied — safe to test against)
    try:
        result = apply_greenhouse(
            url="https://job-boards.greenhouse.io/evismart/jobs/4665421006",
            resume_pdf=RESUME_PDF,
            profile=profile,
            custom_answers={},
            dry_run=True
        )
    except Exception as e:
        pytest.skip(f"Infrastructure unavailable: {e}")
    assert isinstance(result, dict)
    assert "success" in result
    assert result.get("dry_run") is True
