#!/usr/bin/env python3
"""scan_state.py — The dedup memory the cloud scan carries instead of a tracker.

The scan half runs on a GitHub runner. The runner has no Excel tracker, no
Applications/ folder and no resume, and it must not: those are the personal
half, and they stay on the laptop. But the scan still has to know what it has
already seen, or it re-queues the same job every morning.

So the two halves share one small file:

    state/seen.json   { "urls": [...], "keys": [...], "updated": "..." }

`urls` are normalised job URLs, `keys` are punctuation-insensitive
company|role keys. Both come from `daily_auto_apply.normalize_job_url` and
`company_role_key`, so cloud dedup behaves exactly like local dedup. The laptop
exports this from the tracker after each run; the cloud reads it, and appends
whatever it queues so tomorrow's scan does not offer the same roles again
before the laptop has consumed them.

Nothing in here says where anyone applied, only that a URL has been considered.

Usage:
    python Scripts/scan_state.py export --repo <path>   # tracker -> seen.json
    python Scripts/scan_state.py show   --repo <path>
"""
import argparse
import datetime
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SEEN_REL = os.path.join("state", "seen.json")


def seen_path(repo):
    return os.path.join(repo, SEEN_REL)


def load(repo):
    """Read seen.json, tolerating a repo that has never had one."""
    p = seen_path(repo)
    if not os.path.exists(p):
        return {"urls": [], "keys": [], "updated": None}
    with io.open(p, encoding="utf-8") as f:
        d = json.load(f)
    d.setdefault("urls", [])
    d.setdefault("keys", [])
    return d


def load_sets(repo):
    d = load(repo)
    return set(d["urls"]), set(d["keys"])


def save(repo, urls, keys, note=None):
    p = seen_path(repo)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    payload = {
        "updated": datetime.datetime.now().isoformat(timespec="seconds"),
        "note": note or "Dedup memory shared by the cloud scan and the local "
                        "apply run. Job URLs and company|role keys only.",
        "counts": {"urls": len(urls), "keys": len(keys)},
        # Sorted so a commit diff shows what actually changed rather than a
        # reshuffled set every single run.
        "urls": sorted(urls),
        "keys": sorted(keys),
    }
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    return p


def add(repo, jobs):
    """Fold freshly queued jobs into the shared memory."""
    from daily_auto_apply import normalize_job_url, company_role_key
    urls, keys = load_sets(repo)
    for j in jobs:
        u = normalize_job_url(j.get("url") or j.get("apply_url") or "")
        if u:
            urls.add(u)
        k = company_role_key(j.get("company", ""), j.get("title") or j.get("role", ""))
        if k:
            keys.add(k)
    return save(repo, urls, keys), len(urls), len(keys)


def export_from_tracker(repo):
    """Rebuild seen.json from the laptop's tracker. Local-only: needs the xlsx."""
    from daily_auto_apply import get_existing_entries
    urls, keys = get_existing_entries()
    p = save(repo, urls, keys,
             note="Exported from the local tracker. Job URLs and company|role "
                  "keys only; no company names, statuses or documents.")
    return p, len(urls), len(keys)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("export", "show"))
    ap.add_argument("--repo", required=True,
                    help="Path to the private scan repo checkout")
    a = ap.parse_args()

    if a.action == "export":
        p, nu, nk = export_from_tracker(a.repo)
        print(f"wrote {p}: {nu} urls, {nk} company|role keys")
    else:
        d = load(a.repo)
        print(f"updated {d.get('updated')}: "
              f"{len(d['urls'])} urls, {len(d['keys'])} keys")
