"""qa_bank.py — Pattern-matched answers for LinkedIn Easy Apply custom
screening questions, built from the user's real profile facts.

Deliberately excludes EEO/identity questions (gender, race, veteran status,
disability, background-check consent) — those are left unanswered so the
apply flow reports "stuck" and gets flagged for manual review, same as the
existing CAPTCHA/login-required handling. Guessing on the user's behalf for
those isn't this bot's call to make.
"""
import re

# Order matters — more specific patterns must come before generic catch-alls.
# Each entry: (regex, kind, value)
#   kind "text"   -> fill() the associated input/textarea
#   kind "choice" -> pick a radio/select option whose text contains `value`
def build_qa_bank(profile: dict, company: str = "", role: str = "") -> list:
    return [
        (r'years?.*experience.*figma|figma.*years?.*experience', 'text',
         str(profile.get('years_figma', '2'))),
        (r'years?.*experience.*(graphic design|adobe)', 'text',
         str(profile.get('years_graphic_design', '3'))),
        (r'legally authorized|authorized to work|eligib(le|ility).*work', 'choice', 'Yes'),
        (r'require.*sponsorship|sponsorship.*require|visa sponsor|need.*sponsor', 'choice', 'No'),
        (r'work permit|status in canada|immigration status', 'text',
         profile.get('work_auth', '')),
        (r'willing to relocate|relocation', 'choice', 'No'),
        (r'salary|compensation|desired pay|expected pay|pay expectation', 'text',
         str(profile.get('salary_display', '65000'))),
        (r'when.*(can you )?start|start date|notice period|availability to start', 'text', 'Two weeks from offer acceptance'),
        (r'portfolio|link to your work|work samples', 'text',
         profile.get('portfolio', '')),
        (r'linkedin profile|linkedin url', 'text', profile.get('linkedin', '')),
        (r'current (company|employer)', 'text', profile.get('current_company', 'ExampleCo')),
        (r'current(ly)? locat(ed|ion)|city.*(reside|live)|where.*(based|located)', 'text',
         profile.get('location', '')),
        (r'18 years|of age|age requirement', 'choice', 'Yes'),
        (r'why.*(interested|want to join|apply|work (here|with us|for us))',
         'text',
         f"I'm drawn to {company or 'this team'}'s product work and think my UX background — "
         f"design systems, prototyping, and cross-functional collaboration — is a strong fit "
         f"for the {role or 'role'}."),
        (r'tell us about (yourself|your experience|your background)|describe your (experience|background)',
         'text',
         "I'm a UX Designer with a computer science foundation (MCA), currently designing "
         "products at ExampleCo. My background spans a UX internship running usability testing "
         "with real participants, 7 years of freelance visual and branding work, and ongoing "
         "design-system work as a volunteer. I bring both design craft and a technical grounding "
         "to product work."),
        (r'cover letter', 'text',
         f"I'm excited about the {role or 'role'} opportunity at {company or 'your company'} "
         f"and believe my UX background is a strong match — see attached cover letter for detail."),
        (r'years?.*(of )?experience', 'text', '2'),  # generic catch-all, keep last
    ]


# Patterns explicitly left unanswered — used only for logging/awareness, not matched against.
EXCLUDED_PATTERNS = [
    r'gender', r'race|ethnicity', r'veteran', r'disabilit', r'background check',
    r'criminal', r'pronoun',
]


def is_excluded(label_text: str) -> bool:
    tl = label_text.lower()
    return any(re.search(p, tl) for p in EXCLUDED_PATTERNS)


def match_answer(label_text: str, bank: list):
    tl = label_text.lower()
    for pattern, kind, value in bank:
        if re.search(pattern, tl):
            return kind, value
    return None, None
