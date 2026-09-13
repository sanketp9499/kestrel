"""The result contract between an ATS adapter and the phase 5 runner.

On 2026-09-12 both jobs in phase 5 were recorded as
``{"success": false, "error": "no_json_result"}`` even though the adapters had
done their work correctly - Wellfound uploaded the resume and reported
held_safe_mode, LinkedIn correctly found no Easy Apply button. The verdicts
were thrown away and the adapters were then run a SECOND time by hand to
recover them, which with safe mode off is a double submission.

Root cause: every adapter ends with ``print(json.dumps(result, indent=2))``, so
the result spans many lines. That day's runner accepted a result only if one
single line both started with "{" and ended with "}". Pretty-printed JSON never
does, so the parse failed 100% of the time, not intermittently.

The deeper cause is that phase 5's runner is regenerated from the runbook on
every run, and each generation invented its own parser - four different ones
exist in Scripts/ (_phase5.py, _phase5_run.py, _phase5_2026-09-09.py,
_phase5_2026-09-12.py). Two use a greedy brace regex that breaks on any earlier
"{" in the log output; one is line-based and never worked.

So the contract lives in code that both sides import, and these tests pin it.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ats.base import emit_result, parse_result  # noqa: E402

ATS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ats")


def _capture(result):
    """Adapter side: what a real adapter writes to stdout."""
    buf = io.StringIO()
    stdout, sys.stdout = sys.stdout, buf
    try:
        emit_result(result)
    finally:
        sys.stdout = stdout
    return buf.getvalue()


def test_round_trip_is_the_whole_point():
    result = {"success": True, "verdict": "applied", "signal": "confirmation page"}
    assert parse_result(_capture(result)) == result


def test_the_exact_2026_09_12_failure():
    """Pretty-printed output is what every adapter has always emitted."""
    out = json.dumps({"success": False, "error": "held_safe_mode"}, indent=2)
    assert parse_result(out) == {"success": False, "error": "held_safe_mode"}


def test_log_noise_before_the_result_does_not_swallow_it():
    """The greedy-brace parsers match from the first "{" in the output. Adapters
    print progress lines containing braces, so the match started in the wrong
    place and json.loads raised."""
    out = (
        'Wellfound: resume uploaded from {folder}\\Palette_Resume.pdf\n'
        'answered {"years": "3"} for the experience question\n'
        + json.dumps({"success": False, "error": "login_required"}, indent=2)
    )
    assert parse_result(out) == {"success": False, "error": "login_required"}


def test_trailing_noise_after_the_result_does_not_hide_it():
    """Playwright writes teardown warnings to the same stream, after the result."""
    out = _capture({"success": True, "verdict": "applied"})
    out += "\nBrowser context closed\nfuture: <Task finished coro=<...>>\n"
    assert parse_result(out)["verdict"] == "applied"


def test_stderr_is_searched_too():
    """Runners concatenate stdout+stderr; some adapters buffer oddly on Windows
    and the result lands in the other stream."""
    assert parse_result("", _capture({"success": True}))["success"] is True


def test_no_output_is_reported_not_raised():
    """A crashed adapter must produce a recorded failure, never an exception
    that aborts the rest of the queue."""
    res = parse_result("")
    assert res["success"] is False
    assert res["error"] == "no_adapter_result"


def test_truncated_json_is_reported_not_raised():
    res = parse_result('KESTREL_RESULT {"success": true, "verdict": "app')
    assert res["success"] is False
    assert res["error"] == "no_adapter_result"


def test_the_raw_output_is_kept_for_diagnosis():
    res = parse_result("Traceback (most recent call last):\n  boom\n")
    assert "boom" in res["raw"]


def test_a_failure_result_is_never_silently_upgraded():
    """parse_result must not invent success for output it could not read."""
    assert parse_result("done!").get("success") is False


def test_every_adapter_uses_the_shared_emitter():
    """A new adapter that prints its own JSON reintroduces the bug. This is the
    regression guard for the whole class, not just for the nine that exist."""
    offenders = []
    for name in sorted(os.listdir(ATS_DIR)):
        if not name.endswith(".py") or name in ("base.py", "__init__.py"):
            continue
        src = io.open(os.path.join(ATS_DIR, name), encoding="utf-8").read()
        if "__main__" not in src:
            continue
        if re.search(r"print\s*\(\s*json\.dumps\s*\(\s*result", src):
            offenders.append(name)
        elif "emit_result(" not in src:
            offenders.append(name)
    assert offenders == [], f"adapters not on the result contract: {offenders}"
