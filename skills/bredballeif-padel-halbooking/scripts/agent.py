"""
AI Agent for HalBooking member management.

This agent operates in two modes:
  1. DISCOVER  – log in, navigate, and report back all forms/fields/buttons
                 found on the page so you know what data is needed.
  2. SEARCH    – search for a member by name and display their information.
  3. CREATE    – fill in the discovered fields and submit a new member.
  4. ONBOARD   – full SOP workflow: fetch from Conventus, create in HalBooking,
                 set password, assign membership, generate welcome email.

Usage:
  python agent.py discover          # show available form fields
  python agent.py search "Jensen"    # search for a member by name
  python agent.py search "Jensen" --detail  # search + open full detail view
  python agent.py create            # create a member (interactive prompts)
  python agent.py create --json member.json   # create from JSON file
  python agent.py onboard --name "Navn" --type prime --end-date 31-12-2026
  python agent.py --visible ...     # run with browser visible (not headless)
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from pathlib import Path

from halbooking_automation import HalBookingAutomation

for _parent in Path(__file__).resolve().parents:
    if (_parent / "scripts" / "gdpr_controls.py").exists():
        sys.path.insert(0, str(_parent / "scripts"))
        break

from gdpr_controls import (  # noqa: E402
    PolicyViolation,
    audit_event,
    emit_audit_event,
    enforce_record_limit,
    reject_broad_query,
    require_write_approval,
)


def _safe_url_shape(raw_url: str) -> str:
    """Return only origin and path; queries/fragments can contain identifiers or tokens."""
    parsed = urllib.parse.urlsplit(raw_url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _minimal_member_view(member: dict) -> dict:
    """Keep only fields needed to identify the requested member."""
    allowed_fragments = ("medlemsnr", "member_id", "member id", "navn", "name")
    return {
        str(key): value
        for key, value in member.items()
        if any(fragment in str(key).strip().lower() for fragment in allowed_fragments)
    }


def print_page_info(info: dict, indent: int = 0) -> None:
    pad = "  " * indent
    print(f"{pad}URL:   {_safe_url_shape(info.get('url', '')) or '?'}")
    print(f"{pad}Title: [OMITTED]")

    forms = info.get("forms", [])
    if forms:
        for i, form in enumerate(forms):
            print(f"\n{pad}--- Form {i+1} ({len(form)} fields) ---")
            for f in form:
                if f["type"] == "hidden":
                    continue
                req = " *REQUIRED*" if f.get("required") else ""
                opts = f"  options: {len(f['options'])}" if f.get("options") else ""
                print(f"{pad}  • {f['name'] or f['id'] or '(unnamed)'}"
                      f"  ({f['type']}){req}{opts}")
    else:
        print(f"{pad}  (no form fields found)")

    buttons = info.get("buttons", [])
    if buttons:
        print(f"\n{pad}Buttons:")
        for b in buttons:
            print(f"{pad}  [{b.get('type','?')}] id={b.get('id','')}")

    links = info.get("links", [])
    relevant = [l for l in links if any(k in (l.get("href","") + l.get("text","")).lower()
                for k in ("bruger", "opret", "ny", "member", "tilf", "edit", "admin"))]
    if relevant:
        print(f"\n{pad}Relevant links:")
        for l in relevant[:20]:
            print(f"{pad}  {_safe_url_shape(l['href'])}")


def cmd_discover(bot: HalBookingAutomation) -> None:
    """Log in and discover the member-management page."""
    print("=== Starting discovery ===\n")
    bot.start()
    try:
        # Capture AJAX calls for debugging
        ajax_log = bot.start_ajax_capture()

        if not bot.login():
            print("\n[!] Login failed. Check .env credentials and screenshots/")
            return

        print("\n--- Find-user page ---")
        page_info = bot.navigate_to_find_user()
        print_page_info(bot._page_info_to_dict(page_info))

        # Also try to reach the creation form
        print("\n--- Attempting to open 'new member' form ---")
        new_patterns = [
            'a:has-text("Opret")', 'a:has-text("Ny bruger")',
            'a:has-text("Tilføj")', 'button:has-text("Opret")',
            'a[href*="opret"]', 'a[href*="admin_bruger"]',
            'a[href*="editbruger"]', 'a[href*="newbruger"]',
        ]
        for sel in new_patterns:
            try:
                el = bot.page.locator(sel).first
                if el.is_visible(timeout=800):
                    print(f"  Found: {sel}")
                    el.click()
                    bot.wait_for_ajax()
                    break
            except Exception:
                continue

        form_info = bot.discover_page()
        print_page_info(bot._page_info_to_dict(form_info))

        if ajax_log:
            print(f"\n--- Captured {len(ajax_log)} AJAX requests ---")
            for req in ajax_log:
                print(f"  {req['method']} {_safe_url_shape(req['url'])}")
                if req.get("post_data"):
                    print("       body: [OMITTED]")

        print("\nRaw page HTML is deliberately not persisted.")

    finally:
        bot.stop()

    print("\n=== Discovery complete – check screenshots/ for visuals ===")


def cmd_search(bot: HalBookingAutomation, search_name: str, show_detail: bool = False) -> None:
    """Log in and search for a member by name."""
    search_name = reject_broad_query(search_name)
    print(f"=== Searching for '{search_name}' ===\n")
    bot.start()
    try:
        ajax_log = bot.start_ajax_capture()

        if not bot.login():
            print("\n[!] Login failed.")
            return

        if show_detail:
            result = bot.get_member_detail(search_name)
        else:
            result = bot.search_member(search_name)

        print(f"\n--- Search Results ---")
        print(f"  Search term: {result.get('search_term', search_name)}")
        print(f"  Success:     {result.get('success')}")

        members = enforce_record_limit(result.get("members", []), limit=10)
        if members:
            print(f"  Found:       {len(members)} member(s)\n")
            for i, m in enumerate(members):
                view = _minimal_member_view(m)
                parts = [f"{k}: {v}" for k, v in view.items() if v]
                print(f"  [{i}] " + (" | ".join(parts) if parts else "[fields omitted]"))
        else:
            print("  Found:       0 members")

        detail = result.get("member_detail")
        if detail:
            view = _minimal_member_view(detail)
            print(f"\n--- Minimized Member Detail ({len(view)} fields) ---")
            max_key_len = max((len(k) for k in view), default=0)
            for k, v in view.items():
                print(f"  {k:{max_key_len}s}  {v}")

        active_ms = result.get("active_memberships", [])
        if active_ms:
            print(f"\n--- Aktive medlemskaber/klippekort ({len(active_ms)}) ---")
            for ms in active_ms:
                name = ms.get('name', '?')
                period = ms.get('period', '?')
                print(f"  {name}  ({period})")
        elif detail:
            print("\n--- Aktive medlemskaber/klippekort ---")
            print("  (ingen fundet)")

        if result.get("note"):
            print("\n  Note: [OMITTED]")

        if ajax_log:
            print(f"\n--- AJAX activity ({len(ajax_log)} requests) ---")
            for req in ajax_log:
                print(f"  {req['method']} {_safe_url_shape(req['url'])}")
                if req.get("post_data"):
                    print("       body: [OMITTED]")

    finally:
        bot.stop()

    print("\n=== Search complete ===\n")


def cmd_create(bot: HalBookingAutomation, member_data: dict[str, str]) -> None:
    """Log in and create a new member with the given data."""
    print("=== Creating member ===\n")
    bot.start()
    try:
        ajax_log = bot.start_ajax_capture()

        if not bot.login():
            print("\n[!] Login failed.")
            return

        result = bot.create_member(member_data)

        print("\n--- Result ---")
        print(f"  Success:   {result.get('success')}")
        print(f"  Submitted: {result.get('submitted')}")
        print(f"  Final URL: {_safe_url_shape(result.get('final_url', ''))}")
        if result.get("note"):
            print("  Note:      [OMITTED]")

        if ajax_log:
            print(f"\n--- AJAX activity ({len(ajax_log)} requests) ---")
            for req in ajax_log:
                print(f"  {req['method']} {_safe_url_shape(req['url'])}")
                if req.get("post_data"):
                    print("       body: [OMITTED]")

    finally:
        bot.stop()

    print("\n=== Done ===")


def interactive_member_input() -> dict[str, str]:
    """Prompt the user for common member fields."""
    print("Enter member details (press Enter to skip a field):\n")
    fields = [
        ("fornavn",  "First name (fornavn)"),
        ("efternavn", "Last name (efternavn)"),
        ("email",    "Email"),
        ("telefon",  "Phone (telefon)"),
        ("mobil",    "Mobile (mobil)"),
        ("adresse",  "Address (adresse)"),
        ("postnr",   "Postal code (postnr)"),
        ("by",       "City (by)"),
        ("foedselsdato", "Birth date (dd-mm-yyyy)"),
    ]
    data = {}
    for key, label in fields:
        val = input(f"  {label}: ").strip()
        if val:
            data[key] = val
    return data


WELCOME_EMAIL_TEMPLATE = """\
Hej {navn}

Velkommen som medlem af Bredballe IF Padel.

Det er nu muligt at booke spilletider på padelbanerne. Du skal gå ind via https://bredballe.halbooking.dk, hvorefter du øverst til højre vælger punktet LOGIN.

{login_linje}

Her kan du også få tilsendt en ny adgangskode til din email.

Når du er logget ind, så kan du ændre din adgangskode under "Din profil" -> "Login info".


Vedrørende booking:

· Du kan booke spilletider på 60, 90 eller 120 minutter.

· Der skal være min. 2 personer i en booking.

· Ved booking med 2 eller 4 spillere kan den ene vælges som gæstespiller. Gæstespillere betaler via Mobile Pay 88 87 60. Se skilte på banerne.

· Du skal booke spilletid, inden du møder frem for at få adgang til banerne.

· Der vil være adgang 7 minutter før bookningen og 15 minutter efter afslutning af bookningen.

· På indersiden af dørstolpen sidder en kontakt til at låse døren op, når du skal ud igen.

· Lyset på banerne styres automatisk.

· Du modtager en engangs adgangskode pr. mail ved bookningen. Taster du forkert, skal du afvente 3 sec. inden næste forsøg.

· Hvis du har mistet din adgangskode, kan du finde dem i halbookningssystemet.

Anmod om medlemsskab til vores gruppe på Facebook. Her aftaler vi træningstider og deler informationer til medlemmer. https://www.facebook.com/groups/bredballeifpadel

God fornøjelse.
"""

WELCOME_EMAIL_SUBJECT = "Velkommen som medlem af Bredballe IF Padel"


def _send_welcome_email_if_needed(
    bot: HalBookingAutomation,
    conventus_data: dict,
    medlemsnr: str,
    fallback_navn: str,
    password: str = "",
) -> None:
    """Always ensure a welcome email is sent — unless one already exists.

    A welcome email must go out to every new member AND to every existing
    member who is assigned a new membership. Before sending we look at the
    member's "Mails sendt" list (admin_mails.asp) and skip if a welcome email
    was already sent earlier, so re-runs don't double-send.
    """
    navn = conventus_data.get("navn", fallback_navn)
    email = conventus_data.get("email", "?")

    # The membership step uses 'login som medlem' (loginsomklip), so the session
    # is currently browsing AS the member. Drop back to admin context first —
    # this also lands us on the member's admin detail page (admin_konto.asp).
    if not bot.exit_login_som_member():
        # Not in login-som mode — navigate to the detail page the normal way.
        bot.get_member_detail(navn)

    # Check whether a welcome email has already been sent (via 'Mails sendt').
    already_sent = bot.has_welcome_email_been_sent(WELCOME_EMAIL_SUBJECT)
    if already_sent:
        print(f"\n--- Velkomst-email allerede sendt tidligere — springer over ---")
        print(f"  (verificeret via 'Mails sendt' på medlemmets profil)")
        return

    # has_welcome_email_been_sent left us on admin_mails.asp — go back to the
    # detail page (admin search works now that we're in admin context).
    bot.get_member_detail(navn)

    if password:
        login_linje = f'- Dit medlemsnr er {medlemsnr} og din adgangskode er "{password}".'
    else:
        login_linje = f'- Dit medlemsnr er {medlemsnr}.'
    body = WELCOME_EMAIL_TEMPLATE.format(navn=navn, login_linje=login_linje)

    print(f"\n--- Sender velkomst-email via HalBooking ---")
    print("  Til:    [OMITTED]")
    print(f"  Emne:   {WELCOME_EMAIL_SUBJECT}")

    email_result: dict = {"success": False, "steps_completed": []}
    bot._send_email_on_detail_page(bot.page, email_result, WELCOME_EMAIL_SUBJECT, body)

    if email_result.get("success"):
        print(f"  [+] Velkomst-email sendt!")
    else:
        print("  [!] Velkomst-email kunne ikke sendes; indhold/modtager skrives ikke til tool-output.")


def cmd_onboard(bot: HalBookingAutomation, name: str, membership_type: str,
                end_date: str, start_date: str | None = None,
                conventus_data: dict | None = None) -> None:
    """Full SOP onboarding: Conventus lookup → HalBooking create → welcome email."""
    name = reject_broad_query(name)
    print("=== Onboarding ===\n")

    # Step 1: Fetch member info from Conventus. HARD requirement — vi opretter
    # IKKE i HalBooking medmindre medlemmet er verificeret i Conventus (bevis
    # for betalt kontingent). Ingen fallback ved API-fejl.
    if not conventus_data:
        print("--- Henter oplysninger fra Conventus ---", flush=True)
        _script_dir = Path(__file__).resolve().parent
        sys.path.insert(0, str(_script_dir))
        try:
            from conventus_agent import fetch_members, resolve_groups
            print("  [trace] Kalder Conventus API (fetch_members)…", flush=True)
            members = fetch_members(resolve_groups("all"))
            print(f"  [trace] Conventus svarede: {len(members)} medlemmer hentet.", flush=True)
        except Exception as e:
            print(f"  [!] Conventus API fejl: {type(e).__name__}")
            print(f"  [!] AFBRYDER — kan ikke verificere at '{name}' har betalt kontingent.")
            print(f"  [!] Medlem oprettes IKKE i HalBooking.")
            return

        matches = [m for m in members if name.lower() in " ".join(m["navn"].lower().split())]
        if not matches:
            print("  [!] Medlemmet blev ikke fundet i den tilladte Conventus-scope.")
            print(f"  [!] AFBRYDER — medlem er enten ikke registreret eller har ikke betalt.")
            print(f"  [!] Medlem oprettes IKKE i HalBooking.")
            return

        if len(matches) > 1:
            print(f"  [!] Fandt {len(matches)} navne-matches — afbryder; kræver entydigt medlems-id.")
            return
        conventus_data = matches[0]
        print("  [+] Verificeret i Conventus (betalt kontingent); kontaktfelter er udeladt.")
        print()

    # Step 2: Search HalBooking to see if member already exists
    print("--- Starter HalBooking browser ---", flush=True)
    bot.start()
    try:
        print("  [trace] Logger ind i HalBooking…", flush=True)
        if not bot.login():
            print("\n[!] Login til HalBooking fejlede.")
            return
        print("  [trace] Login OK.", flush=True)

        print("--- Søger i HalBooking ---", flush=True)
        search_name = " ".join(conventus_data["navn"].split())  # normalize whitespace
        search_result = bot.search_member(search_name)
        print(f"  [trace] Søgning færdig: search_ok={search_result.get('search_ok')} "
              f"members={len(search_result.get('members', []))}", flush=True)

        # search_ok=False means the search itself failed (page didn't load,
        # results couldn't be parsed). Only then do we abort to avoid dubletter.
        # search_ok=True + no members = legitimate "not found" → proceed to create.
        if not search_result.get("search_ok", False):
            print(f"  [!] Søgning i HalBooking fejlede (search_ok=False) — afbryder.")
            print(f"  [!] Opretter IKKE nyt medlem for at undgå dubletter.")
            print(f"  [!] Kør onboard igen manuelt når HalBooking er tilgængeligt.")
            bot.logout()
            return

        if search_result.get("members"):
            print(f"  Medlem allerede fundet i HalBooking:")
            for m in search_result["members"]:
                parts = [f"{k}: {v}" for k, v in _minimal_member_view(m).items() if v]
                print(f"      {' | '.join(parts)}")
            print()

            # Member exists — assign new membership instead of creating
            print("--- Tildeler nyt medlemskab ---")
            result = bot.assign_membership(
                search_name=search_name,
                membership_type=membership_type,
                end_date=end_date,
                start_date=start_date,
            )

            print(f"\n--- Resultat ---")
            print(f"  Success:          {result.get('success')}")
            print(f"  Medlemsnr:        {result.get('medlemsnr', '?')}")
            print(f"  Steps completed:  {', '.join(result.get('steps_completed', []))}")
            if result.get("warnings"):
                print(f"\n  Advarsler:        {len(result['warnings'])} (indhold udeladt)")
            if result.get("error"):
                print("\n  [!] Fejl: detalje udeladt fra tool-output")

            # Always send a welcome email when a membership was assigned to an
            # existing member (skips automatically if one was already sent).
            medlemsnr = result.get("medlemsnr", "")
            if result.get("success") and medlemsnr:
                _send_welcome_email_if_needed(
                    bot, conventus_data, medlemsnr, name, password=""
                )

            # Logout
            print("\n--- Logger af ---")
            bot.logout()
            return

        # Step 3: Create the member
        print("\n--- Opretter nyt medlem i HalBooking ---")
        result = bot.onboard_new_member(
            navn=search_name,
            mobil=conventus_data.get("mobil", ""),
            email=conventus_data.get("email", ""),
            membership_type=membership_type,
            end_date=end_date,
            start_date=start_date,
        )

        print(f"\n--- Resultat ---")
        print(f"  Success:          {result.get('success')}")
        print(f"  Medlemsnr:        {result.get('medlemsnr', '?')}")
        print("  Adgangskode:      [REDACTED — leveres kun via den sikre velkomstmail]")
        print(f"  Steps completed:  {', '.join(result.get('steps_completed', []))}")

        if result.get("warnings"):
            print(f"\n  Advarsler:        {len(result['warnings'])} (indhold udeladt)")

        if result.get("error"):
            print("\n  [!] Fejl: detalje udeladt fra tool-output")

        # Step 4: Send welcome email via HalBooking (always for new members)
        medlemsnr = result.get("medlemsnr", "")
        if result.get("success") and medlemsnr:
            _send_welcome_email_if_needed(
                bot, conventus_data, medlemsnr, name,
                password=result.get("password", ""),
            )

        # Logout
        print("\n--- Logger af ---")
        bot.logout()

    finally:
        bot.stop()

    print("\n=== Onboarding afsluttet ===\n")


def cmd_welcome_email(bot: HalBookingAutomation, search_name: str) -> None:
    """Resend the welcome email to an existing member via HalBooking's 'Send email' modal.

    Looks up the member, retrieves their medlemsnr, formats the SOP welcome
    email template, and sends it through HalBooking's built-in email feature.
    """
    search_name = reject_broad_query(search_name)
    print("=== Gensender velkomst-email ===\n")
    bot.start()
    try:
        if not bot.login():
            print("\n[!] Login fejlede.")
            return

        # Search for the member and navigate to detail page
        detail_result = bot.get_member_detail(search_name)
        if not detail_result.get("success"):
            print(f"  [!] Medlem '{search_name}' ikke fundet i HalBooking.")
            return

        detail = detail_result.get("member_detail", {})
        medlemsnr = detail.get("Medlemsnr", "")
        email = detail.get("Email", "")
        navn = detail.get("Navn", search_name)

        if not medlemsnr:
            print("  [!] Kunne ikke finde medlemsnr. Afbryder.")
            return

        print(f"  Medlemsnr:  {medlemsnr}")
        print("  Modtager:   [OMITTED]")

        # Format the welcome email (existing members: no password)
        subject = "Velkommen som medlem af Bredballe IF Padel"
        login_linje = f'- Dit medlemsnr er {medlemsnr}.'

        body = WELCOME_EMAIL_TEMPLATE.format(navn=navn, login_linje=login_linje)

        print(f"\n  Emne:       {subject}")
        print(f"  Tekst:      ({len(body)} tegn)")

        # Send via HalBooking — we're already on admin_konto.asp
        result: dict = {"success": False, "steps_completed": []}
        bot._send_email_on_detail_page(bot.page, result, subject, body)

        print(f"\n--- Resultat ---")
        print(f"  Success:          {result.get('success')}")
        print(f"  Steps completed:  {', '.join(result.get('steps_completed', []))}")

        if result.get("error"):
            print("\n  [!] Fejl: detalje udeladt fra tool-output")

        # Logout
        print("\n--- Logger af ---")
        bot.logout()

    finally:
        bot.stop()

    print("\n=== Velkomst-email afsluttet ===\n")


def cmd_history(bot: HalBookingAutomation, search_name: str) -> None:
    """Show full membership history (active + expired) for a member.

    Uses the 'Klippekort/Medlemskaber' page on admin_konto.asp.
    The 'Restklip/udløb' column is the canonical source for the expiry year.
    """
    search_name = reject_broad_query(search_name)
    print(f"=== Medlemskabshistorik for '{search_name}' ===\n")
    bot.start()
    try:
        if not bot.login():
            print("\n[!] Login fejlede.")
            return

        history = bot.get_membership_history(search_name)

        if not history.get("success"):
            print(f"  [!] {history.get('note', 'Ukendt fejl.')}")
            return

        print(f"  Navn:       {history['navn']}")
        print(f"  Medlemsnr:  {history['medlemsnr']}")
        print(f"  Aktive år:  {', '.join(str(y) for y in history['years_active']) or '(ingen)'}")

        active  = history["active"]
        expired = history["expired"]

        print(f"\n--- Aktive medlemskaber ({len(active)}) ---")
        if active:
            for ms in active:
                name  = ms.get("name", "?")
                start = ms.get("start_date", "?")
                end   = ms.get("restklip_date") or ms.get("end_date", "?")
                print(f"  {name:35s}  {start} → {end}")
        else:
            print("  (ingen)")

        print(f"\n--- Udløbne medlemskaber ({len(expired)}) ---")
        if expired:
            for ms in sorted(expired, key=lambda x: x.get("year", 0), reverse=True):
                name  = ms.get("name", "?")
                start = ms.get("start_date", "?")
                end   = ms.get("restklip_date") or ms.get("end_date", "?")
                year  = ms.get("year", "?")
                print(f"  {name:35s}  {start} → {end}  (år {year})  Udløbet")
        else:
            print("  (ingen)")

    finally:
        bot.stop()

    print("\n=== Historik afsluttet ===\n")


def cmd_availability(
    bot: HalBookingAutomation,
    date_str: str,
    time_from: str | None = None,
    time_to: str | None = None,
) -> None:
    """Check which padel courts are free on a date (and optional time window).

    Uses admin_baner.asp: sets #banedato and reads the day grid (one column
    per court: SPORT 24, Sydbank, home Vejle).
    """
    window = ""
    if time_from or time_to:
        window = f" ({time_from or '...'}–{time_to or '...'})"
    print(f"=== Baneoversigt for {date_str}{window} ===\n")
    bot.start()
    try:
        if not bot.login():
            print("\n[!] Login fejlede.")
            return

        result = bot.check_court_availability(
            date_str, time_from=time_from, time_to=time_to
        )

        if not result.get("success"):
            print(f"  [!] {result.get('note', 'Ingen data fundet.')}")
            return

        for court in result["courts"]:
            free = court["free"]
            booked = court["booked"]
            print(f"--- Bane {court['bane']}: {court['name']} ---")
            print(f"  Ledige tider:  {', '.join(free) if free else '(ingen)'}")
            print(f"  Optaget:       {', '.join(booked) if booked else '(ingen)'}")
            for s in court["slots"]:
                mark = "LEDIG " if s["status"] == "free" else "OPTAGET"
                end = f"–{s['end']}" if s["end"] else ""
                print(f"    [{mark}] {s['time']}{end}")
            print()

    finally:
        bot.stop()

    print("=== Baneoversigt afsluttet ===\n")


def cmd_book_court(
    bot: HalBookingAutomation,
    date_str: str,
    court: int,
    start_time: str,
    duration_minutes: int,
    text: str,
) -> None:
    """Create and approve a court booking on admin_straks.asp."""
    print(
        f"=== Opret booking: {date_str} bane {court} {start_time} "
        f"({duration_minutes} min) ===\n"
    )
    bot.start()
    try:
        if not bot.login():
            print("\n[!] Login fejlede.")
            return

        result = bot.create_straks_booking(
            date_str=date_str,
            court=court,
            start_time=start_time,
            duration_minutes=duration_minutes,
            text=text,
        )

        print(f"  Success: {result.get('success')}")
        print(f"  Bane:    {court}")
        print(f"  Tid:     {start_time} - {result.get('end_time', '?')}")
        if text:
            print("  Tekst:   [OMITTED]")
        if result.get("note"):
            print("  Note:    [OMITTED]")

    finally:
        bot.stop()

    print("\n=== Booking-flow afsluttet ===\n")


def cmd_export(bot: HalBookingAutomation, out_file: str | None = None) -> None:
    """Export all HalBooking Padel members to JSON.

    Strategy:
    1. Navigate to admin_findbruger.asp
    2. Set kundegruppe=2 (Padel medlem) via JS and call selskift()
    3. Click 'Alle medlemmer' button (SearchLetter '8') to show all — not just one letter
    4. Paginate through all result pages
    """
    if not out_file:
        raise SystemExit("Masseeksport må kun skrives til en eksplicit privat fil; stdout er blokeret.")
    print("=== HalBooking: Eksporterer alle Padel-medlemmer til privat fil ===")
    bot.start()
    all_members: dict[str, dict] = {}
    try:
        if not bot.login():
            print("[!] Login fejlede.")
            return

        bot.navigate_to_find_user()
        p = bot.page

        # 1. Select 'Padel medlem' group. The underlying <select> is hidden behind a
        #    Bootstrap-Select widget, so set its value via JS then call selskift().
        p.evaluate("document.getElementById('kundegruppe').value = '2'; selskift();")
        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(1500)
        print("  Valgte gruppe: Padel medlem")

        # 2. Click 'Alle medlemmer' button (the one with fa-users icon, letter code '8')
        alle_btn = p.locator('span.btn:has-text("Alle medlemmer")').first
        try:
            if alle_btn.is_visible(timeout=3000):
                alle_btn.click()
                p.wait_for_load_state("networkidle")
                p.wait_for_timeout(1500)
                print("  Klikket 'Alle medlemmer'")
        except Exception:
            print("  Advarsel: kunne ikke klikke 'Alle medlemmer' — fortsætter med nuværende liste")

        # 3. Paginate through all result pages
        page_num = 0
        while True:
            members = bot._extract_member_table()
            for m in members:
                key = m.get("Medlemsnr", "") or m.get("ID", "")
                if key:
                    all_members[key] = m
                else:
                    all_members[str(len(all_members))] = m
            print(f"  Side {page_num + 1}: {len(members)} medlemmer (total: {len(all_members)})")

            if not members:
                break

            # Look for the next-page chevron (single right arrow, not double/last-page)
            # PageSide uses 0-based index, so next page = page_num + 1
            try:
                next_btn = p.locator(
                    f'li:not(.disabled) span.link[onclick*="PageSide({page_num + 1},"]'
                ).first
                if next_btn.is_visible(timeout=1000):
                    next_btn.click()
                    p.wait_for_load_state("networkidle")
                    p.wait_for_timeout(1500)
                    page_num += 1
                else:
                    break
            except Exception:
                break

        print(f"\n  Total: {len(all_members)} Padel-medlemmer fundet")

    finally:
        bot.stop()

    members_list = list(all_members.values())
    output = json.dumps(members_list, ensure_ascii=False, indent=2)
    Path(out_file).write_text(output, encoding="utf-8")
    print("  Eksport gemt i den eksplicit angivne private fil.")


def cmd_preflight(bot: HalBookingAutomation, member_name: str | None = None) -> int:
    """Health-check every dependency required to onboard a member.

    Runs each check independently and prints a PASS/FAIL line so a failing
    workflow log points directly at the broken dependency instead of dying
    deep inside the onboard flow. Returns 0 if all critical checks pass,
    1 otherwise.

    Checks:
      1. Required environment variables / secrets are present.
      2. Conventus API is reachable and returns members.
      3. (optional) A specific member is found in Conventus' active groups.
      4. HalBooking login succeeds + admin page reachable.
      5. Gmail (OAuth) connection works.
    """
    import os
    import time

    results: list[tuple[str, bool, str]] = []  # (label, ok, detail)

    def record(label: str, ok: bool, detail: str = "") -> None:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""), flush=True)
        results.append((label, ok, detail))

    print("=== Preflight: tjekker afhængigheder for medlems-onboarding ===\n", flush=True)

    # --- 1. Required environment variables --------------------------------
    print("--- 1. Miljøvariabler / secrets ---", flush=True)
    required_env = [
        "HALBOOKING_BASE_URL", "HALBOOKING_USERNAME", "HALBOOKING_PASSWORD",
        "CONVENTUS_ID", "CONVENTUS_API_KEY",
        "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN",
        "ADMIN_EMAIL_TO",
    ]
    missing = [k for k in required_env if not os.environ.get(k)]
    record(
        "Alle påkrævede env-vars sat",
        not missing,
        "alle til stede" if not missing else f"mangler: {', '.join(missing)}",
    )

    # --- 2. Conventus API reachable + returns members ---------------------
    print("\n--- 2. Conventus API ---", flush=True)
    conventus_members: list[dict] = []
    try:
        _script_dir = Path(__file__).resolve().parent
        sys.path.insert(0, str(_script_dir))
        from conventus_agent import fetch_members, resolve_groups

        t0 = time.monotonic()
        conventus_members = fetch_members(resolve_groups("all"))
        elapsed = time.monotonic() - t0
        record(
            "Conventus API svarer",
            len(conventus_members) > 0,
            f"{len(conventus_members)} medlemmer hentet på {elapsed:.1f}s",
        )
    except Exception as e:
        record("Conventus API svarer", False, type(e).__name__)

    # --- 3. Optional: specific member present in Conventus ----------------
    if member_name:
        print("\n--- 3. Medlem findes i Conventus ---", flush=True)
        needle = " ".join(member_name.lower().split())
        matches = [
            m for m in conventus_members
            if needle in " ".join(m["navn"].lower().split())
        ]
        if matches:
            m = matches[0]
            record(
                f"'{member_name}' fundet i Conventus",
                True,
                f"id={m.get('id')} grupper={', '.join(m.get('grupper', [])) or '?'}",
            )
        else:
            record(
                f"'{member_name}' fundet i Conventus",
                False,
                "ingen match i aktive 2026-grupper (ikke tilmeldt / ikke betalt?)",
            )

    # --- 4. HalBooking login ----------------------------------------------
    print("\n--- 4. HalBooking login ---", flush=True)
    try:
        bot.start()
        try:
            ok_login = bot.login()
            record("HalBooking login", bool(ok_login),
                   "login lykkedes" if ok_login else "login fejlede (tjek credentials)")
            if ok_login:
                # Verify we can actually reach the find-user admin page.
                try:
                    bot.navigate_to_find_user()
                    record("HalBooking admin-side tilgængelig", True, "admin_findbruger.asp loadede")
                except Exception as e:
                    record("HalBooking admin-side tilgængelig", False, type(e).__name__)
                bot.logout()
        finally:
            bot.stop()
    except Exception as e:
        record("HalBooking login", False, type(e).__name__)

    # --- 5. Gmail (OAuth) connection --------------------------------------
    print("\n--- 5. Gmail forbindelse ---", flush=True)
    try:
        from conventus_email_processor import _build_gmail_service
        service = _build_gmail_service()
        profile = service.users().getProfile(userId="me").execute()
        record(
            "Gmail OAuth + API",
            True,
            f"forbundet som {profile.get('emailAddress', '?')}",
        )
    except Exception as e:
        record("Gmail OAuth + API", False, type(e).__name__)

    # --- Summary ----------------------------------------------------------
    failed = [label for label, ok, _ in results if not ok]
    print("\n" + "=" * 60, flush=True)
    print(f"PREFLIGHT RESULTAT: {len(results) - len(failed)}/{len(results)} checks OK", flush=True)
    print("=" * 60, flush=True)
    if failed:
        print("FEJLEDE CHECKS:", flush=True)
        for label in failed:
            print(f"  ✗ {label}", flush=True)
        print("\n[!] Ikke alle afhængigheder er klar — onboarding vil sandsynligvis fejle.", flush=True)
        return 1

    print("[+] Alle afhængigheder OK — klar til at oprette medlemskab.", flush=True)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="HalBooking member agent")
    parser.add_argument("action", choices=["discover", "search", "create", "onboard", "export", "history", "welcome-email", "process-emails", "preflight", "availability", "book-court"],
                        help="'discover' to inspect the page, 'search' to find a member, "
                             "'create' to add a member, 'onboard' for full SOP workflow, "
                             "'export' to list all Padel members as JSON, "
                             "'history' to show full membership history for a member, "
                             "'welcome-email' to resend the welcome email to an existing member, "
                             "'process-emails' to scan Gmail for Conventus notifications and auto-onboard, "
                             "'preflight' to health-check all dependencies needed to onboard a member, "
                             "'availability' to check which padel courts are free on a date/time, "
                             "'book-court' to create and approve a court booking")
    parser.add_argument("--name", type=str, default=None,
                        help="Member name to search for (for 'search' and 'onboard')")
    parser.add_argument("--detail", action="store_true",
                        help="Open full detail view for the matched member (for 'search')")
    parser.add_argument("--json", type=str, default=None,
                        help="Path to a JSON file with member data (for 'create')")
    parser.add_argument("--type", type=str, default="prime", choices=["prime", "non-prime"],
                        help="Membership type: 'prime' or 'non-prime' (for 'onboard', default: prime)")
    parser.add_argument("--end-date", type=str, default="31-12-2026",
                        help="Membership end date, e.g. '31-12-2026' (for 'onboard')")
    parser.add_argument("--start-date", type=str, default=None,
                        help="Membership start date, e.g. '01-07-2026' (for 'onboard', default: 01-01 of end year)")
    parser.add_argument("--visible", action="store_true",
                        help="Show the browser window (non-headless)")
    parser.add_argument("--date", type=str, default=None,
                        help="Date to check, format DD-MM-YYYY (for 'availability')")
    parser.add_argument("--time-from", dest="time_from", type=str, default=None,
                        help="Lower time bound HH:MM, inclusive (for 'availability')")
    parser.add_argument("--time-to", dest="time_to", type=str, default=None,
                        help="Upper time bound HH:MM, exclusive (for 'availability')")
    parser.add_argument("--court", type=int, default=1,
                        help="Court number 1..3 (for 'book-court')")
    parser.add_argument("--start-time", dest="start_time", type=str, default=None,
                        help="Start time HH:MM (for 'book-court')")
    parser.add_argument("--duration", type=int, default=60,
                        help="Duration in minutes, multiple of 30 (for 'book-court')")
    parser.add_argument("--text", type=str, default="",
                        help="Booking text, e.g. 'Jesper tester' (for 'book-court')")
    parser.add_argument("--test-name", type=str, default=None,
                        help="(process-emails only) Test mode: full member name to onboard. Skips Gmail search.")
    parser.add_argument("--test-hold", type=str, default=None,
                        help="(process-emails only) Test mode: Conventus hold-navn, fx 'Padel: Jan-Juni 2026 (non-prime)'.")
    args = parser.parse_args()

    approval_actions = {
        "discover": "halbooking.diagnostic-export",
        "create": "halbooking.member.create",
        "onboard": "onboarding.onboard",
        "export": "halbooking.bulk-read",
        "welcome-email": "halbooking.email.send",
        "process-emails": "onboarding.process-emails",
        "book-court": "halbooking.court.book",
    }
    approval = None
    if args.action in approval_actions:
        try:
            approval = require_write_approval(approval_actions[args.action])
            if args.action == "process-emails":
                approval.require("onboarding.onboard")
        except PolicyViolation as exc:
            parser.error(str(exc))
        emit_audit_event(audit_event(
            approval_actions[args.action], "approved", record_count=1,
            actor_role=approval.actor_role, correlation_id=approval.correlation_id,
        ))

    if args.name:
        try:
            args.name = reject_broad_query(args.name)
        except PolicyViolation as exc:
            parser.error(str(exc))

    bot = HalBookingAutomation(headless=not args.visible)

    if args.action == "discover":
        cmd_discover(bot)

    elif args.action == "search":
        name = args.name
        if not name:
            name = input("Enter member name to search for: ").strip()
        if not name:
            print("[!] No search name provided. Aborting.")
            sys.exit(1)
        cmd_search(bot, name, show_detail=args.detail)

    elif args.action == "create":
        if args.json:
            member_data = json.loads(Path(args.json).read_text(encoding="utf-8"))
        else:
            member_data = interactive_member_input()

        if not member_data:
            print("[!] No member data provided. Aborting.")
            sys.exit(1)

        cmd_create(bot, member_data)

    elif args.action == "onboard":
        name = args.name
        if not name:
            name = input("Indtast medlemsnavn: ").strip()
        if not name:
            print("[!] Intet navn angivet. Afbryder.")
            sys.exit(1)
        cmd_onboard(bot, name, membership_type=args.type, end_date=args.end_date, start_date=args.start_date)

    elif args.action == "export":
        cmd_export(bot, out_file=args.json)

    elif args.action == "history":
        name = args.name
        if not name:
            name = input("Indtast medlemsnavn: ").strip()
        if not name:
            print("[!] Intet navn angivet. Afbryder.")
            sys.exit(1)
        cmd_history(bot, name)

    elif args.action == "welcome-email":
        name = args.name
        if not name:
            name = input("Indtast medlemsnavn: ").strip()
        if not name:
            print("[!] Intet navn angivet. Afbryder.")
            sys.exit(1)
        cmd_welcome_email(bot, name)

    elif args.action == "process-emails":
        from conventus_email_processor import process_emails, process_test
        if args.test_name or args.test_hold:
            if not (args.test_name and args.test_hold):
                print("[!] Test mode kræver BÅDE --test-name og --test-hold.")
                sys.exit(2)
            sys.exit(process_test(args.test_name, args.test_hold))
        sys.exit(process_emails())

    elif args.action == "preflight":
        sys.exit(cmd_preflight(bot, member_name=args.name))

    elif args.action == "availability":
        date_str = args.date
        if not date_str:
            date_str = input("Indtast dato (DD-MM-YYYY): ").strip()
        if not date_str:
            print("[!] Ingen dato angivet. Afbryder.")
            sys.exit(1)
        cmd_availability(bot, date_str, time_from=args.time_from, time_to=args.time_to)

    elif args.action == "book-court":
        date_str = args.date
        if not date_str:
            date_str = input("Indtast dato (DD-MM-YYYY): ").strip()
        if not date_str:
            print("[!] Ingen dato angivet. Afbryder.")
            sys.exit(1)

        start_time = args.start_time
        if not start_time:
            start_time = input("Indtast starttid (HH:MM): ").strip()
        if not start_time:
            print("[!] Ingen starttid angivet. Afbryder.")
            sys.exit(1)

        cmd_book_court(
            bot,
            date_str=date_str,
            court=args.court,
            start_time=start_time,
            duration_minutes=args.duration,
            text=args.text,
        )


if __name__ == "__main__":
    main()
