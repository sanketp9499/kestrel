"""email_monitor.py — Monitor Gmail for job responses + send daily notification.

NOTE: This script is called FROM within Claude CLI which has Gmail MCP access.
It outputs structured JSON that Claude reads, then Claude uses Gmail MCP to act.
Standalone testing uses classify_email() which has no MCP dependency.

check_inbox() and send_summary() require Gmail OAuth credentials stored in
secrets.local.json or environment variables (GMAIL_CREDENTIALS_JSON,
GMAIL_TOKEN_JSON). Tests skip gracefully when credentials are absent.
"""

import json
import datetime
import os

# ── Classification signals ─────────────────────────────────────────────────
INTERVIEW_SIGNALS = [
    "interview", "next steps", "schedule", "assessment",
    "coding challenge", "call", "meet", "invite", "availability", "talk",
]
REJECTION_SIGNALS = [
    "unfortunately", "regret", "not moving forward", "other candidates",
    "not selected", "position has been filled",
    "decided to move forward with other",
]
UPDATE_SIGNALS = [
    "received your application", "application is under review",
    "we have received", "thank you for applying",
]


# ── Pure classification (no credentials needed) ────────────────────────────
def classify_email(subject: str, body: str) -> str | None:
    """Classify an email by subject + body text.

    Returns "interview", "rejection", or "other". Returns None for unrelated emails.
    """
    combined = (subject + " " + body).lower()
    if any(s in combined for s in INTERVIEW_SIGNALS):
        return "interview"
    if any(s in combined for s in REJECTION_SIGNALS):
        return "rejection"
    return None


# ── Gmail helpers ──────────────────────────────────────────────────────────
def _get_gmail_service(profile: dict):
    """Build and return an authenticated Gmail API service.

    Credentials are loaded from (in priority order):
      1. GMAIL_CREDENTIALS_JSON env var (JSON string)
      2. GMAIL_TOKEN_JSON env var (JSON string for the token)
      3. profile["gmail_credentials"] / profile["gmail_token"] from secrets.local.json
    Returns None if credentials are unavailable.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        return None  # google-api-python-client not installed

    token_json = (
        os.environ.get("GMAIL_TOKEN_JSON")
        or profile.get("gmail_token")
    )
    creds_json = (
        os.environ.get("GMAIL_CREDENTIALS_JSON")
        or profile.get("gmail_credentials")
    )

    if not token_json:
        return None

    try:
        token_data = json.loads(token_json) if isinstance(token_json, str) else token_json
        creds = Credentials.from_authorized_user_info(token_data)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build("gmail", "v1", credentials=creds)
    except Exception:
        return None


def _decode_body(payload: dict) -> str:
    """Recursively extract plain-text body from a Gmail message payload."""
    import base64

    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    if mime.startswith("multipart/"):
        for part in payload.get("parts", []):
            text = _decode_body(part)
            if text:
                return text
    return ""


def _header(headers: list, name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


# ── Public API ─────────────────────────────────────────────────────────────
def check_inbox(profile: dict) -> list[dict]:
    """Scan Gmail inbox for job-related threads from the last 7 days.

    Returns a list of dicts:
        {
            "thread_id": str,
            "subject":   str,
            "from":      str,
            "type":      "interview" | "rejection" | "other",
        }

    Returns an empty list if Gmail credentials are not configured.
    """
    service = _get_gmail_service(profile)
    if service is None:
        return []

    try:
        query = "in:inbox newer_than:7d"
        response = (
            service.users()
            .threads()
            .list(userId="me", q=query, maxResults=50)
            .execute()
        )
        threads = response.get("threads", [])
    except Exception:
        return []

    results = []
    for t in threads:
        thread_id = t.get("id", "")
        try:
            thread = (
                service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )
        except Exception:
            continue

        messages = thread.get("messages", [])
        if not messages:
            continue

        # Use the most recent message for headers + body
        msg = messages[-1]
        headers = msg.get("payload", {}).get("headers", [])
        subject = _header(headers, "subject")
        sender = _header(headers, "from")
        body = _decode_body(msg.get("payload", {}))

        email_type = classify_email(subject, body)
        if email_type is None:
            email_type = "other"

        results.append(
            {
                "thread_id": thread_id,
                "subject": subject,
                "from": sender,
                "type": email_type,
            }
        )

    return results


def send_summary(
    profile: dict,
    applied_jobs: list,
    inbox_results: list,
    captcha_pending: list | None = None,
    errors: list | None = None,
) -> bool:
    """Send a daily HTML summary email to profile["email"].

    applied_jobs: list of dicts with keys: company, role, url, ats_type
    inbox_results: list of dicts returned by check_inbox()

    Returns True on success, False on failure or when credentials unavailable.
    """
    # The summary carries company names, roles and what was applied to, so it
    # is outbound mail like any other and is held with the rest.
    import safe_mode
    if safe_mode.guard("email"):
        return False

    service = _get_gmail_service(profile)
    if service is None:
        return False

    report = build_daily_report(
        applied=applied_jobs,
        captcha_pending=captcha_pending or [],
        responses=[r for r in inbox_results if r.get("type") in ("interview", "rejection")],
        errors=errors or [],
    )
    subject = report["subject"]
    body_text = report["body"]

    # Build HTML version
    html_lines = []
    for line in body_text.splitlines():
        if line.isupper() and line.strip():
            html_lines.append(f"<h3>{line}</h3>")
        elif line.startswith("•"):
            html_lines.append(f"<li>{line[1:].strip()}</li>")
        elif line == "":
            html_lines.append("<br>")
        else:
            html_lines.append(f"<p>{line}</p>")
    html_body = "<html><body>" + "\n".join(html_lines) + "</body></html>"

    # Compose MIME message
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    to_addr = profile.get("email", "sanketp9499@gmail.com")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = to_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True
    except Exception:
        return False


# ── Extra IMAP mailboxes ──────────────────────────────────────────────────
# Gmail is not the only place employer replies land. aiApply applies on Sanket's
# behalf from a proxy mailbox it issues him, sanketp9499@mailboxcore.com — a
# Migadu-hosted domain (MX aspmx1.migadu.com, and an _imaps._tcp SRV record
# pointing at imap.migadu.com). Every reply to an aiApply submission goes there
# and Gmail never sees it, which is how a ventureLAB interview request and an
# expired Huzzle video interview both went unnoticed. Reading it over IMAP
# closes that hole without waiting on aiApply to add a forwarding feature.
#
# Configure in Scripts/secrets.local.json:
#   "imap_mailboxes": [
#     {"label": "aiapply",
#      "user": "sanketp9499@mailboxcore.com",
#      "password": "<the mailbox password shown at aiapply.co/app/inbox>",
#      "host": "imap.migadu.com",
#      "port": 993}
#   ]
IMAP_DEFAULT_HOST = "imap.migadu.com"
IMAP_DEFAULT_PORT = 993


def _imap_body(msg) -> str:
    """Best-effort plain text out of an email.message.Message."""
    if not msg.is_multipart():
        try:
            return msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            return str(msg.get_payload())
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            try:
                return part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="replace")
            except Exception:
                continue
    return ""


def _decode_mime_header(raw) -> str:
    from email.header import decode_header, make_header
    try:
        return str(make_header(decode_header(raw or "")))
    except Exception:
        return str(raw or "")


def check_imap_inbox(profile: dict, days: int = 7) -> list[dict]:
    """Scan every mailbox listed under profile["imap_mailboxes"].

    Same result shape as check_inbox(), plus a "mailbox" field naming the
    account a message came from. Returns [] when nothing is configured, and
    skips (rather than raises on) a mailbox that fails to authenticate, so one
    bad credential cannot take down the whole daily run.
    """
    import datetime as _dt
    import email
    import imaplib

    boxes = profile.get("imap_mailboxes") or []
    if isinstance(boxes, dict):
        boxes = [boxes]
    if not boxes:
        return []

    since = (_dt.date.today() - _dt.timedelta(days=days)).strftime("%d-%b-%Y")
    results = []

    for box in boxes:
        user = box.get("user") or box.get("email")
        password = box.get("password")
        label = box.get("label") or user or "imap"
        if not user or not password:
            continue
        host = box.get("host") or IMAP_DEFAULT_HOST
        port = int(box.get("port") or IMAP_DEFAULT_PORT)

        conn = None
        try:
            conn = imaplib.IMAP4_SSL(host, port)
            conn.login(user, password)
            conn.select("INBOX")
            status, data = conn.search(None, f"(SINCE {since})")
            if status != "OK":
                continue
            for mid in (data[0] or b"").split()[-100:]:
                status, payload = conn.fetch(mid, "(RFC822)")
                if status != "OK" or not payload or not payload[0]:
                    continue
                msg = email.message_from_bytes(payload[0][1])
                subject = _decode_mime_header(msg.get("Subject"))
                sender = _decode_mime_header(msg.get("From"))
                results.append({
                    "thread_id": _decode_mime_header(msg.get("Message-ID")),
                    "subject": subject,
                    "from": sender,
                    "date": _decode_mime_header(msg.get("Date")),
                    "mailbox": label,
                    "type": classify_email(subject, _imap_body(msg)) or "other",
                })
        except Exception as e:
            print(f"IMAP {label}: {type(e).__name__}: {str(e)[:120]}")
        finally:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass

    return results


def check_all_inboxes(profile: dict, days: int = 7) -> list[dict]:
    """Gmail plus every configured IMAP mailbox, in one list.

    This is what Phase 6 should call. check_inbox() on its own is blind to
    everything aiApply submitted.
    """
    merged = list(check_inbox(profile))
    for r in merged:
        r.setdefault("mailbox", "gmail")
    merged.extend(check_imap_inbox(profile, days=days))
    return merged


# ── Report builder (also used by orchestrator directly) ───────────────────
def build_daily_report(
    applied: list,
    captcha_pending: list,
    responses: list,
    errors: list,
) -> dict:
    """Build structured data for the daily notification email.

    Returns {"subject": str, "body": str}.
    """
    today = datetime.date.today().strftime("%B %d")
    interviews = [r for r in responses if r.get("type") == "interview"]
    rejections = [r for r in responses if r.get("type") == "rejection"]

    subject_parts = [f"Job Hunt — {today}: {len(applied)} applied"]
    if interviews:
        count = len(interviews)
        subject_parts.append(
            f"{count} interview invite{'s' if count > 1 else ''}"
        )
    subject = ", ".join(subject_parts)

    lines = ["APPLIED TODAY"]
    for job in applied:
        ats = job.get("ats_type", "")
        lines.append(f"• {job.get('company')} — {job.get('role')} ({ats})")

    if captcha_pending:
        lines += ["", "CAPTCHA PENDING — YOUR ACTION NEEDED"]
        for job in captcha_pending:
            lines.append(
                f"• {job.get('company')} — {job.get('role')} — {job.get('url', '')}"
            )

    if responses:
        lines += ["", "RESPONSES RECEIVED"]
        for r in interviews:
            lines.append(
                f"• INTERVIEW: {r.get('subject')} (check Gmail, labeled Job Hunt/Job Offers)"
            )
        for r in rejections:
            lines.append(f"• Rejected: {r.get('subject')}")

    if errors:
        lines += ["", "ERRORS / SKIPPED"]
        for e in errors:
            lines.append(f"• {e}")

    return {"subject": subject, "body": "\n".join(lines)}


# ── Aliases for brief compatibility ───────────────────────────────────────
def scan_responses(profile: dict | None = None) -> list[dict]:
    """Alias for check_inbox() — returns categorised inbox threads."""
    if profile is None:
        try:
            from daily_log import load_profile
            profile = load_profile()
        except Exception:
            return []
    return check_inbox(profile)


def send_daily_report(
    applied: list,
    captcha_pending: list,
    responses: list,
    errors: list,
    profile: dict | None = None,
) -> dict:
    """Build and return report dict; also emails it when Gmail is configured."""
    if profile is None:
        try:
            from daily_log import load_profile
            profile = load_profile()
        except Exception:
            profile = {}
    report = build_daily_report(applied, captcha_pending, responses, errors)
    # Best-effort send — failure is non-fatal
    send_summary(profile, applied, responses, captcha_pending, errors)
    return report


# ── CLI ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Job-response mailbox monitor")
    ap.add_argument("--check-mail", action="store_true",
                    help="scan Gmail + every configured IMAP mailbox and print what it finds")
    ap.add_argument("--imap-only", action="store_true",
                    help="scan only the IMAP mailboxes (use to test new credentials)")
    ap.add_argument("--days", type=int, default=7)
    # Phase 7 of RUN_PIPELINE.md has documented these four since the pipeline
    # was written, but they were never defined, and parse_known_args() threw
    # them away without a word: the documented command printed a hardcoded
    # sample report and exited 0. Every run worked around it by hand.
    ap.add_argument("--applied", metavar="JSON",
                    help="JSON list of jobs applied to today: "
                         '[{"company":..,"role":..,"url":..,"ats_type":..}]')
    ap.add_argument("--captcha", metavar="JSON", default="[]",
                    help="JSON list of jobs left pending behind a CAPTCHA")
    ap.add_argument("--responses", metavar="JSON", default="[]",
                    help="JSON list of inbox results from check_all_inboxes()")
    ap.add_argument("--errors", metavar="JSON", default="[]",
                    help="JSON list of error strings from today's run")
    ap.add_argument("--dry-run", action="store_true",
                    help="build and print the report without sending it")
    # Not parse_known_args: silently discarding an unrecognised flag is what
    # hid this bug for the life of the project.
    args = ap.parse_args()

    if args.check_mail or args.imap_only:
        try:
            from daily_log import load_profile
            profile = load_profile()
        except Exception:
            profile = {}
        found = (check_imap_inbox(profile, days=args.days) if args.imap_only
                 else check_all_inboxes(profile, days=args.days))
        if not found:
            configured = bool(profile.get("imap_mailboxes"))
            print("Nothing found."
                  + ("" if configured else
                     "\nNo imap_mailboxes configured in Scripts/secrets.local.json —"
                     " see the block above check_imap_inbox() for the shape."))
        by_type = {}
        for m in found:
            by_type.setdefault(m["type"], []).append(m)
        for kind in ("interview", "rejection", "other"):
            rows = by_type.get(kind, [])
            if not rows:
                continue
            print(f"\n=== {kind.upper()} ({len(rows)}) ===")
            for m in rows:
                print(f"  [{m.get('mailbox', '?')}] {m.get('date', '')[:16]}  "
                      f"{m['from'][:40]}  |  {m['subject'][:70]}")
        raise SystemExit(0)

    if args.applied is None:
        # There used to be a hardcoded "sample" report here, printed for a
        # Shopify application nobody made. It looked exactly like a real report,
        # and it is what the documented phase 7 command actually produced.
        ap.print_usage()
        raise SystemExit("\nNothing to report on. Pass --applied '<json>' "
                         "(see phase 7 of RUN_PIPELINE.md) or --check-mail.")

    def _load(flag, raw):
        try:
            value = json.loads(raw)
        except ValueError as e:
            raise SystemExit(f"{flag}: not valid JSON ({e})")
        if not isinstance(value, list):
            raise SystemExit(f"{flag}: expected a JSON list, got {type(value).__name__}")
        return value

    applied = _load("--applied", args.applied)
    captcha = _load("--captcha", args.captcha)
    responses = _load("--responses", args.responses)
    errors = _load("--errors", args.errors)

    if args.dry_run:
        report = build_daily_report(applied, captcha, responses, errors)
        print("[dry run] built the report, not sending it")
    else:
        report = send_daily_report(applied, captcha, responses, errors)
    print(json.dumps(report, indent=2, ensure_ascii=False))
