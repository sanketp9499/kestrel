"""Phase 7's documented command line has never existed.

RUN_PIPELINE.md phase 7 says:

    python Scripts/email_monitor.py --applied '<json>' --captcha '<json>' \
        --responses '<json>' --errors '<json>'

`email_monitor.py`'s parser only ever defined --check-mail, --imap-only and
--days, and it reads them with `parse_known_args()`, which silently discards
the four documented flags. Running the documented line therefore never sent a
report - it fell through to a hardcoded sample and printed a "report" for a
Shopify Product Designer application that does not exist, then exited 0.

Every run has had to notice and work around it by hand. From the logs:

    2026-09-09  "Phase 7's documented CLI flags don't exist in email_monitor.py.
                 Called send_daily_report() directly instead"
    2026-09-11  "Runbook's Phase 7 command line does not exist ... Called
                 send_daily_report() directly instead"

A documented interface that silently does the wrong thing is worse than a
missing one, so the flags are implemented, unknown flags are now an error, and
the fake sample is gone.
"""
import json
import os
import subprocess
import sys

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(SCRIPTS)
APPLIED = json.dumps([{"company": "Palette", "role": "Senior Product Designer",
                       "url": "https://wellfound.com/jobs/4095826",
                       "ats_type": "Wellfound"}])


def _run(*args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "Scripts/email_monitor.py", *args],
                          cwd=WORKSPACE, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=180)


def test_the_documented_flags_are_accepted():
    p = _run("--applied", APPLIED, "--captcha", "[]", "--responses", "[]",
             "--errors", "[]", "--dry-run")
    assert p.returncode == 0, p.stdout + p.stderr


def test_the_report_is_built_from_what_was_passed_in():
    p = _run("--applied", APPLIED, "--captcha", "[]", "--responses", "[]",
             "--errors", "[]", "--dry-run")
    assert "Palette" in p.stdout, p.stdout + p.stderr


def test_the_fake_sample_report_is_gone():
    """It printed a Shopify application nobody made, formatted exactly like a
    real report."""
    p = _run("--applied", APPLIED, "--captcha", "[]", "--responses", "[]",
             "--errors", "[]", "--dry-run")
    assert "Shopify" not in p.stdout


def test_bare_invocation_does_not_print_a_report():
    p = _run()
    assert "Shopify" not in p.stdout
    assert p.returncode != 0 or "usage" in (p.stdout + p.stderr).lower()


def test_an_unknown_flag_is_an_error_not_a_silent_discard():
    """parse_known_args() is what let the documented flags vanish."""
    p = _run("--applied", APPLIED, "--dry-run", "--no-such-flag", "x")
    assert p.returncode != 0
    assert "no-such-flag" in (p.stdout + p.stderr)


def test_malformed_json_says_which_flag():
    p = _run("--applied", "[{not json", "--dry-run")
    assert p.returncode != 0
    assert "--applied" in (p.stdout + p.stderr)


def test_dry_run_does_not_send():
    p = _run("--applied", APPLIED, "--dry-run")
    assert "not sending" in (p.stdout + p.stderr).lower(), p.stdout + p.stderr


def test_the_runbook_and_the_parser_agree():
    """The contract test for the whole class: every flag the runbook shows for
    email_monitor.py must exist in its parser."""
    import re
    spec = open(os.path.join(SCRIPTS, "RUN_PIPELINE.md"), encoding="utf-8").read()
    src = open(os.path.join(SCRIPTS, "email_monitor.py"), encoding="utf-8").read()
    documented = set()
    for line in spec.splitlines():
        if "email_monitor.py" in line:
            documented.update(re.findall(r"--[a-z][a-z-]+", line))
    defined = set(re.findall(r'add_argument\(\s*"(--[a-z][a-z-]+)"', src))
    missing = sorted(documented - defined)
    assert missing == [], f"runbook documents flags the CLI does not have: {missing}"
