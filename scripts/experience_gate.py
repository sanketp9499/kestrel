"""Read the experience a posting actually asks for.

The first attempt at fixing scan accuracy dropped every title containing
"Senior". That was wrong, and Sanket said so on 2026-09-13: he is not hunting
senior roles specifically, but if he is eligible then why not, and he wants
every design discipline in the net.

Titles are a bad proxy anyway. "Senior Product Designer" at a small startup can
ask for 3 years; "Product Designer" at a bank can ask for 8. The requirement is
written in the description, so read it there.

What this does NOT do is decide he cannot have the job. A stated requirement is
a wish, not a rule, and a 5-year ask with 2 years held is a stretch worth the
application. Only a genuinely unreachable number is refused, and the ceiling is
configurable. Everything else is kept and labelled so phase 3 can rank instead
of discard.
"""
import re

# 1-2 years of hands-on UX, per the master resume and the standing rule about
# never claiming 6+.
HAVE_YEARS = 2

# Where a stretch starts, and where the application stops being worth the
# Firecrawl and Claude calls it costs.
STRETCH_FROM = 4
HARD_CEILING = 9

_WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

# Only patterns where the number is bound to experience. A JD is full of other
# numbers - "founded 5 years ago", "4 year degree", "equity vests over 4 years" -
# and treating those as requirements would drop good postings.
_PATTERNS = [
    # "5+ years of X experience", "5-7 years of relevant experience"
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|to)?\s*\d{0,2}\s*(?:\+)?\s*"
    r"(?:years?|yrs?|ans)\b[^.;\n]{0,40}?"
    r"(?:experience|exp\b|expérience|experience|designing|design|working|in\s+\w+)",
    # "minimum 5 years", "at least 3 years", "minimum of 4 years"
    r"(?:minimum|min\.?|at least|au moins)\s+(?:of\s+)?(\d{1,2})\s*(?:\+)?\s*"
    r"(?:years?|yrs?|ans)",
    # "experience: 5+ years"
    r"(?:experience|expérience)[^.\n]{0,20}?(\d{1,2})\s*(?:\+)?\s*(?:years?|yrs?|ans)",
]

# Numbers that look like requirements but are not.
_NOT_A_REQUIREMENT = re.compile(
    r"(?:founded|established|since|ago|vest\w*|roadmap|degree|diploma|program"
    r"|warranty|contract|term|old|anniversary)", re.I)


def years_required(text: str):
    """Minimum years of experience the posting asks for, or None.

    None means the posting never said. That is the common case for good
    postings and must never be read as zero or used as a reason to drop.
    """
    if not text:
        return None
    t = str(text).lower().replace("–", "-").replace("—", "-")

    for word, n in _WORD_NUMBERS.items():
        t = re.sub(r"\b%s\s+(years?|yrs?)\b" % word, "%d \\1" % n, t)

    best = None
    for pattern in _PATTERNS:
        for m in re.finditer(pattern, t, re.I):
            window = t[max(0, m.start() - 60):m.end() + 40]
            if _NOT_A_REQUIREMENT.search(window):
                continue
            try:
                n = int(m.group(1))
            except (TypeError, ValueError):
                continue
            if not 1 <= n <= 30:
                continue
            # The lowest stated number is the real bar: "3 to 5 years" means 3,
            # and a JD listing several requirements is gated by the smallest.
            best = n if best is None else min(best, n)
    return best


def assess(text: str, have_years: int = HAVE_YEARS,
           stretch_from: int = STRETCH_FROM,
           hard_ceiling: int = HARD_CEILING) -> dict:
    """Keep/drop plus a band, for ranking rather than discarding.

    match      - at or near what he has
    stretch    - asks more than he has, still worth applying to
    out of band - unreachable; the only case that is dropped
    """
    years = years_required(text)
    if years is None:
        return {"years": None, "band": "unstated", "keep": True,
                "reason": "no stated requirement"}
    if years >= hard_ceiling:
        return {"years": years, "band": "out of band", "keep": False,
                "reason": f"asks {years}+ years, he has ~{have_years}"}
    if years >= stretch_from:
        return {"years": years, "band": "stretch", "keep": True,
                "reason": f"asks {years} years, he has ~{have_years} - stretch, worth applying"}
    return {"years": years, "band": "match", "keep": True,
            "reason": f"asks {years} years, he has ~{have_years}"}


if __name__ == "__main__":
    import argparse, io, json
    ap = argparse.ArgumentParser(description="Read a posting's experience requirement")
    ap.add_argument("--jd-file", required=True)
    ap.add_argument("--have", type=int, default=HAVE_YEARS)
    ap.add_argument("--ceiling", type=int, default=HARD_CEILING)
    args = ap.parse_args()
    jd = io.open(args.jd_file, encoding="utf-8", errors="replace").read()
    print(json.dumps(assess(jd, args.have, hard_ceiling=args.ceiling), indent=2))
