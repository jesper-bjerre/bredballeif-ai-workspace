"""
Read-only padel court availability agent for HalBooking.

The agent logs in with a read-only HalBooking user and reports which padel
courts (SPORT 24, Sydbank, home Vejle) are free on a given date and optional
time window. It never creates, edits, books or deletes anything.

Usage:
  python -m agent availability --date 05-07-2026
  python -m agent availability --date 05-07-2026 --time-from 18:00 --time-to 20:00
  python -m agent availability --date 05-07-2026 --visible   # show the browser
  python -m agent book-court --date 28-06-2026 --court 1 --start-time 19:00 --duration 60 --text "Booking"
  python -m agent book-court --date 28-06-2026 --court 1 --start-time 19:00 --end-time 20:00 --text "Booking"
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from halbooking_automation import HalBookingAutomation

_WEEKDAYS_DA = [
    "mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag",
]


def _weekday_da(date_str: str) -> str:
    """Return the Danish weekday name for a DD-MM-YYYY date, or '' if invalid."""
    try:
        d = datetime.strptime(date_str, "%d-%m-%Y").date()
    except ValueError:
        return ""
    return _WEEKDAYS_DA[d.weekday()]


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
    weekday = _weekday_da(date_str)
    day_label = f"{weekday} {date_str}" if weekday else date_str
    print(f"=== Baneoversigt for {day_label}{window} ===\n")
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

        courts = result["courts"]
        for court in courts:
            free = court["free"]
            booked = court["booked"]
            print(f"--- Bane {court['bane']}: {court['name']} ---")
            print(f"  Ledige tider:  {', '.join(free) if free else '(ingen)'}")
            print(f"  Optaget:       {', '.join(booked) if booked else '(ingen)'}")
            for s in court["slots"]:
                mark = "LEDIG " if s["status"] == "free" else "OPTAGET"
                end = f"–{s['end']}" if s["end"] else ""
                label = f"  {s['label']}" if s["label"] else ""
                print(f"    [{mark}] {s['time']}{end}{label}")
            print()

        # --- Explicit summary so the answer can't be miscounted ---
        # A court is "fully free" for the window only if NO slot is booked.
        total = len(courts)
        fully_free = [c for c in courts if not c["booked"]]
        occupied = [c for c in courts if c["booked"]]
        span = window.strip() or "hele dagen"
        print(f"--- OPSUMMERING {span} ---")
        print(
            f"  Ledige baner:  {len(fully_free)} af {total}"
            + (f"  -> {', '.join(c['name'] for c in fully_free)}" if fully_free else "")
        )
        print(
            f"  Optaget:       {len(occupied)} af {total}"
            + (f"  -> {', '.join(c['name'] for c in occupied)}" if occupied else "")
        )
        print()

    finally:
        bot.stop()

    print("=== Baneoversigt afsluttet ===\n")


def _parse_clock_minutes(clock: str) -> int:
    """Parse HH:MM into total minutes since midnight. Raises ValueError on bad input."""
    h, m = clock.strip().split(":")
    return int(h) * 60 + int(m)


def cmd_book_court(
    bot: HalBookingAutomation,
    date_str: str,
    court: int,
    start_time: str,
    duration_minutes: int | None = None,
    end_time: str | None = None,
    text: str = "",
) -> None:
    """Create and approve a court booking on admin_straks.asp.

    Either *duration_minutes* or *end_time* (HH:MM) must be given.
    If both are given, *end_time* takes precedence.
    """
    if end_time:
        duration_minutes = _parse_clock_minutes(end_time) - _parse_clock_minutes(start_time)
        if duration_minutes <= 0:
            print(f"[!] Sluttid {end_time} er før eller lig starttid {start_time}. Afbryder.")
            return

    if duration_minutes is None:
        print("[!] Angiv enten --duration eller --end-time. Afbryder.")
        return

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
            print(f"  Tekst:   {text}")
        if result.get("note"):
            print(f"  Note:    {result['note']}")

    finally:
        bot.stop()

    print("\n=== Booking-flow afsluttet ===\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Padel court availability & booking agent for HalBooking"
    )
    parser.add_argument(
        "action",
        choices=["availability", "book-court"],
        help="'availability' to check court availability, 'book-court' to create a booking",
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Date, format DD-MM-YYYY",
    )
    parser.add_argument(
        "--time-from", dest="time_from", type=str, default=None,
        help="Lower time bound HH:MM, inclusive (for 'availability')",
    )
    parser.add_argument(
        "--time-to", dest="time_to", type=str, default=None,
        help="Upper time bound HH:MM, exclusive (for 'availability')",
    )
    parser.add_argument(
        "--court", type=int, default=None,
        help="Court number 1-3 (for 'book-court')",
    )
    parser.add_argument(
        "--start-time", dest="start_time", type=str, default=None,
        help="Booking start time HH:MM (for 'book-court')",
    )
    parser.add_argument(
        "--duration", type=int, default=None,
        help="Booking duration in minutes, multiple of 30 (for 'book-court'). "
             "Use --end-time instead if you know start+end clock times.",
    )
    parser.add_argument(
        "--end-time", dest="end_time", type=str, default=None,
        help="Booking end time HH:MM — alternative to --duration (for 'book-court'). "
             "Duration is auto-calculated from --start-time.",
    )
    parser.add_argument(
        "--text", type=str, default="",
        help="Booking text/label (for 'book-court')",
    )
    parser.add_argument(
        "--visible", action="store_true",
        help="Show the browser window (non-headless)",
    )
    args = parser.parse_args()

    bot = HalBookingAutomation(headless=not args.visible)

    if args.action == "availability":
        date_str = args.date
        if not date_str:
            date_str = input("Indtast dato (DD-MM-YYYY): ").strip()
        if not date_str:
            print("[!] Ingen dato angivet. Afbryder.")
            sys.exit(1)
        cmd_availability(bot, date_str, time_from=args.time_from, time_to=args.time_to)

    elif args.action == "book-court":
        if not args.date:
            print("[!] --date er påkrævet for book-court. Afbryder.")
            sys.exit(1)
        if not args.court:
            print("[!] --court er påkrævet for book-court. Afbryder.")
            sys.exit(1)
        if not args.start_time:
            print("[!] --start-time er påkrævet for book-court. Afbryder.")
            sys.exit(1)
        if not args.duration and not args.end_time:
            print("[!] Enten --duration eller --end-time er påkrævet. Afbryder.")
            sys.exit(1)
        if not args.text:
            print("[!] --text er påkrævet for book-court. Afbryder.")
            sys.exit(1)
        cmd_book_court(
            bot,
            date_str=args.date,
            court=args.court,
            start_time=args.start_time,
            duration_minutes=args.duration,
            end_time=args.end_time,
            text=args.text,
        )


if __name__ == "__main__":
    main()
