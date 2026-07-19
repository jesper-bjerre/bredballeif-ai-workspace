r"""
Cross-reference Conventus members with HalBooking active memberships.

Usage (from skill root):
  $env:PYTHONPATH = ".\scripts"
  python .\scripts\analyze_memberships.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_script_dir))

from conventus_agent import fetch_members, resolve_groups
from halbooking_automation import HalBookingAutomation


def main() -> None:
    # Step 1: Fetch all Conventus members
    print("=== Henter alle Conventus padel-medlemmer ===\n")
    conventus_members = fetch_members(resolve_groups("all"))
    print(f"  Fandt {len(conventus_members)} medlemmer i Conventus\n")

    # Step 2: Start HalBooking and check each member
    print("=== Krydstjekker med HalBooking ===\n")
    bot = HalBookingAutomation(headless=True)
    bot.start()

    if not bot.login():
        print("[!] Login til HalBooking fejlede.")
        bot.stop()
        return

    results: list[dict] = []

    for i, cm in enumerate(conventus_members):
        navn = cm["navn"]
        conventus_grupper = ", ".join(cm["grupper"]) if cm["grupper"] else "?"
        print(f"  [{i+1:3d}/{len(conventus_members)}] {navn:40s} ", end="", flush=True)

        try:
            search_result = bot.search_member(navn)

            if not search_result["success"] or not search_result.get("members"):
                print("IKKE FUNDET i HalBooking")
                results.append({
                    "navn": navn,
                    "conventus_gruppe": conventus_grupper,
                    "halbooking_status": "IKKE FUNDET",
                    "hb_medlemsnr": "",
                    "active_memberships": [],
                })
                continue

            # Member found — check detail page for active memberships
            detail = search_result.get("member_detail", {})
            medlemsnr = detail.get("Medlemsnr", "?")

            # Navigate to klippekort if we're on the detail page
            active_ms = []
            if "admin_konto" in bot.page.url:
                active_ms = bot._extract_active_memberships()

            if active_ms:
                ms_names = "; ".join(
                    f"{m.get('name', '?')} ({m.get('period', '?')})" for m in active_ms
                )
                print(f"OK  #{medlemsnr}  {ms_names}")
                status = "OK"
            else:
                print(f"MANGLER MEDLEMSKAB  #{medlemsnr}")
                status = "MANGLER MEDLEMSKAB"

            results.append({
                "navn": navn,
                "conventus_gruppe": conventus_grupper,
                "halbooking_status": status,
                "hb_medlemsnr": medlemsnr,
                "active_memberships": active_ms,
            })

        except Exception as e:
            print(f"FEJL: {type(e).__name__}")
            results.append({
                "navn": navn,
                "conventus_gruppe": conventus_grupper,
                "halbooking_status": f"FEJL: {type(e).__name__}",
                "hb_medlemsnr": "",
                "active_memberships": [],
            })

    bot.logout()
    bot.stop()

    # Step 3: Print summary
    ok = [r for r in results if r["halbooking_status"] == "OK"]
    missing_ms = [r for r in results if r["halbooking_status"] == "MANGLER MEDLEMSKAB"]
    not_found = [r for r in results if r["halbooking_status"] == "IKKE FUNDET"]
    errors = [r for r in results if r["halbooking_status"].startswith("FEJL")]

    print(f"\n{'='*80}")
    print(f"ANALYSE: Conventus → HalBooking krydstjek")
    print(f"{'='*80}")
    print(f"  Conventus medlemmer:             {len(conventus_members)}")
    print(f"  Aktivt medlemskab i HalBooking:  {len(ok)}")
    print(f"  Mangler medlemskab:              {len(missing_ms)}")
    print(f"  Ikke fundet i HalBooking:        {len(not_found)}")
    print(f"  Fejl:                            {len(errors)}")

    if missing_ms:
        print(f"\n{'─'*80}")
        print("MANGLER AKTIVT MEDLEMSKAB I HALBOOKING:")
        print(f"{'─'*80}")
        for r in missing_ms:
            print(f"  #{r['hb_medlemsnr']:>6s}  {r['navn']:40s}  Conventus: {r['conventus_gruppe']}")

    if not_found:
        print(f"\n{'─'*80}")
        print("IKKE FUNDET I HALBOOKING (skal oprettes):")
        print(f"{'─'*80}")
        for r in not_found:
            print(f"          {r['navn']:40s}  Conventus: {r['conventus_gruppe']}")

    if errors:
        print(f"\n{'─'*80}")
        print("FEJL UNDER OPSLAG:")
        print(f"{'─'*80}")
        for r in errors:
            print(f"  {r['navn']:40s}  {r['halbooking_status']}")

    print(f"\n{'='*80}")


if __name__ == "__main__":
    main()
