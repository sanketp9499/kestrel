"""The record phase 4 hands to phase 5.

`apply_url` is the URL the ATS adapter is actually driven against. It matters
when it differs from `url`: a LinkedIn or Wellfound listing whose Apply button
leaves for a Greenhouse form has a listing URL that no adapter can submit.

RUN_PIPELINE.md's phase 4 field list has never mentioned `apply_url`, so it is
a convention rather than a contract, and on 2026-09-12 it broke: all 18 phase 3
records and both prepared records carried `"apply_url": ""`. Nothing failed that
day only because that run's phase 5 script happened to read `j["url"]`. An
earlier generation of the same script, still on disk as `_phase5_run.py`, reads
`j["apply_url"]` and would have driven every adapter against an empty string.

Older artifacts (phase4_prepared_all.json) have it populated, which is what makes
this the dangerous kind of bug: it works until the day it silently doesn't.

So the shape is validated in code that both phases import.
"""
import io
import json
import os
import sys

import pytest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS)

from job_record import (PreparedRecordError, apply_url_for,  # noqa: E402
                        load_prepared, validate_prepared)


def _job(**over):
    job = {"company": "Palette", "title": "Senior Product Designer",
           "url": "https://wellfound.com/jobs/4095826-senior-product-designer",
           "apply_url": "https://boards.greenhouse.io/palette/jobs/1",
           "resume_pdf": "Applications/Palette/Palette_Resume.pdf",
           "cover_letter_path": "Applications/Palette/Palette_CL.docx",
           "folder": "Applications/Palette - Senior Product Designer",
           "ats_type": "GREENHOUSE", "custom_q_answers": {}}
    job.update(over)
    return job


def test_apply_url_wins_when_it_is_set():
    """The whole point of the field: the listing and the form are different
    pages."""
    assert apply_url_for(_job()) == "https://boards.greenhouse.io/palette/jobs/1"


def test_the_2026_09_12_record_falls_back_to_url():
    """Empty apply_url must degrade to the listing URL, not to an empty string."""
    assert apply_url_for(_job(apply_url="")) == _job()["url"]


def test_whitespace_only_counts_as_empty():
    assert apply_url_for(_job(apply_url="   ")) == _job()["url"]


def test_a_missing_key_is_not_a_crash():
    job = _job()
    del job["apply_url"]
    assert apply_url_for(job) == job["url"]


def test_no_url_at_all_is_an_error_not_an_empty_string():
    """Driving an adapter against "" is the failure this prevents."""
    with pytest.raises(PreparedRecordError):
        apply_url_for(_job(url="", apply_url=""))


def test_validate_accepts_a_good_record():
    assert validate_prepared([_job()]) == [_job()]


def test_validate_names_the_job_and_the_missing_field():
    job = _job()
    del job["resume_pdf"]
    with pytest.raises(PreparedRecordError) as e:
        validate_prepared([job])
    assert "resume_pdf" in str(e.value) and "Palette" in str(e.value)


def test_validate_reports_every_problem_at_once():
    """A run that stops at the first bad record wastes the whole day finding
    the second one."""
    bad1 = _job(company="One"); del bad1["folder"]
    bad2 = _job(company="Two"); del bad2["ats_type"]
    with pytest.raises(PreparedRecordError) as e:
        validate_prepared([bad1, bad2])
    assert "One" in str(e.value) and "Two" in str(e.value)


def test_validate_fills_apply_url_in_place():
    out = validate_prepared([_job(apply_url="")])
    assert out[0]["apply_url"] == _job()["url"]


def test_a_linkedin_record_may_omit_the_cover_letter():
    """LinkedIn Easy Apply takes no cover letter, so the adapter is not given
    one and phase 4 does not always write the path."""
    job = _job(ats_type="LINKEDIN")
    del job["cover_letter_path"]
    assert validate_prepared([job])[0]["ats_type"] == "LINKEDIN"


def test_load_prepared_reads_validates_and_normalises(tmp_path):
    p = tmp_path / "phase4_prepared.json"
    io.open(p, "w", encoding="utf-8").write(json.dumps([_job(apply_url="")]))
    jobs = load_prepared(str(p))
    assert jobs[0]["apply_url"] == _job()["url"]


def test_load_prepared_on_an_empty_queue_is_fine(tmp_path):
    """A day with nothing to apply to is a normal day, not an error."""
    p = tmp_path / "phase4_prepared.json"
    io.open(p, "w", encoding="utf-8").write("[]")
    assert load_prepared(str(p)) == []


def test_load_prepared_rejects_a_truncated_file(tmp_path):
    p = tmp_path / "phase4_prepared.json"
    io.open(p, "w", encoding="utf-8").write('[{"company": "Half')
    with pytest.raises(PreparedRecordError):
        load_prepared(str(p))


def test_the_runbook_documents_the_field():
    """The field existed only in generated code. If the spec does not name it,
    the next generated phase 4 leaves it empty again."""
    spec = io.open(os.path.join(SCRIPTS, "RUN_PIPELINE.md"), encoding="utf-8").read()
    assert "apply_url" in spec
