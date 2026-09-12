"""Tests for ats_resolver's pure parts. No network: the network behaviour that
actually bit us (Workable answering 200 without a jobs key) is covered by
driving the count function directly.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ats_resolver import (BOARDS, UNSUBMITTABLE, _fresh, from_url,  # noqa: E402
                          key, slug_variants)


def test_from_url_reads_the_slug_out_of_each_board():
    cases = [
        ("https://jobs.lever.co/fullscript/fea251e7-fd41", ("lever", "fullscript")),
        ("https://boards.greenhouse.io/asana/jobs/123", ("greenhouse", "asana")),
        ("https://job-boards.greenhouse.io/evismart/jobs/466", ("greenhouse", "evismart")),
        ("https://jobs.ashbyhq.com/absorblms/616c9441", ("ashby", "absorblms")),
        ("https://apply.workable.com/thisisgain/j/5BDA426955/", ("workable", "thisisgain")),
    ]
    for url, expected in cases:
        assert from_url(url) == expected, url


def test_from_url_returns_none_for_a_front_door():
    assert from_url("https://careers.loblaw.ca/front-end-developer/job/PAF-LCL-0B93") is None
    assert from_url("https://www.linkedin.com/jobs/view/4119085346") is None
    assert from_url("") is None
    assert from_url(None) is None


def test_unsubmittable_covers_the_surfaces_we_refuse_to_drive():
    for url in ("https://www.jobbank.gc.ca/jobsearch/jobposting/123",
                "https://www.linkedin.com/jobs/view/41190",
                "https://ca.indeed.com/viewjob?jk=abc",
                "https://loblaw.wd3.myworkdayjobs.com/LCLCareers/job/x"):
        assert UNSUBMITTABLE.search(url), url
    assert not UNSUBMITTABLE.search("https://jobs.lever.co/fullscript/abc")


def test_slug_variants_strips_legal_noise_and_keeps_order():
    v = slug_variants("Absorb Software Inc.")
    assert "absorb" in v
    assert v[0] == "absorb"          # noise-stripped, joined, tried first
    v2 = slug_variants("Irth Solutions")
    assert "irth-solutions" in v2 or "irth" in v2
    assert slug_variants("") == []
    assert slug_variants(None) == []


def test_slug_variants_are_unique_and_bounded():
    v = slug_variants("The Canada Technology Technologies Group Company Ltd")
    assert len(v) == len(set(v))
    assert len(v) <= 6


def test_key_normalises_punctuation_and_case():
    """Cache key only. It must not fold two different companies together, so
    "Owner.com" and "Owner" stay distinct; matching them is slug_variants' job."""
    assert key("Vitalist Inc. (VITA - TSXV)") == key("vitalistincvitatsxv")
    assert key("  ASANA  ") == key("asana") == "asana"
    assert key("Owner.com") == "ownercom"
    assert key("Owner.com") != key("Owner")
    assert key(None) == "" and key("") == ""


def test_workable_count_rejects_a_payload_with_no_jobs_key():
    """The false-positive bug: a 200 with no jobs list is not an empty board."""
    count = BOARDS["workable"]["count"]
    assert count({"jobs": []}) == 0          # a real, empty board
    assert count({"jobs": [1, 2]}) == 2
    assert count({"error": "rate limited"}) is None
    assert count({}) is None
    assert count([]) is None


def test_other_boards_count_their_own_shapes():
    assert BOARDS["greenhouse"]["count"]({"jobs": [1, 2, 3]}) == 3
    assert BOARDS["lever"]["count"]([1, 2]) == 2
    assert BOARDS["lever"]["count"]({}) == 0
    assert BOARDS["ashby"]["count"]({"jobs": [1]}) == 1


def test_fresh_uses_a_shorter_ttl_for_misses():
    now = datetime.datetime.now()
    recent = (now - datetime.timedelta(days=3)).isoformat(timespec="seconds")
    old = (now - datetime.timedelta(days=14)).isoformat(timespec="seconds")

    assert _fresh({"ats": "greenhouse", "checked": recent})
    assert _fresh({"ats": "greenhouse", "checked": old})      # hits keep 30 days
    assert _fresh({"ats": None, "checked": recent})           # misses keep 7
    assert not _fresh({"ats": None, "checked": old})          # so this retries
    assert not _fresh({"ats": None})
    assert not _fresh({"ats": None, "checked": "not-a-date"})
