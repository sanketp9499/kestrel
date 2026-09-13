"""A dry run must never appear in the run record.

`daily_log.init_log()` already sends the test suite to `test_log_<date>.txt`,
because run_history.py publishes the daily logs as the record of which days the
machine really worked, and fixture traffic in there is a lie about the run.

The guard keys off pytest's own environment, so it does not cover a dry run
started by hand - which is the normal way to check an adapter still works
against a live posting. Proof, from this very investigation: running
`greenhouse.py --dry-run` against a deliberately nonexistent URL appended

    [23:48:01]   Greenhouse: resume upload failed at
                 https://job-boards.greenhouse.io/does-not-exist/jobs/0

to daily_log_2026-09-12.txt, where it is indistinguishable from a real
application failing.

A dry run is by definition not an application, so the adapter routes its own
logging the same way the suite does.
"""
import io
import os
import re
import subprocess
import sys

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS)

import daily_log  # noqa: E402

ATS_DIR = os.path.join(SCRIPTS, "ats")


def test_use_test_log_repoints_an_already_open_log():
    """The adapter has usually logged its startup line before it parses args."""
    daily_log.init_log()
    daily_log.use_test_log()
    assert os.path.basename(daily_log._log_file).startswith("test_log_")


def test_use_test_log_is_idempotent():
    daily_log.use_test_log()
    first = daily_log._log_file
    daily_log.use_test_log()
    assert daily_log._log_file == first


def test_every_adapter_routes_its_dry_run():
    """Regression guard for the class: a new adapter with --dry-run and no
    routing writes fixture traffic into the public record."""
    offenders = []
    for name in sorted(os.listdir(ATS_DIR)):
        if not name.endswith(".py") or name in ("base.py", "__init__.py"):
            continue
        src = io.open(os.path.join(ATS_DIR, name), encoding="utf-8").read()
        if "--dry-run" not in src:
            continue
        if not re.search(r"use_test_log\s*\(", src):
            offenders.append(name)
    assert offenders == [], f"adapters logging dry runs to the run record: {offenders}"


def test_a_real_dry_run_leaves_the_daily_log_untouched(tmp_path):
    """End to end, through the actual CLI, in a subprocess with no pytest
    environment - the exact condition the existing guard misses."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTEST_CURRENT_TEST", "KESTREL_TEST_LOG")}
    env["PYTHONIOENCODING"] = "utf-8"
    workspace = os.path.dirname(SCRIPTS)
    daily = os.path.join(SCRIPTS, "daily_log_%s.txt" %
                         __import__("datetime").date.today().isoformat())
    before = os.path.getsize(daily) if os.path.exists(daily) else 0

    subprocess.run(
        [sys.executable, "Scripts/ats/greenhouse.py", "--url",
         "https://job-boards.greenhouse.io/does-not-exist/jobs/0",
         "--resume", "Scripts/sanket_profile.json", "--dry-run", "--headless",
         "--company", "DryRunGuard", "--role", "Routing test"],
        cwd=workspace, capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, timeout=300)

    after = os.path.getsize(daily) if os.path.exists(daily) else 0
    assert after == before, "a dry run appended to the daily log"
