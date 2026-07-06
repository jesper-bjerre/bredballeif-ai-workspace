"""Process Conventus notification emails and trigger HalBooking onboarding.

This module is invoked by:
  * the agent CLI: `python -m agent process-emails`
  * the GitHub Actions workflow conventus-to-halbooking.yml (which runs the
    same CLI command — single source of truth)

Workflow per run:
1. Connect to Gmail (bredballeifpadel@gmail.com) via OAuth refresh token.
2. Search for unread emails from kan-ikke-besvares-2296@conventus.dk
   with subject starting with "Notifikation - Tilmelding til".
3. For each email: parse "Hold:" and "Medlem:" lines, map the hold name to
   --type / --end-date / --start-date flags, then run
   `python -m agent onboard --name <medlem> --type <type> --end-date ...`
   as a subprocess (same code path a human would invoke).
4. On success: label "AI-processed" + mark read.
   On failure: label "AI-error" + mark read.
5. Send one summary email to ADMIN_EMAIL_TO. If nothing was processed, send nothing.

Required environment variables:
    GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN
    ADMIN_EMAIL_TO
    HALBOOKING_BASE_URL, HALBOOKING_USERNAME, HALBOOKING_PASSWORD
    CONVENTUS_ID, CONVENTUS_API_KEY

Returns: int exit code. 0 if all OK, 1 if any email failed, 2 on config error.
"""
from __future__ import annotations

import base64
import datetime
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
HALBOOKING_AGENT_DIR = Path(__file__).resolve().parent

CONVENTUS_SENDER = "kan-ikke-besvares-2296@conventus.dk"
SUBJECT_PREFIX = "Notifikation - Tilmelding til"

GMAIL_QUERY = (
    f'from:{CONVENTUS_SENDER} '
    f'subject:"{SUBJECT_PREFIX}" '
    f'is:unread '
    f'-label:AI-processed -label:AI-error'
)

LABEL_PROCESSED = "AI-processed"
LABEL_ERROR = "AI-error"


@dataclass
class ProcessedEmail:
    message_id: str
    subject: str = ""
    received: str = ""
    hold: str = ""
    hold_id: str = ""
    medlem: str = ""
    medlem_id: str = ""
    type_flag: str = ""
    start_date: str = ""
    end_date: str = ""
    success: bool = False
    error: str = ""
    onboard_stdout: str = ""
    onboard_stderr: str = ""


# ---------------------------------------------------------------------------
# Gmail helpers (lazy-imported so the agent CLI doesn't require Google libs
# unless `process-emails` is actually invoked)
# ---------------------------------------------------------------------------
def _build_gmail_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    required = ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"Missing required env vars: {', '.join(missing)}")

    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/gmail.modify"],
    )
    creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _get_or_create_label(service, name: str) -> str:
    resp = service.users().labels().list(userId="me").execute()
    for lbl in resp.get("labels", []):
        if lbl["name"].lower() == name.lower():
            return lbl["id"]
    created = service.users().labels().create(
        userId="me",
        body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
    ).execute()
    return created["id"]


def _list_matching_messages(service) -> list[dict]:
    messages: list[dict] = []
    page_token: str | None = None
    while True:
        resp = service.users().messages().list(
            userId="me", q=GMAIL_QUERY, pageToken=page_token, maxResults=100
        ).execute()
        messages.extend(resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return messages


def _get_full_message(service, message_id: str) -> dict:
    return service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()


def _extract_plain_body(message: dict) -> str:
    def _walk(part: dict) -> Iterable[str]:
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if mime == "text/plain" and data:
            yield base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        for sub in part.get("parts", []) or []:
            yield from _walk(sub)

    payload = message.get("payload", {})
    text_parts = list(_walk(payload))
    if text_parts:
        return "\n".join(text_parts)

    def _walk_html(part: dict) -> Iterable[str]:
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if mime == "text/html" and data:
            yield base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        for sub in part.get("parts", []) or []:
            yield from _walk_html(sub)

    html_parts = list(_walk_html(payload))
    if html_parts:
        return re.sub(r"<[^>]+>", "", "\n".join(html_parts))
    return ""


def _get_header(message: dict, name: str) -> str:
    for h in message.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _label_and_mark_read(service, message_id: str, label_id: str) -> None:
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"addLabelIds": [label_id], "removeLabelIds": ["UNREAD"]},
    ).execute()


def _send_status_email(service, to_addr: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


# ---------------------------------------------------------------------------
# Conventus email parsing + hold-name mapping (pure, no Gmail dependency)
# ---------------------------------------------------------------------------
# Conventus notification body (text/plain) puts everything on a single line:
#   Hold:Padel: Hele 2026 (non-prime) (Id: 1019513)Medlem:Wilhelm Hill Nedergaard (Id: 5908572)
# We use the trailing "(Id: <digits>)" as a reliable terminator for each field.
HOLD_RE = re.compile(
    r"Hold:\s*(?P<name>.+?)\s*\(Id:\s*(?P<id>\d+)\s*\)",
    re.IGNORECASE | re.DOTALL,
)
MEDLEM_RE = re.compile(
    r"Medlem:\s*(?P<name>.+?)\s*\(Id:\s*(?P<id>\d+)\s*\)",
    re.IGNORECASE | re.DOTALL,
)
YEAR_RE = re.compile(r"\b(20\d{2})\b")


def parse_email_body(body: str) -> tuple[str, str, str, str]:
    """Return (hold_name, hold_id, medlem_name, medlem_id) parsed from a Conventus body.

    Each tuple element is "" if the corresponding match was not found.
    """
    h = HOLD_RE.search(body)
    m = MEDLEM_RE.search(body)
    hold_name = h.group("name").strip() if h else ""
    hold_id = h.group("id").strip() if h else ""
    medlem_name = m.group("name").strip() if m else ""
    medlem_id = m.group("id").strip() if m else ""
    return hold_name, hold_id, medlem_name, medlem_id


def map_hold_to_flags(hold: str) -> tuple[str, str, str | None]:
    """Map a Conventus group/hold name to (type, end_date, start_date_or_None).

    Examples:
        'Padel: Hele 2026 (prime)'              -> ('prime',     '31-12-2026', None)
        'Padel: Januar-Juni 2026 (prime)'       -> ('prime',     '30-06-2026', None)
        'Padel: Hele 2026 (non-prime)'          -> ('non-prime', '31-12-2026', None)
        'Padel: Juli-December 2026 (prime)'     -> ('prime',     '31-12-2026', '01-07-2026')
        'Padel: Resten af 2026 (non-prime)'     -> ('non-prime', '31-12-2026', '<today>')

    Raises ValueError if the hold name cannot be mapped.
    """
    low = hold.lower()

    if "non-prime" in low or "non prime" in low:
        type_flag = "non-prime"
    elif "prime" in low:
        type_flag = "prime"
    else:
        raise ValueError(f"Kan ikke afgøre type (prime/non-prime) fra hold: {hold!r}")

    year_match = YEAR_RE.search(hold)
    if not year_match:
        raise ValueError(f"Kan ikke finde årstal i hold: {hold!r}")
    year = int(year_match.group(1))

    if "hele" in low:
        end_date, start_date = f"31-12-{year}", None
    elif "januar-juni" in low or "jan-juni" in low or "jan-jun" in low:
        end_date, start_date = f"30-06-{year}", None
    elif "juli-december" in low or "jul-dec" in low or "juli-dec" in low:
        end_date, start_date = f"31-12-{year}", f"01-07-{year}"
    elif "resten af" in low:
        today = datetime.date.today()
        end_date = f"31-12-{year}"
        start_date = today.strftime("%d-%m-%Y")
    else:
        raise ValueError(f"Kan ikke afgøre periode fra hold: {hold!r}")

    return type_flag, end_date, start_date


# ---------------------------------------------------------------------------
# Onboard subprocess — same CLI invocation a human would use
# ---------------------------------------------------------------------------
# Onboard subprocess timeout (seconds). Must comfortably exceed the worst-case
# Conventus verification time inside onboard: 90s timeout × 5 retries + backoff
# (~450s+), PLUS the HalBooking Playwright steps. Set generously so a slow
# Conventus API never causes a silent mid-retry kill.
ONBOARD_TIMEOUT_SECONDS = 900


def _run_onboard(name: str, type_flag: str, end_date: str, start_date: str | None) -> tuple[int, str, str]:
    cmd = [
        sys.executable, "-m", "agent",
        "onboard",
        "--name", name,
        "--type", type_flag,
        "--end-date", end_date,
    ]
    if start_date:
        cmd += ["--start-date", start_date]

    env = os.environ.copy()
    pythonpath_parts = [str(HALBOOKING_AGENT_DIR), env.get("PYTHONPATH", "")]
    env["PYTHONPATH"] = os.pathsep.join(p for p in pythonpath_parts if p)

    # Trace: echo the exact command + environment so a failed run can be
    # reproduced locally from the workflow log alone.
    printable_cmd = " ".join(
        f'"{c}"' if " " in c else c for c in cmd[2:]  # skip python -m noise
    )
    print(f"    [trace] onboard cmd: python -m {printable_cmd}")
    print(f"    [trace] cwd={REPO_ROOT}  PYTHONPATH={env['PYTHONPATH']}")
    print(f"    [trace] timeout={ONBOARD_TIMEOUT_SECONDS}s  starting subprocess…", flush=True)

    t0 = time.monotonic()
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=ONBOARD_TIMEOUT_SECONDS,
    )
    elapsed = time.monotonic() - t0
    print(f"    [trace] onboard subprocess finished in {elapsed:.1f}s with exit code {proc.returncode}", flush=True)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _onboard_succeeded(stdout: str) -> bool:
    if "[!] Fejl" in stdout or "[!] Login" in stdout:
        return False
    return bool(re.search(r"Success:\s+True", stdout))


def _is_conventus_api_timeout(stdout: str) -> bool:
    """Return True if the onboard failure was caused by Conventus API being
    unreachable (transient network error).  In that case the email should NOT
    be labelled AI-error — leave it unread so the next cron run retries."""
    return "Conventus API kunne ikke nås" in stdout or "urlopen error timed out" in stdout


# ---------------------------------------------------------------------------
# Summary email
# ---------------------------------------------------------------------------
def _build_summary(results: list[ProcessedEmail]) -> tuple[str, str]:
    total = len(results)
    failed = [r for r in results if not r.success]
    ok = [r for r in results if r.success]

    if failed:
        subject = f"[Padel] {len(failed)} fejl ud af {total} Conventus-tilmeldinger"
    else:
        subject = f"[Padel] {total} Conventus-tilmelding(er) behandlet OK"

    lines: list[str] = [
        f"Behandlet: {total}",
        f"OK:        {len(ok)}",
        f"Fejl:      {len(failed)}",
        "",
    ]

    if failed:
        lines += ["=" * 70, "FEJL — kræver manuel håndtering", "=" * 70]
        for r in failed:
            lines += [
                "",
                f"Modtaget:  {r.received}",
                f"Emne:      {r.subject}",
                f"Hold:      {r.hold or '(ikke parset)'}" + (f"  (Id: {r.hold_id})" if r.hold_id else ""),
                f"Medlem:    {r.medlem or '(ikke parset)'}" + (f"  (Id: {r.medlem_id})" if r.medlem_id else ""),
                f"Fejl:      {r.error}",
            ]
            if r.onboard_stdout:
                tail = r.onboard_stdout.strip().splitlines()[-20:]
                lines.append("Onboard stdout (sidste 20 linjer):")
                lines += [f"  {l}" for l in tail]
            if r.onboard_stderr:
                lines.append("Onboard stderr:")
                lines += [f"  {l}" for l in r.onboard_stderr.strip().splitlines()[-10:]]

    if ok:
        lines += ["", "=" * 70, "OK", "=" * 70]
        for r in ok:
            lines.append(f"  ✓ {r.medlem}  —  {r.hold}  ({r.type_flag}, til {r.end_date})")

    lines += ["", "--", "Sendt af conventus-to-halbooking automation (agent process-emails)"]
    return subject, "\n".join(lines)


# ---------------------------------------------------------------------------
# Test mode — synthesizes one email so the full parse→map→onboard chain runs
# without touching Gmail search/labels. Used by the TEST workflow.
# ---------------------------------------------------------------------------
def process_test(name: str, hold: str) -> int:
    """Run the full pipeline with a synthesized email body.

    Skips Gmail search and labeling, but still:
    - runs the body regex parser
    - runs map_hold_to_flags()
    - subprocess-calls `agent onboard ...` with real HalBooking automation
    - sends a [TEST]-prefixed status email to ADMIN_EMAIL_TO

    Returns 0 on success, 1 on onboard failure, 2 on config error.
    """
    admin_to = os.environ.get("ADMIN_EMAIL_TO", "").strip()
    if not admin_to:
        print("ERROR: ADMIN_EMAIL_TO not set.")
        return 2

    fake_body = f"Hold:{hold} (Id: 0)Medlem:{name} (Id: 0)"
    print(f"[*] TEST MODE")
    print(f"    Synthesized body: {fake_body!r}")

    record = ProcessedEmail(
        message_id="(test)",
        subject=f"[TEST] Notifikation - Tilmelding til {hold}",
        received="(test mode — udløst manuelt via workflow_dispatch)",
    )

    hold_parsed, hold_id, medlem_parsed, medlem_id = parse_email_body(fake_body)
    record.hold = hold_parsed
    record.hold_id = hold_id
    record.medlem = medlem_parsed
    record.medlem_id = medlem_id
    print(f"    Hold:     {hold_parsed!r}")
    print(f"    Medlem:   {medlem_parsed!r}")

    proceed = True
    if not hold_parsed or not medlem_parsed:
        record.error = "Kunne ikke parse syntetisk body."
        proceed = False

    if proceed:
        try:
            type_flag, end_date, start_date = map_hold_to_flags(hold_parsed)
            record.type_flag = type_flag
            record.end_date = end_date
            record.start_date = start_date or ""
            print(f"    Mapping:  --type {type_flag} --end-date {end_date}"
                  + (f" --start-date {start_date}" if start_date else ""))
        except ValueError as e:
            record.error = str(e)
            proceed = False

    if proceed:
        print(f"    [*] Running onboard …")
        try:
            rc, stdout, stderr = _run_onboard(medlem_parsed, type_flag, end_date, start_date)
            record.onboard_stdout = stdout
            record.onboard_stderr = stderr
            if rc == 0 and _onboard_succeeded(stdout):
                record.success = True
                print(f"    [+] OK")
            else:
                record.success = False
                record.error = (
                    f"Onboard exit code {rc}." if rc != 0
                    else "Onboard returnerede 0, men 'Success: True' blev ikke fundet."
                )
                print(f"    [!] FEJL: {record.error}")
                # Echo onboard output to workflow log so debugging doesn't require opening status mail
                print()
                print("=" * 70)
                print("ONBOARD STDOUT (fuld output for diagnostik):")
                print("=" * 70)
                print(stdout)
                if stderr.strip():
                    print("=" * 70)
                    print("ONBOARD STDERR:")
                    print("=" * 70)
                    print(stderr)
                print("=" * 70)
        except subprocess.TimeoutExpired:
            record.error = f"Onboard kommando timeout (>{ONBOARD_TIMEOUT_SECONDS//60} min)."
            print(f"    [!] FEJL: {record.error}")
        except Exception as e:
            record.error = f"Onboard subprocess fejlede: {e}"
            print(f"    [!] FEJL (uventet exception): {e!r}")
            import traceback
            traceback.print_exc()

    # Send test summary
    print()
    print(f"[*] Sending [TEST] status email to {admin_to}…")
    service = _build_gmail_service()
    subject, body = _build_summary([record])
    subject = "[TEST] " + subject
    body = (
        "⚠️ TEST MODE — udløst manuelt via workflow_dispatch.\n"
        "Ingen Gmail-mails er læst eller labelet i denne kørsel.\n\n"
        + body
    )
    _send_status_email(service, admin_to, subject, body)

    return 0 if record.success else 1


# ---------------------------------------------------------------------------
# Public entrypoint — used by agent.py and (transitively) by GitHub Actions
# ---------------------------------------------------------------------------
def process_emails() -> int:
    admin_to = os.environ.get("ADMIN_EMAIL_TO", "").strip()
    if not admin_to:
        print("ERROR: ADMIN_EMAIL_TO not set.")
        return 2

    print(f"[*] Connecting to Gmail (bredballeifpadel@gmail.com)…")
    service = _build_gmail_service()

    print(f"[*] Searching: {GMAIL_QUERY}")
    messages = _list_matching_messages(service)
    print(f"[*] Found {len(messages)} unprocessed message(s).")

    if not messages:
        print("[*] Nothing to do.")
        return 0

    label_ok = _get_or_create_label(service, LABEL_PROCESSED)
    label_err = _get_or_create_label(service, LABEL_ERROR)

    results: list[ProcessedEmail] = []

    for stub in messages:
        msg_id = stub["id"]
        try:
            msg = _get_full_message(service, msg_id)
        except Exception as e:
            print(f"[!] Could not fetch message {msg_id}: {e}")
            continue

        subject = _get_header(msg, "Subject")
        received = _get_header(msg, "Date")
        body = _extract_plain_body(msg)

        print()
        print(f"--- Message {msg_id} ---")
        print(f"    Subject:  {subject}")
        print(f"    Received: {received}")

        record = ProcessedEmail(message_id=msg_id, subject=subject, received=received)

        hold, hold_id, medlem, medlem_id = parse_email_body(body)
        record.hold = hold
        record.hold_id = hold_id
        record.medlem = medlem
        record.medlem_id = medlem_id
        print(f"    Hold:     {hold!r} (Conventus group id={hold_id or '?'})")
        print(f"    Medlem:   {medlem!r} (Conventus member id={medlem_id or '?'})")

        if not hold or not medlem:
            record.error = "Kunne ikke parse 'Hold:' og/eller 'Medlem:' i email-body."
            _label_and_mark_read(service, msg_id, label_err)
            results.append(record)
            continue

        try:
            type_flag, end_date, start_date = map_hold_to_flags(hold)
        except ValueError as e:
            record.error = str(e)
            _label_and_mark_read(service, msg_id, label_err)
            results.append(record)
            continue

        record.type_flag = type_flag
        record.end_date = end_date
        record.start_date = start_date or ""
        print(f"    Mapping:  --type {type_flag} --end-date {end_date}"
              + (f" --start-date {start_date}" if start_date else ""))

        print(f"    [*] Running onboard …")
        try:
            rc, stdout, stderr = _run_onboard(medlem, type_flag, end_date, start_date)
        except subprocess.TimeoutExpired as e:
            record.error = f"Onboard kommando timeout (>{ONBOARD_TIMEOUT_SECONDS//60} min)."
            print(f"    [!] FEJL: {record.error}")
            # Echo whatever output was captured before the kill, for diagnostics.
            partial_out = (e.stdout or "")
            partial_err = (e.stderr or "")
            if isinstance(partial_out, bytes):
                partial_out = partial_out.decode("utf-8", "replace")
            if isinstance(partial_err, bytes):
                partial_err = partial_err.decode("utf-8", "replace")
            record.onboard_stdout = partial_out
            record.onboard_stderr = partial_err
            print("=" * 70)
            print(f"ONBOARD STDOUT (delvis, før timeout) for message {msg_id}:")
            print("=" * 70)
            print(partial_out or "(ingen output fanget før timeout)")
            if partial_err.strip():
                print("=" * 70)
                print(f"ONBOARD STDERR (delvis) for message {msg_id}:")
                print("=" * 70)
                print(partial_err)
            print("=" * 70)
            _label_and_mark_read(service, msg_id, label_err)
            results.append(record)
            continue
        except Exception as e:
            record.error = f"Onboard subprocess fejlede: {e}"
            print(f"    [!] FEJL (uventet exception ved start af onboard): {e!r}")
            import traceback
            traceback.print_exc()
            _label_and_mark_read(service, msg_id, label_err)
            results.append(record)
            continue

        record.onboard_stdout = stdout
        record.onboard_stderr = stderr

        if rc == 0 and _onboard_succeeded(stdout):
            record.success = True
            _label_and_mark_read(service, msg_id, label_ok)
            print(f"    [+] OK")
        else:
            record.success = False
            if rc != 0:
                record.error = f"Onboard exit code {rc}."
            else:
                record.error = "Onboard returnerede 0, men 'Success: True' blev ikke fundet i output."
            if _is_conventus_api_timeout(stdout):
                # Transient — leave email unread/unlabeled so next cron run retries
                print(f"    [!] TRANSIENT FEJL (Conventus API timeout) — email beholder ingen label, genprøves næste kørsel.")
            else:
                _label_and_mark_read(service, msg_id, label_err)
                print(f"    [!] FEJL: {record.error}")
            # Echo onboard output to workflow log for diagnostics
            print()
            print("=" * 70)
            print(f"ONBOARD STDOUT for message {msg_id}:")
            print("=" * 70)
            print(stdout)
            if stderr.strip():
                print("=" * 70)
                print(f"ONBOARD STDERR for message {msg_id}:")
                print("=" * 70)
                print(stderr)
            print("=" * 70)

        results.append(record)

    print()
    print(f"[*] Sending summary email to {admin_to}…")
    subject, body = _build_summary(results)
    _send_status_email(service, admin_to, subject, body)

    failed_count = sum(1 for r in results if not r.success)
    return 0 if failed_count == 0 else 1
