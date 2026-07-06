"""
Read-only padel court availability agent for HalBooking.

The agent logs in with a read-only HalBooking user and reports which padel
courts (SPORT 24, Sydbank, home Vejle) are free on a given date and optional
time window. It never creates, edits, books or deletes anything.

Usage:
  python -m agent availability --date 05-07-2026
  python -m agent availability --date 05-07-2026 --time-from 18:00 --time-to 20:00
  python -m agent availability --date 05-07-2026 --visible   # show the browser
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only padel court availability agent for HalBooking"
    )
    parser.add_argument(
        "action",
        choices=["availability"],
        help="'availability' to check which padel courts are free on a date/time",
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Date to check, format DD-MM-YYYY (for 'availability')",
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


if __name__ == "__main__":
    main()
