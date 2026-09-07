"""Tests for email_monitor.py.

Pure-function tests (classify_email, build_daily_report) run always.
Tests that require Gmail credentials skip gracefully when not configured.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from email_monitor import classify_email, build_daily_report, check_inbox, send_summary


# ── classify_email ─────────────────────────────────────────────────────────

def test_classify_interview():
    result = classify_email(
        "Interview Invitation — Product Designer",
        "We'd like to schedule an interview with you.",
    )
    assert result == "interview"


def test_classify_interview_availability():
    result = classify_email(
        "Next steps for your application",
        "We'd like to discuss your availability for a call next week.",
    )
    assert result == "interview"


def test_classify_rejection():
    result = classify_email(
        "Your application",
        "Unfortunately we will not be moving forward with your application.",
    )
    assert result == "rejection"


def test_classify_rejection_other_candidates():
    result = classify_email(
        "Update on your application to Shopify",
        "We have decided to move forward with other candidates at this time.",
    )
    assert result == "rejection"


def test_classify_update():
    result = classify_email(
        "Update on your application",
        "We received your application and it is currently under review.",
    )
    assert result is None


def test_classify_unknown():
    result = classify_email(
        "Newsletter",
        "Check out our latest blog posts and design resources.",
    )
    assert result is None


def test_classify_case_insensitive():
    result = classify_email(
        "INTERVIEW INVITATION",
        "Please SCHEDULE a time that works for you.",
    )
    assert result == "interview"


# Interview signals take priority over rejection signals in the same email
def test_classify_interview_priority_over_rejection():
    result = classify_email(
        "Next steps",
        "Unfortunately we still want to schedule an interview.",
    )
    assert result == "interview"


# ── build_daily_report ─────────────────────────────────────────────────────

def test_report_subject_includes_date_and_count():
    report = build_daily_report(
        applied=[{"company": "Shopify", "role": "Product Designer", "ats_type": "Greenhouse"}],
        captcha_pending=[],
        responses=[],
        errors=[],
    )
    assert "applied" in report["subject"].lower()
    assert "1" in report["subject"]


def test_report_body_lists_applied_jobs():
    report = build_daily_report(
        applied=[
            {"company": "Acme Corp", "role": "UX Designer", "ats_type": "Lever"},
        ],
        captcha_pending=[],
        responses=[],
        errors=[],
    )
    assert "Acme Corp" in report["body"]
    assert "UX Designer" in report["body"]


def test_report_body_includes_captcha_section():
    report = build_daily_report(
        applied=[],
        captcha_pending=[
            {"company": "FooCo", "role": "Designer", "url": "https://fooco.com/apply"}
        ],
        responses=[],
        errors=[],
    )
    assert "CAPTCHA" in report["body"]
    assert "FooCo" in report["body"]


def test_report_body_includes_interview_response():
    report = build_daily_report(
        applied=[],
        captcha_pending=[],
        responses=[
            {"subject": "Interview invite from Stripe", "from": "hr@stripe.com", "type": "interview"}
        ],
        errors=[],
    )
    assert "INTERVIEW" in report["body"]
    assert "Stripe" in report["body"]


def test_report_body_includes_rejection_response():
    report = build_daily_report(
        applied=[],
        captcha_pending=[],
        responses=[
            {"subject": "Your Shopify application", "from": "noreply@shopify.com", "type": "rejection"}
        ],
        errors=[],
    )
    assert "Rejected" in report["body"]
    assert "Shopify" in report["body"]


def test_report_interview_count_in_subject():
    report = build_daily_report(
        applied=[{"company": "Acme", "role": "UX Designer", "ats_type": ""}],
        captcha_pending=[],
        responses=[
            {"subject": "Interview invite", "from": "hr@acme.com", "type": "interview"}
        ],
        errors=[],
    )
    assert "interview" in report["subject"].lower()


def test_report_errors_section():
    report = build_daily_report(
        applied=[],
        captcha_pending=[],
        responses=[],
        errors=["Workday login wall at Loblaw", "Captcha at RBC careers"],
    )
    assert "ERRORS" in report["body"]
    assert "Loblaw" in report["body"]


def test_report_returns_dict_with_subject_and_body():
    report = build_daily_report([], [], [], [])
    assert isinstance(report, dict)
    assert "subject" in report
    assert "body" in report
    assert isinstance(report["subject"], str)
    assert isinstance(report["body"], str)


# ── check_inbox / send_summary (credential-dependent) ─────────────────────

def _gmail_configured() -> bool:
    """Return True only when Gmail credentials are available."""
    has_env = bool(
        os.environ.get("GMAIL_TOKEN_JSON") and os.environ.get("GMAIL_CREDENTIALS_JSON")
    )
    if has_env:
        return True
    # Check secrets.local.json
    secrets_path = os.path.join(os.path.dirname(__file__), "..", "secrets.local.json")
    if os.path.exists(secrets_path):
        try:
            import json
            with open(secrets_path, encoding="utf-8") as f:
                secrets = json.load(f)
            return bool(secrets.get("gmail_token"))
        except Exception:
            pass
    return False


def test_check_inbox_returns_list_without_credentials():
    """check_inbox() must return an empty list, not raise, when not configured."""
    profile = {}  # no credentials
    result = check_inbox(profile)
    assert isinstance(result, list)


def test_send_summary_returns_false_without_credentials():
    """send_summary() must return False (not raise) when not configured."""
    profile = {}
    result = send_summary(profile, applied_jobs=[], inbox_results=[])
    assert result is False


@pytest.mark.skipif(not _gmail_configured(), reason="Gmail credentials not configured")
def test_check_inbox_live():
    """Live test: check_inbox returns properly shaped dicts."""
    from daily_log import load_profile

    profile = load_profile()
    results = check_inbox(profile)
    assert isinstance(results, list)
    for item in results:
        assert "thread_id" in item
        assert "subject" in item
        assert "from" in item
        assert item["type"] in ("interview", "rejection", "other")


@pytest.mark.skipif(not _gmail_configured(), reason="Gmail credentials not configured")
def test_send_summary_live():
    """Live test: send_summary returns True with real credentials."""
    from daily_log import load_profile

    profile = load_profile()
    result = send_summary(
        profile,
        applied_jobs=[{"company": "TestCo", "role": "UX Designer", "ats_type": "Test"}],
        inbox_results=[],
    )
    assert result is True
