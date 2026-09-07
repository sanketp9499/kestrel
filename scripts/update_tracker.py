#!/usr/bin/env python3
"""
update_tracker.py — Adds or updates a job entry in Job_Tracker.xlsx
Usage:
  python3 update_tracker.py --company "ACME" --role "UX Designer" \
    --location "Toronto, ON" --url "https://..." \
    --status "✅ APPLIED" --date "2026-06-15" --mode "Remote (Canada)" \
    --salary "$65,000 CAD" --notes "Applied via Greenhouse"
"""
import argparse, os, datetime
from openpyxl import load_workbook
from openpyxl.styles import PatternFill

# Path resolution
WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.exists(WORKSPACE):
    WORKSPACE = "/sessions/eager-pensive-meitner/mnt/Job Hunter"
TRACKER = os.path.join(WORKSPACE, "Job_Tracker.xlsx")

GREEN  = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
ORANGE = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
RED    = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
BLUE   = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")

def get_fill(status):
    s = status.lower()
    if "applied" in s:   return GREEN
    if "manual" in s:    return ORANGE
    if "expired" in s or "skip" in s: return RED
    return BLUE

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--company",  required=True)
    p.add_argument("--role",     required=True)
    p.add_argument("--location", default="Canada")
    p.add_argument("--url",      default="")
    p.add_argument("--status",   default="✅ APPLIED")
    p.add_argument("--date",     default=datetime.date.today().isoformat())
    p.add_argument("--mode",     default="")
    p.add_argument("--salary",   default="")
    p.add_argument("--notes",    default="")
    p.add_argument("--heat",     default="")
    args = p.parse_args()

    wb = load_workbook(TRACKER)
    ws = wb.active
    fill = get_fill(args.status)

    # Columns are resolved from the header row. A hardcoded index map used to
    # live here and had drifted out of sync with the sheet, which wrote Status
    # into the Location column and the URL into Resume for every row it touched.
    header = [str(c.value or "").strip().lower() for c in ws[1]]

    def col(*names):
        for n in names:
            if n in header:
                return header.index(n)
        return None

    IDX = {
        "num":      col("#", "no", "id"),
        "company":  col("company", "employer"),
        "role":     col("role", "title", "position"),
        "location": col("location"),
        "mode":     col("mode", "work mode", "workmode"),
        "salary":   col("pay", "salary", "compensation"),
        "status":   col("status"),
        "priority": col("priority"),
        "date":     col("applied", "date applied", "dateapplied"),
        "url":      col("url", "applyurl", "apply url", "link"),
        "folder":   col("folder"),
        "resume":   col("resume"),
        "cl":       col("cl", "cover letter"),
        "cold":     col("cold email", "coldemail"),
    }
    if IDX["company"] is None or IDX["role"] is None:
        raise SystemExit("Tracker header missing Company/Role columns — refusing to write")

    values = {
        "company":  args.company,
        "role":     args.role,
        "location": args.location,
        "mode":     args.mode,
        "salary":   args.salary,
        "status":   args.status,
        "priority": args.heat or "HIGH",
        "date":     args.date,
        "url":      args.url,
    }

    # Update in place when company+role already exists
    for row in ws.iter_rows(min_row=2):
        comp = str(row[IDX["company"]].value or "").lower()
        role = str(row[IDX["role"]].value or "").lower()
        if not comp:
            continue
        if args.company.lower() in comp and args.role.lower()[:10] in role:
            for key, val in values.items():
                i = IDX.get(key)
                if i is None or not val:
                    continue
                if key in ("company", "role"):
                    continue
                row[i].value = val
            for cell in row:
                if cell.value is not None:
                    cell.fill = fill
            wb.save(TRACKER)
            print(f"Updated: {args.company} — {args.role} → {args.status}")
            return

    nums = [r[IDX["num"]] for r in ws.iter_rows(min_row=2, values_only=True)
            if IDX["num"] is not None and isinstance(r[IDX["num"]], int)]
    next_num = (max(nums) + 1) if nums else 1

    new_row = [None] * len(header)
    if IDX["num"] is not None:
        new_row[IDX["num"]] = next_num
    for key, val in values.items():
        i = IDX.get(key)
        if i is not None and val:
            new_row[i] = val
    ws.append(new_row)

    last_row = ws.max_row
    for col_i in range(1, len(header) + 1):
        cell = ws.cell(row=last_row, column=col_i)
        if cell.value is not None:
            cell.fill = fill

    wb.save(TRACKER)
    print(f"Added: {args.company} — {args.role} (#{next_num}) → {args.status}")

if __name__ == "__main__":
    main()
