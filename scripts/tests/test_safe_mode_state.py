"""Safe mode's state model, and that every adapter is covered by it.

On 2026-09-12 safe mode was turned off deliberately and the 08:00 run submitted
nothing anyway: "off" was the *absence* of SAFE_MODE.json, the run could not
tell a deliberate off from a lost safety file, failed closed, and restored the
hold. It was right to be suspicious - absence is not consent - so the fix was
to make a deliberate off a recorded decision rather than a missing file.

The same run found that three adapters clicked submit without ever asking. The
coverage test below fails if a new adapter is added and forgets.
"""
import importlib
import io
import json
import os
import re
import sys

import pytest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS)

import safe_mode  # noqa: E402

ATS_DIR = os.path.join(SCRIPTS, "ats")


@pytest.fixture
def flagfile(tmp_path, monkeypatch):
    """Point safe_mode at a throwaway flag so tests never touch the real one."""
    f = tmp_path / "SAFE_MODE.json"
    monkeypatch.setattr(safe_mode, "FLAG", str(f))
    monkeypatch.delenv("KESTREL_SAFE_MODE", raising=False)
    return f


def test_off_is_written_down_not_deleted(flagfile):
    """The bug. Turning off used to remove the file, which is indistinguishable
    from the file having been lost."""
    safe_mode.set_mode(False, note="Sanket asked for it off")
    assert flagfile.exists(), "a deliberate off must leave a record"
    data = json.loads(io.open(flagfile, encoding="utf-8").read())
    assert data["on"] is False
    assert "Sanket asked" in data["note"]
    assert not safe_mode.is_on("submit")
    assert not safe_mode.is_on("email")


def test_a_missing_file_still_fails_closed(flagfile):
    """Absence is not consent: an unconfigured machine holds."""
    assert not flagfile.exists()
    s = safe_mode.state()
    assert s["on"] is True
    assert s.get("unset") is True
    assert safe_mode.is_on("submit")


def test_an_unreadable_file_fails_closed(flagfile):
    flagfile.write_text("{ this is not json", encoding="utf-8")
    assert safe_mode.state()["on"] is True
    assert safe_mode.is_on("submit")


def test_a_file_with_no_on_key_is_read_as_held(flagfile):
    """Older hand-written flags were only ever written to hold."""
    flagfile.write_text(json.dumps({"note": "legacy"}), encoding="utf-8")
    assert safe_mode.is_on("submit")


def test_on_holds_both_actions_and_guard_reports_it(flagfile):
    safe_mode.set_mode(True, note="checking documents")
    assert safe_mode.is_on("submit") and safe_mode.is_on("email")
    assert safe_mode.guard("submit") is True          # True means HELD
    assert "held_safe_mode" in safe_mode.reason("submit")


def test_allow_list_exempts_named_actions(flagfile):
    safe_mode.set_mode(True, note="hold email only", allow=["submit"])
    assert not safe_mode.is_on("submit")
    assert safe_mode.is_on("email")


def test_off_then_on_round_trips(flagfile):
    safe_mode.set_mode(False, note="live")
    assert not safe_mode.is_on("submit")
    safe_mode.set_mode(True, note="held again")
    assert safe_mode.is_on("submit")
    safe_mode.set_mode(False, note="live again")
    assert not safe_mode.is_on("submit")


def test_env_var_can_force_the_hold_on(flagfile, monkeypatch):
    monkeypatch.setenv("KESTREL_SAFE_MODE", "1")
    importlib.reload(safe_mode)
    monkeypatch.setattr(safe_mode, "FLAG", str(flagfile))
    assert safe_mode.is_on("submit")
    importlib.reload(safe_mode)


def test_every_ats_adapter_is_covered_by_the_hold():
    """An adapter either submits through base.submit_and_confirm (which guards)
    or guards itself. Three of them did neither, and RUN_PIPELINE.md's claim
    that the hold "applies no matter which script runs" was simply untrue."""
    uncovered = []
    for name in sorted(os.listdir(ATS_DIR)):
        if not name.endswith(".py") or name in ("base.py", "__init__.py"):
            continue
        src = io.open(os.path.join(ATS_DIR, name), encoding="utf-8").read()
        via_base = "submit_and_confirm" in src
        guards_itself = re.search(r"safe_mode\.guard\s*\(", src)
        if not (via_base or guards_itself):
            uncovered.append(name)
    assert not uncovered, (
        "these adapters can submit without checking safe mode: "
        + ", ".join(uncovered))


def test_base_guards_before_submitting():
    src = io.open(os.path.join(ATS_DIR, "base.py"), encoding="utf-8").read()
    assert re.search(r"safe_mode\.guard\s*\(\s*[\"']submit[\"']\s*\)", src), \
        "base.submit_and_confirm must consult safe mode"
