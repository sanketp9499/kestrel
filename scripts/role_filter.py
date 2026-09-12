#!/usr/bin/env python3
"""role_filter.py — Is this posting a design job Sanket could actually take?

One gate, shared by every source, because the two that existed disagreed and
both leaked. The board sweep found Stripe's "Backend Engineer, Developer &
End-user Experience Platform" (the allowlist matched "user experience") and
Knix's "Seasonal Sales Associate (McArthurGlen Designer Outlet)" — a shopping
mall whose name contains "Designer".

So the gate is two-sided:

    allow   the title names the discipline: design/designer/UX/UI/researcher
    block   the title names a different job: engineer, developer, manager,
            analyst, sales, associate, counsel...

Allowlist alone lets a mall through. Blocklist alone cannot keep up with the
ways a title fails to be a design role. Both, and the block wins ties, because
a false positive costs a wasted application and a false negative costs one
posting out of thousands.

Seniority is reported, not enforced: `seniority()` says junior/mid/senior so a
caller can decide. A "Senior Product Designer" at a startup is often worth an
application; a "Director of Design" is not.
"""
import re

# The discipline has to be in the title. "Product" or "web" alone is not enough:
# matching those let a Senior Product Manager through on an earlier pass.
DESIGN = re.compile(
    r"(\bdesign(er|ers|ing)?\b"
    r"|\bux\b|\bui\b|\bux/ui\b|\bui/ux\b|\bux-ui\b|\bui-ux\b"
    r"|(?<!end-)(?<!end )user experience"      # not "End-user Experience"
    r"|user interface"
    r"|\bux research(er)?\b"
    r"|\bproduct design"
    r"|\bvisual design"
    r"|\binteraction design"
    r"|\bdesign system)",
    re.I)

# A title that names one of these is that job, whatever else it also says.
NOT_DESIGN = re.compile(
    r"\b("
    r"engineer|engineering|developer|dev\b|programmer|architect"
    r"|scientist|analyst|accountant|bookkeeper|counsel|lawyer|legal"
    r"|recruiter|sales|account executive|business development"
    # Bare "manager", not just the qualified ones: "Instructional Designer
    # Manager" and "UX Research Manager" both cleared a list that only knew
    # about product/program/project managers. These are people-management
    # roles, which is a different job from the one being applied for.
    r"|\bmanager\b"
    r"|product owner|\bowner\b|transformation|scrum master"
    r"|technical writer|copywriter"
    r"|cashier|associate|clerk|cook|driver|warehouse|merchandiser"
    # Retail floor titles. "Part-Time Key Lead (McArthurGlen Designer
    # Outlet)" cleared both lists: the mall's name supplied "Designer"
    # and nothing in the title named the actual job.
    r"|outlet|key lead|store|retail|stocker"
    r"|nurse|pharmac|technician|mechanic|installer"
    r"|teacher|instructor|professor|tutor"
    r"|intern(ship)?\b"
    r"|vice president|\bvp\b|chief|president|head of|director of"
    r")\b", re.I)

# Reported, never enforced here.
SENIOR = re.compile(r"\b(senior|sr\.?|staff|principal|lead|director|head)\b", re.I)
JUNIOR = re.compile(r"\b(junior|jr\.?|associate designer|entry[- ]level|graduate|intern)\b", re.I)

CANADA = re.compile(
    r"\b(canada|canadian|toronto|ontario|vancouver|british columbia|montreal|"
    r"quebec|calgary|alberta|ottawa|edmonton|waterloo|kitchener|mississauga|"
    r"hamilton|halifax|winnipeg|victoria|burnaby|richmond|markham|"
    r"on|bc|ab|qc|ns|mb|sk)\b", re.I)
# "Remote" with no country is usually US-only in practice; require a signal.
REMOTE_CA = re.compile(r"remote[^a-z]{0,12}(canada|ca\b|on\b|bc\b|ontario)", re.I)


def is_design_role(title):
    """True when the title names a design job and not some other job."""
    t = str(title or "")
    if not DESIGN.search(t):
        return False
    if NOT_DESIGN.search(t):
        return False
    return True


def seniority(title):
    t = str(title or "")
    if JUNIOR.search(t):
        return "junior"
    if SENIOR.search(t):
        return "senior"
    return "mid"


def in_canada(location):
    loc = str(location or "")
    if not loc:
        return False
    return bool(CANADA.search(loc) or REMOTE_CA.search(loc))


def verdict(title, location=None, require_canada=True):
    """(keep: bool, reason: str) — the reason is for logging a drop, never silently."""
    t = str(title or "").strip()
    if not t:
        return False, "no title"
    if not DESIGN.search(t):
        return False, "off-role"
    m = NOT_DESIGN.search(t)
    if m:
        return False, f"other discipline ({m.group(1).lower()})"
    if require_canada and not in_canada(location):
        return False, "not in Canada"
    return True, seniority(t)


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        keep, why = verdict(arg, "Toronto, ON")
        print(f"  {'KEEP' if keep else 'drop'}  {why:26} {arg}")
