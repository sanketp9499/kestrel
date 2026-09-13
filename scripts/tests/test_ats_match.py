"""Does the tailored resume actually cover the posting's language?

Nothing in the pipeline asked this before. `daily_auto_apply.relevance_score()`
scores the JOB against a fixed list of words Sanket cares about - it never looks
at the resume. `tailor_resume.py` pastes up to five keywords into the summary
paragraph and never checks whether the result covers what the posting asked for.

So a posting could demand design systems, prototyping and accessibility, the
resume could mention none of them, and the pipeline would submit it with no
signal that anything was wrong. Every ATS keyword filter on the other end is
doing exactly this comparison.

Borrowed from mayankjoshii/claude-job-skill, which gates on >= 70% JD keyword
overlap and rewrites until it passes. The gate is the valuable part; the number
is a starting threshold, not a law.
"""
import os
import sys

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS)

from ats_match import coverage, extract_keywords, gate  # noqa: E402

JD = """
Senior Product Designer

We are looking for a product designer to own end-to-end design of our web app.
You will run usability testing, build and maintain our design system in Figma,
create interactive prototypes, and work closely with engineers on accessibility
and responsive layouts. Experience with user research and wireframing required.
Nice to have: motion design, design tokens.

About us: we are a fast-paced team that values collaboration and ownership.
Equal opportunity employer. We offer competitive salary and benefits.
"""

STRONG_RESUME = """
Sanket Pawar - UX Designer
Skilled in the full UX process: discovery user research, usability testing,
wireframing, interaction design, interactive prototypes, and design systems in
Figma. Built design tokens and accessibility-compliant responsive layouts.
Collaborated with engineers across product teams.
"""

WEAK_RESUME = """
Sanket Pawar - Graphic Designer
Made posters, brochures and social media graphics in Photoshop and Illustrator.
Worked on brand identity and print production for local clients.
"""


def test_it_pulls_the_skills_out_of_the_posting():
    kws = extract_keywords(JD)
    # Singular stems: "prototype" and "prototypes" are one keyword, not two, so
    # a posting that says both cannot count it twice.
    for expected in ("figma", "usability testing", "design system", "prototype",
                     "accessibility", "user research", "wireframing"):
        assert any(expected in k for k in kws), f"{expected} not in {kws}"


def test_boilerplate_is_not_a_keyword():
    """"Equal opportunity employer" is in every posting and means nothing."""
    kws = " ".join(extract_keywords(JD))
    for junk in ("equal opportunity", "competitive salary", "fast-paced",
                 "benefits", "about us"):
        assert junk not in kws, junk


def test_the_company_name_is_not_a_keyword():
    """Scored against the real folders, the top misses included "crakmedia",
    "altaml", "asana" and "palette". No resume should contain the employer's
    name, so counting it only drags every score down by a fixed amount."""
    kws = extract_keywords("Palette is hiring. At Palette you will design.",
                           company="Palette")
    assert not any("palette" in k for k in kws), kws


def test_filler_words_are_not_keywords():
    """Also from the real run: "about", "make", "someone", "everyone", "clear",
    "real", "environment", "benefits". None of them is a skill."""
    jd = ("About us: we want someone who will make everyone's day clear and real. "
          "About the environment, about benefits, about someone real. "
          "You'll love it here, we're great.")
    kws = " ".join(extract_keywords(jd))
    for junk in ("about", "someone", "everyone", "make", "clear", "real",
                 "environment", "benefits", "we're", "you'll"):
        assert junk not in kws, f"{junk} in {kws}"


def test_a_non_english_posting_does_not_invent_keywords():
    """Crakmedia's posting is French and scored 0.28, with "nous", "pour" and
    "avoir" reported as missing skills. A resume in English cannot match those,
    so the number was meaningless."""
    fr = ("Nous recherchons un designer web pour rejoindre notre equipe. "
          "Vous devez avoir de l'experience avec nous et pour nous. "
          "Nous offrons des avantages pour vous.")
    kws = " ".join(extract_keywords(fr))
    for word in ("nous", "pour", "avoir", "vous"):
        assert word not in kws, f"{word} in {kws}"


def test_accents_are_folded_not_stripped():
    """Stripping the accent from "équipe" left "quipe", which matched no filter
    and was reported as a missing skill."""
    kws = " ".join(extract_keywords(
        "Notre équipe recherche. L'équipe est une équipe. Une équipe équipe."))
    assert "quipe" not in kws, kws


def test_common_verbs_and_hedges_are_not_skills():
    """Residue from the second real-folder run: rather, bring, whether, being,
    believe, learn, first."""
    jd = ("We believe you will learn. We believe, we believe. Rather than being "
          "first, bring whether you learn. Learn, learn, bring, bring, rather, "
          "rather, whether, whether, being, being, first, first.")
    kws = " ".join(extract_keywords(jd))
    for junk in ("rather", "bring", "whether", "being", "believe", "learn", "first"):
        assert junk not in kws, f"{junk} in {kws}"


def test_real_skills_still_survive_the_tightening():
    """The filters must not be so aggressive that the gate stops working."""
    kws = extract_keywords(JD, company="Acme")
    assert len(kws) >= 8, kws
    for expected in ("figma", "design system", "usability testing", "accessibility"):
        assert any(expected in k for k in kws), f"{expected} not in {kws}"


def test_a_matching_resume_scores_high():
    result = coverage(JD, STRONG_RESUME)
    assert result["score"] >= 0.70, result


def test_a_mismatched_resume_scores_low():
    result = coverage(JD, WEAK_RESUME)
    assert result["score"] < 0.40, result


def test_it_names_what_is_missing_so_it_can_be_fixed():
    """A score alone is useless - phase 4 needs to know which words to add."""
    result = coverage(JD, WEAK_RESUME)
    assert "figma" in " ".join(result["missing"])
    assert result["missing"], "no missing keywords reported"


def test_matched_and_missing_account_for_every_keyword():
    result = coverage(JD, STRONG_RESUME)
    assert len(result["matched"]) + len(result["missing"]) == len(result["keywords"])


def test_plurals_and_case_do_not_count_as_misses():
    result = coverage("We need strong prototypes and design systems.",
                      "I build prototype flows and a Design System.")
    assert result["missing"] == [], result


def test_the_gate_blocks_below_threshold_and_says_why():
    ok, result = gate(JD, WEAK_RESUME, threshold=0.70)
    assert ok is False
    assert result["score"] < 0.70
    assert result["missing"]


def test_the_gate_passes_a_good_match():
    ok, _ = gate(JD, STRONG_RESUME, threshold=0.70)
    assert ok is True


def test_an_empty_jd_does_not_crash_or_fail_a_resume():
    """Phase 2 sometimes cannot extract a JD. Scoring nothing must not block the
    application - that would turn a scraping failure into a lost job."""
    ok, result = gate("", STRONG_RESUME)
    assert ok is True
    assert result["score"] == 1.0
    assert result["keywords"] == []


def test_an_empty_resume_fails_loudly():
    ok, result = gate(JD, "")
    assert ok is False
    assert result["score"] == 0.0
