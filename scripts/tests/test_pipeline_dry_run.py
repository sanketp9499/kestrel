"""test_pipeline_dry_run.py — End-to-end dry-run importability check.

Verifies that every module the pipeline depends on is importable and
exposes the correct public functions.  No network calls are made
(Apify, Firecrawl, Gmail, Playwright) — this is purely a static
import and signature check.

Also verifies that:
- Scripts/RUN_PIPELINE.md exists and is > 50 lines
- Scripts/setup_scheduler.ps1 exists and contains the expected task name
"""
import sys, os, inspect

# Make all Scripts/ modules importable regardless of where pytest is invoked
SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SCRIPTS_DIR)

import pytest

# ── Helpers ──────────────────────────────────────────────────────────────────

def _has_param(func, name):
    """Return True if *func* has a parameter called *name*."""
    try:
        sig = inspect.signature(func)
        return name in sig.parameters
    except (ValueError, TypeError):
        return False


# ── 1. ATS modules ───────────────────────────────────────────────────────────

def test_greenhouse_importable():
    from ats.greenhouse import apply_greenhouse
    assert callable(apply_greenhouse)

def test_greenhouse_signature():
    from ats.greenhouse import apply_greenhouse
    assert _has_param(apply_greenhouse, "url")
    assert _has_param(apply_greenhouse, "dry_run")

def test_lever_importable():
    from ats.lever import apply_lever
    assert callable(apply_lever)

def test_lever_signature():
    from ats.lever import apply_lever
    assert _has_param(apply_lever, "url")
    assert _has_param(apply_lever, "dry_run")

def test_workable_importable():
    from ats.workable import apply_workable
    assert callable(apply_workable)

def test_workable_signature():
    from ats.workable import apply_workable
    assert _has_param(apply_workable, "url")
    assert _has_param(apply_workable, "dry_run")

def test_linkedin_importable():
    from ats.linkedin import apply_linkedin
    assert callable(apply_linkedin)

def test_linkedin_signature():
    from ats.linkedin import apply_linkedin
    assert _has_param(apply_linkedin, "url")
    assert _has_param(apply_linkedin, "dry_run")

def test_indeed_importable():
    from ats.indeed import apply_indeed
    assert callable(apply_indeed)

def test_indeed_signature():
    from ats.indeed import apply_indeed
    assert _has_param(apply_indeed, "url")
    assert _has_param(apply_indeed, "dry_run")

def test_workday_importable():
    from ats.workday import apply_workday
    assert callable(apply_workday)

def test_workday_signature():
    from ats.workday import apply_workday
    assert _has_param(apply_workday, "url")
    assert _has_param(apply_workday, "dry_run")

def test_direct_importable():
    from ats.direct import apply_direct
    assert callable(apply_direct)

def test_direct_signature():
    from ats.direct import apply_direct
    assert _has_param(apply_direct, "url")
    assert _has_param(apply_direct, "dry_run")


# ── 2. Email monitor ─────────────────────────────────────────────────────────

def test_check_inbox_importable():
    from email_monitor import check_inbox
    assert callable(check_inbox)

def test_check_inbox_signature():
    from email_monitor import check_inbox
    assert _has_param(check_inbox, "profile")

def test_send_summary_importable():
    from email_monitor import send_summary
    assert callable(send_summary)

def test_send_summary_signature():
    from email_monitor import send_summary
    assert _has_param(send_summary, "profile")
    assert _has_param(send_summary, "applied_jobs")


# ── 3. Apify scraper ─────────────────────────────────────────────────────────

def test_scrape_all_importable():
    from apify_scraper import scrape_all
    assert callable(scrape_all)

def test_scrape_all_signature():
    from apify_scraper import scrape_all
    assert _has_param(scrape_all, "search_terms")


# ── 4. Firecrawl extractor ───────────────────────────────────────────────────

def test_extract_jd_importable():
    from firecrawl_extract import extract_jd
    assert callable(extract_jd)

def test_extract_jd_signature():
    from firecrawl_extract import extract_jd
    assert _has_param(extract_jd, "url")


# ── 5. Pipeline prompt and scheduler files ───────────────────────────────────

WORKSPACE = os.path.abspath(os.path.join(SCRIPTS_DIR, ".."))

def test_run_pipeline_md_exists():
    path = os.path.join(WORKSPACE, "Scripts", "RUN_PIPELINE.md")
    assert os.path.exists(path), f"RUN_PIPELINE.md not found at {path}"

def test_run_pipeline_md_has_enough_lines():
    path = os.path.join(WORKSPACE, "Scripts", "RUN_PIPELINE.md")
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) > 50, f"RUN_PIPELINE.md is only {len(lines)} lines — expected > 50"

def test_setup_scheduler_ps1_exists():
    path = os.path.join(WORKSPACE, "Scripts", "setup_scheduler.ps1")
    assert os.path.exists(path), f"setup_scheduler.ps1 not found at {path}"

def test_setup_scheduler_contains_task_name():
    path = os.path.join(WORKSPACE, "Scripts", "setup_scheduler.ps1")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "the userJobHuntPipeline" in content, (
        "Expected task name 'the userJobHuntPipeline' not found in setup_scheduler.ps1"
    )

def test_setup_scheduler_contains_daily_trigger():
    path = os.path.join(WORKSPACE, "Scripts", "setup_scheduler.ps1")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "Daily" in content or "-Daily" in content, (
        "Expected daily trigger (-Daily) not found in setup_scheduler.ps1"
    )

def test_setup_scheduler_contains_08am():
    path = os.path.join(WORKSPACE, "Scripts", "setup_scheduler.ps1")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "08:00" in content or "8:00AM" in content or "08:00AM" in content, (
        "Expected 08:00 AM schedule not found in setup_scheduler.ps1"
    )

def test_setup_scheduler_ps1_parseable():
    """Verify setup_scheduler.ps1 has no obvious PowerShell syntax errors via Get-Command check.

    We parse it with PowerShell's -File combined with a safe dry-run technique:
    use the tokenizer (Parser::ParseFile) via pwsh/powershell if available,
    falling back to a simple heuristic check.
    """
    path = os.path.join(WORKSPACE, "Scripts", "setup_scheduler.ps1")
    import subprocess, shutil
    ps_exe = shutil.which("powershell") or shutil.which("pwsh")
    if ps_exe is None:
        pytest.skip("PowerShell not available in test environment")

    # Use PSParser tokenization — exits 0 if no syntax errors
    parse_cmd = (
        f"$err = $null; "
        f"[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw '{path}'), [ref]$err); "
        f"if ($err.Count -gt 0) {{ Write-Error \"Parse errors: $($err.Count)\"; exit 1 }}"
    )
    result = subprocess.run(
        [ps_exe, "-NonInteractive", "-NoProfile", "-Command", parse_cmd],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30
    )
    assert result.returncode == 0, (
        f"PowerShell syntax error in setup_scheduler.ps1:\n{result.stderr}"
    )


# ── 6. ATS __init__ is importable (smoke-test the package) ───────────────────

def test_ats_package_importable():
    import ats
    assert ats is not None
