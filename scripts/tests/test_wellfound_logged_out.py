"""Wellfound's logged-out detector.

On 2026-09-12 the pipeline reached Palette's posting, failed to notice it was
signed out, opened the apply flow and clicked submit on a page it had no
session for. The run reported it and deliberately did not fix it.

Verified against the live page that day: the detector's five markers
("log in to wellfound", "sign up to apply", ...) matched NOTHING. What the page
actually renders is a nav with two buttons whose text is exactly "Log In" and
"Sign Up".

The tempting fix - add "log in" to the substring list - is the same bug as the
role filter's "user experience" leak: a scan of whole-body text matches any job
description that says "users log in to the dashboard". So the signal is the
auth control as an element, not a word anywhere on the page.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ats.wellfound import is_logged_out_from  # noqa: E402


def test_the_real_page_that_fooled_it():
    """Exactly what wellfound.com rendered for the Palette posting."""
    assert is_logged_out_from(["Log In", "Sign Up"]) is True


def test_variants_of_the_same_control():
    for txt in ("Log In", "log in", "Login", "Sign Up", "signup",
                "Sign In", "Register", "Join now"):
        assert is_logged_out_from([txt]) is True, txt


def test_a_signed_in_page_has_no_auth_controls():
    assert is_logged_out_from([]) is False
    assert is_logged_out_from(["Apply Now", "Save", "Message"]) is False


def test_an_account_menu_settles_it_even_if_a_control_looks_like_auth():
    """Some layouts keep a "Sign in" affordance in a footer. A visible account
    menu is positive proof of a session and outranks it."""
    assert is_logged_out_from(["Sign In"], has_account_menu=True) is False


def test_a_job_description_mentioning_login_does_not_trigger_it():
    """The whole reason this matches elements and not body text: these are the
    kinds of phrases that appear in a real posting."""
    for phrase in ("Users log in to the dashboard daily",
                   "Design the sign up flow",
                   "Improve login conversion",
                   "single sign-on experience"):
        assert is_logged_out_from([phrase]) is False, phrase


def test_partial_matches_inside_a_longer_control_do_not_count():
    assert is_logged_out_from(["Log in to see salary details"]) is False
    assert is_logged_out_from(["Sign up for job alerts"]) is False


def test_none_and_empty_are_safe():
    assert is_logged_out_from([None, "", "   "]) is False
