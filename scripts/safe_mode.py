#!/usr/bin/env python3
"""safe_mode.py — One switch that stops Kestrel acting on the outside world.

While safe mode is on, the pipeline still does everything it normally does:
discovers jobs, reads descriptions, scores them, and writes tailored resumes,
cover letters and cold emails to disk. What it will not do is press send.

Two things are held:

    submit   clicking submit on any employer application form
    email    sending any outbound mail (cold emails, the daily summary)

The check lives at the lowest choke point in each path - the submit click in
ats/base.py and the SMTP call sites - rather than in the runbook, so it holds
no matter which script or which phase is running, including a run started by
hand. A held action is logged and reported as `held_safe_mode`, never as a
failure and never as an application.

Turn it off only after the tailored documents have been reviewed:

    python Scripts/safe_mode.py --off
    python Scripts/safe_mode.py --status
    python Scripts/safe_mode.py --on --note "why"

The flag file wins over the environment. KESTREL_SAFE_MODE=0 in the environment
is honoured only when no flag file exists, so a stray shell variable cannot
quietly re-enable sending.
"""
import argparse
import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FLAG = os.path.join(HERE, "SAFE_MODE.json")

HELD = ("submit", "email")


class SafeModeHold(Exception):
    """Raised when an outward action is attempted while safe mode is on."""


def state():
    """Current safe-mode state as a dict.

    "Off" is a recorded decision, not an absent file. It used to be the absence
    of SAFE_MODE.json, and on 2026-09-12 that cost a whole run: safe mode was
    turned off deliberately, the 08:00 pipeline found no flag file, could not
    tell "switched off on purpose" from "safety file lost", correctly failed
    closed, restored the hold from its last known value, and submitted nothing.

    It was right to be suspicious. Absence is not consent. So absence stays
    fail-closed, and a deliberate off writes a file that says so, with who and
    when, which nothing is entitled to overwrite on a guess.
    """
    if os.path.exists(FLAG):
        try:
            with open(FLAG, encoding="utf-8") as f:
                data = json.load(f)
            # No `on` key at all means an older or hand-written file. Those were
            # only ever written to hold, so read them as held.
            data.setdefault("on", True)
            return data
        except (OSError, ValueError):
            # An unreadable flag file must fail closed: assume held.
            return {"on": True, "note": "SAFE_MODE.json unreadable - failing closed"}

    env = os.environ.get("KESTREL_SAFE_MODE", "").strip().lower()
    if env in ("1", "true", "on", "yes"):
        return {"on": True, "note": "KESTREL_SAFE_MODE env var"}

    # No file and no env var: never configured on this machine. Fail closed and
    # say why, so a caller that restores the hold is not guessing either.
    return {"on": True, "unset": True,
            "note": "no SAFE_MODE.json found - failing closed. Run "
                    "`python Scripts/safe_mode.py --off` to record a "
                    "deliberate off."}


def is_on(action: str = "") -> bool:
    s = state()
    if not s.get("on"):
        return False
    allow = s.get("allow") or []
    return action not in allow


def reason(action: str = "") -> str:
    s = state()
    note = s.get("note") or "safe mode is on"
    since = (s.get("since") or "")[:16]
    return f"held_safe_mode: {action or 'action'} blocked - {note}" + (f" (since {since})" if since else "")


def guard(action: str, *, raise_on_hold: bool = False) -> bool:
    """True when the action is held. Logs once so the hold is never silent."""
    if not is_on(action):
        return False
    msg = reason(action)
    try:
        from daily_log import log
        log(f"  {msg}")
    except Exception:
        print(f"  {msg}")
    if raise_on_hold:
        raise SafeModeHold(msg)
    return True


def _write(data):
    tmp = FLAG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, FLAG)
    return data


def set_mode(on: bool, note: str = "", allow=None):
    """Record the decision. Turning off writes a file; it does not delete one.

    Deleting was the bug: it made a deliberate "off" look exactly like a lost
    safety file, so the next run restored the hold and nothing was submitted.
    """
    now = datetime.datetime.now().isoformat(timespec="seconds")
    if not on:
        return _write({
            "on": False,
            "note": note or "turned off by request",
            "since": now,
            "held": [],
            "allow": [],
            "warning": "Submissions and outbound email are LIVE. This file "
                       "records a deliberate decision - do not delete it to "
                       "re-enable the hold, run `safe_mode.py --on` instead.",
        })
    return _write({"on": True, "note": note or "held by request", "since": now,
                   "held": list(HELD), "allow": list(allow or [])})


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--on", action="store_true", help="hold submissions and outbound email")
    g.add_argument("--off", action="store_true", help="allow them again")
    g.add_argument("--status", action="store_true")
    p.add_argument("--note", default="")
    p.add_argument("--allow", nargs="*", default=None,
                   help=f"actions to keep allowed while on (of {', '.join(HELD)})")
    args = p.parse_args()

    if args.off:
        # Pass the note through. Now that off is a recorded state rather than a
        # deleted file, why it is live is the only audit trail there is.
        set_mode(False, args.note)
        print("SAFE MODE OFF - Kestrel may submit applications and send email again.")
        return
    if args.on:
        d = set_mode(True, args.note, args.allow)
        print(f"SAFE MODE ON - holding: {', '.join(a for a in HELD if a not in d['allow'])}")
        if d["allow"]:
            print(f"  still allowed: {', '.join(d['allow'])}")
        print(f"  reason: {d['note']}")
        return

    s = state()
    if not s.get("on"):
        print("SAFE MODE OFF - submissions and outbound email are live.")
    else:
        held = [a for a in HELD if a not in (s.get("allow") or [])]
        print(f"SAFE MODE ON since {(s.get('since') or '?')[:16]}")
        print(f"  holding: {', '.join(held)}")
        print(f"  reason:  {s.get('note')}")
        print("  documents are still written; nothing is sent.")


if __name__ == "__main__":
    main()
