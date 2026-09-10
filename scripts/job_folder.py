#!/usr/bin/env python3
"""job_folder.py — One writer for application folders and their Job_Details.md.

Job_Details.md is the only record of where a job posting actually lives. The
tracker is rebuilt from it, the Command Center's Open button reads it, and the
apply engine needs the URL. It was never written by shared code: Phase 4 of
RUN_PIPELINE.md improvised a script each run, so 55 of 189 folders ended up with
no Job_Details.md at all — including six of the nine CAPTCHA-blocked ones, whose
whole purpose is to send a human to a posting that nothing recorded.

So folder creation and the details file are the same operation here. You cannot
call one without the other.

Two rules the format follows:

* **Merge, never clobber.** Rewriting must keep a hand-written body and any
  field this call has no value for. A status change should not cost you the JD
  summary somebody typed.
* **One shape.** A markdown field table, because build_tracker.field() reads it
  and because a table survives round-tripping in a way that scattered
  `**Field:**` lines do not. Existing bold-line files are read fine and are
  converted on the next write.

Usage:
    from job_folder import ensure, write_details, FIELDS
    folder = ensure("Acme", "UX Designer", url="https://...", salary="$70k")

    python Scripts/job_folder.py --company Acme --role "UX Designer" \\
        --url https://... --status "Not Applied"
"""
import argparse
import datetime
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("KESTREL_WORKSPACE") or os.path.dirname(HERE)
APPS = os.path.join(ROOT, "Applications")

# Order is the order they are written. Company and Role always come first so a
# half-filled file still says what it is about.
FIELDS = [
    "Company", "Role", "Status", "Location", "Work Mode", "Pay",
    "Posted", "Discovered", "Applied", "Source", "ATS",
    "URL", "Apply URL", "Priority", "CL angle", "Keywords",
]

TABLE_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*$", re.M)
BOLD_LINE = re.compile(r"^\s*\*\*([A-Za-z ()/]+):\*\*\s*(.*)$", re.M)
EMPTYISH = {"", "n/a", "na", "none", "-", "tbd", "unknown"}


def folder_name(company, role, status=None, applied=None):
    """The folder name the rest of the system expects.

    Status lives in the folder name because that is what the board reads and
    what a rename moves. Kept here so every caller spells it the same way.
    """
    base = f"{company} - {role}".strip(" -")
    base = re.sub(r'[<>:"/\\|?*]', "", base).strip()
    s = (status or "").lower()
    if "captcha" in s:
        return f"{base} (CAPTCHA Pending)"
    if "applied" in s and "not" not in s:
        when = applied or datetime.date.today().strftime("%b %d %Y")
        return f"{base} (Applied {when})"
    return base


def parse(path_or_text):
    """Read an existing Job_Details.md into (fields, body).

    Accepts both shapes this project has produced: the field table and the
    `**Field:** value` lines. Anything that is neither is the body and is
    handed back untouched.
    """
    if os.path.exists(str(path_or_text)):
        text = io.open(path_or_text, encoding="utf-8", errors="replace").read()
    else:
        text = path_or_text or ""

    fields = {}
    for m in TABLE_ROW.finditer(text):
        k, v = m.group(1).strip(), m.group(2).strip()
        if k.lower() in ("field", "---") or set(k) <= set("-: "):
            continue
        if v.lower() not in EMPTYISH:
            fields[k] = v
    for m in BOLD_LINE.finditer(text):
        k, v = m.group(1).strip(), m.group(2).strip()
        if v.lower() not in EMPTYISH:
            fields.setdefault(k, v)

    body = TABLE_ROW.sub("", text)
    body = BOLD_LINE.sub("", body)
    body = re.sub(r"^#\s*Job Details.*$", "", body, flags=re.M)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return fields, body


def render(fields, body=""):
    company = fields.get("Company", "")
    out = [f"# Job Details — {company}".rstrip(" —"), "",
           "| Field | Value |", "|---|---|"]
    for k in FIELDS:
        v = str(fields.get(k, "") or "").strip()
        out.append(f"| {k} | {v} |")
    # Anything the caller passed that is not a known field still gets written:
    # losing a value because this list is out of date would be the same bug in
    # a new coat.
    for k, v in fields.items():
        if k not in FIELDS and str(v).strip():
            out.append(f"| {k} | {str(v).strip()} |")
    if body:
        out += ["", body.strip(), ""]
    return "\n".join(out).rstrip() + "\n"


def write_details(folder, **fields):
    """Write Job_Details.md into *folder*, merging over whatever is there.

    Values that are empty are dropped rather than written as blanks, so a caller
    that knows nothing about salary cannot erase a salary somebody recorded.
    """
    path = os.path.join(folder, "Job_Details.md")
    existing, body = parse(path)
    for k, v in fields.items():
        key = k.replace("_", " ").title() if k.islower() else k
        key = {"Url": "URL", "Apply Url": "Apply URL", "Cl Angle": "CL angle",
               "Ats": "ATS"}.get(key, key)
        if v is None:
            continue
        v = str(v).strip()
        if v and v.lower() not in EMPTYISH:
            existing[key] = v
    existing.setdefault("Discovered", datetime.date.today().isoformat())
    os.makedirs(folder, exist_ok=True)
    io.open(path, "w", encoding="utf-8", newline="").write(render(existing, body))
    return path


def ensure(company, role, status=None, applied=None, folder=None, **fields):
    """Create the application folder and its Job_Details.md in one call.

    This is the entry point Phase 4 should use. Creating a folder without the
    details file is what produced 55 folders the dashboard cannot open, so the
    two are deliberately not separable here.
    """
    name = folder or folder_name(company, role, status, applied)
    path = name if os.path.isabs(name) else os.path.join(APPS, name)
    os.makedirs(path, exist_ok=True)
    write_details(path, Company=company, Role=role,
                  Status=status or "Not Applied", Applied=applied, **fields)
    return path


def missing(apps_dir=APPS):
    """Folders with no Job_Details.md. The check Phase 4 has to pass."""
    out = []
    if not os.path.isdir(apps_dir):
        return out
    for d in sorted(os.listdir(apps_dir)):
        p = os.path.join(apps_dir, d)
        if os.path.isdir(p) and not d.startswith("_") \
                and not os.path.exists(os.path.join(p, "Job_Details.md")):
            out.append(d)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--company")
    ap.add_argument("--role")
    ap.add_argument("--status")
    ap.add_argument("--applied")
    ap.add_argument("--folder", help="Existing folder to write into")
    ap.add_argument("--url")
    ap.add_argument("--apply-url", dest="apply_url")
    ap.add_argument("--location")
    ap.add_argument("--mode", dest="work_mode")
    ap.add_argument("--pay")
    ap.add_argument("--posted")
    ap.add_argument("--source")
    ap.add_argument("--ats")
    ap.add_argument("--priority")
    ap.add_argument("--cl-angle", dest="cl_angle")
    ap.add_argument("--keywords")
    ap.add_argument("--check", action="store_true",
                    help="List folders with no Job_Details.md and exit non-zero")
    a = ap.parse_args()

    if a.check:
        gaps = missing()
        for g in gaps:
            print(f"  MISSING Job_Details.md: {g}")
        print(f"{len(gaps)} folder(s) without Job_Details.md")
        sys.exit(1 if gaps else 0)

    if not (a.company and a.role) and not a.folder:
        ap.error("--company and --role are required (or --folder)")

    named = {"URL": a.url, "Apply URL": a.apply_url, "Location": a.location,
             "Work Mode": a.work_mode, "Pay": a.pay, "Posted": a.posted,
             "Source": a.source, "ATS": a.ats, "Priority": a.priority,
             "CL angle": a.cl_angle, "Keywords": a.keywords}
    named = {k: v for k, v in named.items() if v}
    if a.folder:
        p = a.folder if os.path.isabs(a.folder) else os.path.join(APPS, a.folder)
        if a.company:
            named["Company"] = a.company
        if a.role:
            named["Role"] = a.role
        if a.status:
            named["Status"] = a.status
        print(write_details(p, **named))
    else:
        print(ensure(a.company, a.role, status=a.status, applied=a.applied, **named))
