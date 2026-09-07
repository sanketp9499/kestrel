#!/usr/bin/env python3
"""aiapply_overlap.py — Flag jobs at companies aiApply has already applied to.

the user runs aiApply's Auto Apply alongside this pipeline. aiApply submits a
generic resume under a proxy identity (you@proxy-mail.example.com) and knows
none of his positioning rules, so a second application from this pipeline can
land at a company that already has one from him.

This deliberately **flags rather than blocks**. Blocking would have skipped
an interviewing company, which aiApply sourced and which turned into a real interview. What
matters is that a duplicate is a decision Phase 3 makes on purpose, not an
accident nobody noticed until a recruiter saw two different stories.

Company list lives in aiapply_applied_companies.txt; refresh it by re-scraping
the Auto Apply table.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
COMPANIES_FILE = os.path.join(HERE, "aiapply_applied_companies.txt")

# Legal-form and region suffixes that differ between the two systems for the
# same employer: aiApply writes "Rakuten Kobo Inc.", the tracker writes "Kobo".
_SUFFIX = re.compile(
    r"\b(inc|llc|ltd|limited|corp|corporation|co|company|group|holdings|"
    r"technologies|technology|labs|lab|solutions|services|international|"
    r"canada|north america|plc|gmbh|pvt|private)\b", re.I)


def normalize(name: str) -> str:
    """Company name reduced to something two systems can agree on."""
    if not name:
        return ""
    n = re.split(r"\s*[/|]\s*", name.lower())[0]   # "Aldo Group Inc / Le Groupe Aldo"
    n = re.sub(r"\(.*?\)", " ", n)                  # "Global University Systems (GUS)"
    n = re.sub(r"[^a-z0-9&+ ]", " ", n)
    n = _SUFFIX.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def load_aiapply_companies(path: str = None) -> set:
    """Normalised company names aiApply has applied to. Empty set if absent."""
    path = path or COMPANIES_FILE
    if not os.path.exists(path):
        return set()
    names = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key = normalize(line)
            if key:
                names.add(key)
    return names


def mark_overlap(jobs: list, companies: set = None) -> int:
    """Set job["aiapply_overlap"] on every job whose company aiApply hit.

    Returns how many were flagged. Mutates the dicts in place.
    """
    companies = load_aiapply_companies() if companies is None else companies
    if not companies:
        for j in jobs:
            j["aiapply_overlap"] = False
        return 0
    hits = 0
    for j in jobs:
        overlap = normalize(j.get("company", "")) in companies
        j["aiapply_overlap"] = overlap
        hits += overlap
    return hits


if __name__ == "__main__":
    import argparse
    import json
    p = argparse.ArgumentParser()
    p.add_argument("--report", default="", help="a daily_report.json to check")
    args = p.parse_args()

    companies = load_aiapply_companies()
    print(f"{len(companies)} aiApply companies loaded from {COMPANIES_FILE}")
    if not args.report:
        raise SystemExit(0)

    with open(args.report, encoding="utf-8") as f:
        data = json.load(f)
    jobs = data.get("jobs", data) if isinstance(data, dict) else data
    hits = mark_overlap(jobs, companies)
    print(f"{hits} of {len(jobs)} jobs are at a company aiApply already applied to")
    for j in jobs:
        if j.get("aiapply_overlap"):
            print(f"  OVERLAP  {j.get('company')} - {j.get('title')}")
