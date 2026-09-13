"""Judge a posting on what it asks for, not on the word in its title.

Dropping every "Senior" title was the wrong correction. Sanket's rule, stated
2026-09-13: he is not hunting senior roles specifically, but if he is eligible
then why not - and he wants every type of design role in the net, brand and
creative and graphic and learning design included.

A title is a poor proxy for eligibility anyway. "Senior Product Designer" at a
20-person startup can ask for 3 years; "Product Designer" at a bank can ask for
8. The number is in the description, so read the number.

So the title gate no longer drops seniors at all. This reads the stated
requirement instead, and only refuses the genuinely impossible. Every sentence
below is a real skip reason from Scripts/phase3_2026-09-12.json.
"""
import os
import sys

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS)

from experience_gate import assess, years_required  # noqa: E402


def test_the_real_skip_reasons_from_the_pipeline():
    cases = [
        ("6+ years of professional UX or Product Design experience required", 6),
        ("7+ years experience designing software across devices and surfaces.", 7),
        ("8+ years of product design experience, Staff level, hybrid Toronto", 8),
        ("5-7 years of relevant experience, senior title.", 5),
        ("Minimum 5 years relevant experience plus a bachelor's degree", 5),
        ("5+ years graphic design, 5+ years Adobe, and 5+ years website build", 5),
        ("7+ years of instructional design experience in private sectors.", 7),
        ("6+ years designing digital products, hybrid in Calgary", 6),
    ]
    for text, expected in cases:
        assert years_required(text) == expected, text


def test_other_ways_postings_phrase_it():
    assert years_required("At least 3 years of design experience") == 3
    assert years_required("Minimum of 4 years in product design") == 4
    assert years_required("2+ ans d'experience en design") == 2
    assert years_required("You have 3 to 5 years of experience") == 3
    assert years_required("Three years of experience required") == 3


def test_no_stated_requirement_is_not_a_requirement_of_zero():
    """Most good postings never name a number. That must not read as 0, and it
    must never be a reason to drop."""
    assert years_required("We want a designer who ships great work.") is None
    assert years_required("") is None
    assert assess("We want a designer who ships.")["keep"] is True


def test_numbers_that_are_not_experience_requirements():
    """The trap: a JD full of numbers about other things."""
    for text in ("Founded 5 years ago, we now serve 3 million users",
                 "Our 4 year roadmap includes 6 new products",
                 "A 4 year degree is required",
                 "Equity vests over 4 years"):
        assert years_required(text) is None, text


def test_a_role_in_his_band_is_a_match():
    r = assess("2+ years of product design experience")
    assert r["band"] == "match" and r["keep"] is True


def test_a_stretch_is_kept_and_labelled():
    """"If eligible, why not" - 5 years asked with 2 held is a stretch, not a
    no. It stays in, flagged, so phase 3 can rank rather than discard."""
    r = assess("5+ years of product design experience")
    assert r["keep"] is True
    assert r["band"] == "stretch"


def test_only_the_genuinely_impossible_is_dropped():
    r = assess("10+ years of design leadership experience")
    assert r["keep"] is False
    assert r["band"] == "out of band"
    assert "10" in r["reason"]


def test_the_ceiling_is_configurable():
    text = "8+ years of product design experience"
    assert assess(text, hard_ceiling=8)["keep"] is False
    assert assess(text, hard_ceiling=12)["keep"] is True


def test_seniors_are_no_longer_dropped_on_the_title_alone():
    """The correction. A senior title with a reachable requirement survives."""
    import apify_scraper
    jobs = [{"title": "Senior Product Designer", "location": "Toronto, ON",
             "snippet": "3+ years of design experience", "url": "u"}]
    assert len(apify_scraper.filter_roles(jobs)) == 1


def test_every_design_discipline_he_asked_for_survives_the_title_gate():
    import apify_scraper
    titles = ["Brand Designer", "Creative Designer", "Graphic Designer",
              "Instructional Designer", "Learning Experience Designer",
              "Digital Designer", "Senior UX Designer", "Lead Product Designer",
              "UX Designer", "Product Designer", "Interaction Designer"]
    jobs = [{"title": t, "location": "Toronto, ON", "snippet": "", "url": "u"}
            for t in titles]
    kept = [j["title"] for j in apify_scraper.filter_roles(jobs)]
    assert kept == titles, f"dropped: {set(titles) - set(kept)}"


def test_the_junk_is_still_dropped():
    """Widening the net must not reopen the leaks."""
    import apify_scraper
    for title in ("Mobile App Tester - User Experience & Feedback",
                  "Seasonal Sales Associate (McArthurGlen Designer Outlet)",
                  "Backend Engineer, Developer & End-user Experience Platform",
                  "Designer UX - Stage"):
        assert apify_scraper.filter_roles(
            [{"title": title, "location": "Toronto, ON", "snippet": "", "url": "u"}]
        ) == [], title
