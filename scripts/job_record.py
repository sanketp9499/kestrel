"""The prepared-job record that phase 4 writes and phase 5 drives adapters with.

Phase 5's runner is regenerated from RUN_PIPELINE.md on every run, so any field
convention that lives only in generated code drifts. `apply_url` did exactly
that: the runbook's phase 4 field list never named it, generations disagreed
about whether to write it, and on 2026-09-12 every record carried
`"apply_url": ""`. That run survived only because its script read `url`
instead; the previous generation, `_phase5_run.py`, reads `apply_url` and would
have driven every adapter against an empty string.

Both phases import this module rather than restating the shape.
"""
import io
import json
import os

# Fields phase 5 cannot work without.
REQUIRED = ("company", "title", "url", "resume_pdf", "folder", "ats_type")

# Required unless the ATS has no cover letter field. LinkedIn Easy Apply does
# not, so phase 4 legitimately omits the path for it.
REQUIRED_UNLESS_LINKEDIN = ("cover_letter_path",)

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "phase4_prepared.json")


class PreparedRecordError(Exception):
    """A prepared record cannot be applied with. Raised with every problem in
    the batch, not just the first: a run that dies on record 1 and again on
    record 2 has burned a day to find two typos."""


def apply_url_for(job: dict) -> str:
    """The URL an adapter should actually be pointed at.

    `apply_url` when the Apply button leaves the listing site (a Wellfound or
    LinkedIn post whose form lives on Greenhouse), otherwise the listing URL.
    Never returns an empty string.
    """
    target = (job.get("apply_url") or "").strip() or (job.get("url") or "").strip()
    if not target:
        raise PreparedRecordError(
            f"{job.get('company') or '<unnamed job>'}: neither apply_url nor url is set, "
            "so there is nothing to submit to")
    return target


def validate_prepared(jobs: list) -> list:
    """Check every record and fill `apply_url` where phase 4 left it blank.

    Returns the same list, normalised in place.
    """
    problems = []
    for i, job in enumerate(jobs):
        who = job.get("company") or f"record {i}"
        missing = [f for f in REQUIRED if not str(job.get(f) or "").strip()]
        if (job.get("ats_type") or "").upper() != "LINKEDIN":
            missing += [f for f in REQUIRED_UNLESS_LINKEDIN
                        if not str(job.get(f) or "").strip()]
        if missing:
            problems.append(f"{who}: missing {', '.join(missing)}")
            continue
        try:
            job["apply_url"] = apply_url_for(job)
        except PreparedRecordError as e:
            problems.append(str(e))
    if problems:
        raise PreparedRecordError("; ".join(problems))
    return jobs


def load_prepared(path: str = DEFAULT_PATH) -> list:
    """Read phase4_prepared.json, validate it, and return applyable records."""
    try:
        jobs = json.load(io.open(path, encoding="utf-8"))
    except FileNotFoundError:
        raise PreparedRecordError(f"{path} does not exist - phase 4 did not run")
    except ValueError as e:
        raise PreparedRecordError(f"{path} is not readable JSON: {e}")
    if not isinstance(jobs, list):
        raise PreparedRecordError(f"{path} must hold a list of jobs, got {type(jobs).__name__}")
    return validate_prepared(jobs)
