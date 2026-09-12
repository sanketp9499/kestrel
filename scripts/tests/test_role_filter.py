"""Tests for the shared role gate.

Every case here is a real title the pipeline actually saw. The leaks at the top
are the ones that got through an earlier allowlist-only gate and would have
cost a wasted application each.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from role_filter import in_canada, is_design_role, seniority, verdict  # noqa: E402


def test_the_leaks_that_motivated_this_file():
    # matched because the allowlist contained "user experience"
    assert not is_design_role("Backend Engineer, Developer & End-user Experience Platform")
    # a shopping mall called McArthurGlen Designer Outlet
    assert not is_design_role("Seasonal Sales Associate (McArthurGlen Designer Outlet)")
    assert not is_design_role("Part-Time Key Lead (McArthurGlen Designer Outlet)")
    # "Design" present, but the job is transformation ownership
    assert not is_design_role("AI Transformation Owner, Product & Design")
    # people-management roles an earlier blocklist missed
    assert not is_design_role("Instructional Designer Manager")
    assert not is_design_role("UX Research Manager, Payments")


def test_real_design_roles_are_kept():
    for t in ("Product Designer",
              "UX Designer III",
              "Intermediate UX Designer",
              "Technical UI/UX Designer (5-month contract)",
              "Motion & Graphic Designer (Remote Canada)",
              "Instructional Designer",
              "Brand Designer",
              "Web Designer (UX-UI Focus)",
              "Learning Designer - 12 Month Contract",
              "Sr. UX/UI Designer",
              "Product Designer, Design Systems"):
        assert is_design_role(t), t


def test_other_disciplines_are_rejected():
    for t in ("Senior Product Manager - Createspace",
              "Chief Technical Officer",
              "Product Marketing Manager",
              "Full Stack Engineer II",
              "Frontend Engineer",
              "Technical Writer II",
              "Client Success Coach (CSM)",
              "Social Media & Content Creator",
              "Design Engineer, Presence"):
        assert not is_design_role(t), t


def test_seniority_is_reported_not_enforced():
    assert seniority("Senior Product Designer") == "senior"
    assert seniority("Sr. UX/UI Designer") == "senior"
    assert seniority("Staff Product Designer") == "senior"
    assert seniority("Junior UX Designer") == "junior"
    assert seniority("Product Designer") == "mid"
    # still a design role - the caller decides whether to apply
    assert is_design_role("Senior Product Designer")


def test_canada_detection():
    for loc in ("Toronto, ON", "Vancouver, BC, Canada", "Remote - Canada",
                "Calgary", "Montreal, QC", "Oakville, Ontario - Canada",
                "Miami, New York City, Sarasota, Toronto (ON), Washington DC"):
        assert in_canada(loc), loc
    for loc in ("San Francisco, CA", "Remote - United States", "London, UK", ""):
        assert not in_canada(loc), loc


def test_verdict_reports_why_it_dropped():
    # "off-role" when the title never names the discipline at all - the
    # allowlist rejects it before the blocklist is consulted.
    keep, why = verdict("Full Stack Engineer II", "Toronto, ON")
    assert not keep and why == "off-role"
    # "other discipline" when it does name design AND another job.
    keep, why = verdict("Design Engineer, Presence", "Toronto, ON")
    assert not keep and "engineer" in why
    keep, why = verdict("Product Designer", "San Francisco, CA")
    assert not keep and why == "not in Canada"
    keep, why = verdict("Chief Technical Officer", "Toronto, ON")
    assert not keep
    keep, why = verdict("Product Designer", "Toronto, ON")
    assert keep and why == "mid"
    keep, why = verdict("", "Toronto, ON")
    assert not keep and why == "no title"


def test_canada_can_be_waived():
    keep, why = verdict("Product Designer", "Remote - United States",
                        require_canada=False)
    assert keep and why == "mid"
