"""
CLI agent for querying the Conventus membership API.

Usage:
  python conventus_agent.py search --name "Jensen"
  python conventus_agent.py list --group prime
  python conventus_agent.py list --group all
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Ensure UTF-8 output on Windows terminals (fixes Danish chars æ/ø/å)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import xml.etree.ElementTree as ET
from pathlib import Path

from dotenv import load_dotenv

# Repo-fælles fail-closed kontroller. Direkte `python -m agent` fra skill-mappen
# understøttes fortsat ved at lokalisere workspace-roden relativt.
for _parent in Path(__file__).resolve().parents:
    if (_parent / "scripts" / "gdpr_controls.py").exists():
        sys.path.insert(0, str(_parent / "scripts"))
        break

from gdpr_controls import (  # noqa: E402
    ApprovalContext,
    PolicyViolation,
    audit_event,
    emit_audit_event,
    enforce_record_limit,
    reject_broad_query,
    require_write_approval,
)

# Load .env from project root (walk up from this script's location)
_script_dir = Path(__file__).resolve().parent
for _candidate in [_script_dir, *_script_dir.parents]:
    if (_candidate / ".env").exists():
        load_dotenv(_candidate / ".env")
        break

CONVENTUS_ID = os.environ.get("CONVENTUS_ID", "")
CONVENTUS_API_KEY = os.environ.get("CONVENTUS_API_KEY", "")

API_URL = "https://www.conventus.dk/dataudv/api/adressebog/get_grupper_medlemmer.php"

GROUP_ALIASES: dict[str, list[str]] = {
    "prime":        ["1019486", "1019508", "1046242"],
    "non-prime":    ["1019513", "1019517", "1046244"],
    "hele-2026":    ["1019486", "1019513"],
    "jan-jun-2026": ["1019508", "1019517"],
    "all":          ["1019486", "1019508", "1019513", "1019517", "1046242", "1046244"],
    # Year-based aliases
    "2021":         ["704445", "704446", "720175"],
    "2022":         ["704445", "704446", "720175"],
    "2023":         ["704445", "791184", "854985"],
    "2024":         ["893985", "939685", "893982", "791187"],
    "2025":         ["959495", "959479", "959497", "959502", "959496", "959493"],
    "2026":         ["1019486", "1019508", "1019513", "1019517", "1046242", "1046244"],
}

GROUP_NAMES: dict[str, str] = {
    # 2026
    "1019486": "Padel: Hele 2026 (prime)",
    "1019508": "Padel: Januar-Juni 2026 (prime)",
    "1019513": "Padel: Hele 2026 (non-prime)",
    "1019517": "Padel: Jan-Juni 2026 (non-prime)",
    "1046242": "Padel: Resten af 2026 (prime)",
    "1046244": "Padel: Resten af 2026 (non-prime)",
    # 2025
    "959495":  "Padel: Hele 2025 (prime)",
    "959479":  "Padel: Januar-Juni 2025 (prime)",
    "959497":  "Padel: Juli-December 2025 (prime)",
    "959502":  "Padel: Hele 2025 (non-prime)",
    "959496":  "Padel: Januar-Juni 2025 (non-prime)",
    "959493":  "Padel: Juli-December 2025 (non-prime)",
    # 2024
    "893985":  "Padel: Hele 2024 (prime)",
    "939685":  "Padel: Juli-December 2024 (prime)",
    "893982":  "Padel: Hele 2024 (non-prime)",
    # 2023
    "791184":  "Padel: Hele 2023 (prime)",
    "854985":  "Padel: Hele 2023 B (prime)",
    "791187":  "Padel: Hele 2024 børn (non-prime)",
    # 2021-2023
    "704445":  "Padel: Hele 2021, 2022 og 2023 (prime)",
    "704446":  "Padel: Hele 2021 og 2022 (prime)",
    "720175":  "Padel: Hele 2021 og 2022 B (prime)",
}

# Groups that count toward each year (members in any of these groups were active that year)
YEAR_GROUPS: dict[int, list[str]] = {
    2021: ["704445", "704446", "720175"],
    2022: ["704445", "704446", "720175"],   # same packages — flersæson-kontingent
    2023: ["704445", "791184", "854985"],
    2024: ["893985", "939685", "893982", "791187"],
    2025: ["959495", "959479", "959497", "959502", "959496", "959493"],
    2026: ["1019486", "1019508", "1019513", "1019517", "1046242", "1046244"],
}

def fetch_members(group_ids: list[str], timeout: float = 180.0, retries: int = 5) -> list[dict]:
    """Fetch members from the Conventus API for the given group IDs.

    Raises RuntimeError if the API is unreachable after the given retries.
    Callers MUST treat this exception as fatal — falling back to manual data
    would bypass the "member has paid in Conventus" verification.
    """
    if not CONVENTUS_ID or not CONVENTUS_API_KEY:
        raise RuntimeError("CONVENTUS_ID and CONVENTUS_API_KEY must be set (env or .env)")

    groups_param = ",".join(group_ids)
    url = f"{API_URL}?forening={CONVENTUS_ID}&key={CONVENTUS_API_KEY}&grupper={groups_param}"

    last_err: Exception | None = None
    xml_data: str | None = None
    for attempt in range(retries + 1):
        try:
            resp = urllib.request.urlopen(url, timeout=timeout)  # noqa: S310 — URL from config
            xml_data = resp.read().decode("utf-8")
            break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < retries:
                wait = min(2 ** attempt, 30)  # 1s, 2s, 4s, 8s, 16s (capped at 30s)
                print(
                    f"[!] Conventus API fejl (forsøg {attempt+1}/{retries+1}), "
                    f"prøver igen om {wait}s: {type(e).__name__}"
                )
                time.sleep(wait)

    if xml_data is None:
        raise RuntimeError(
            f"Conventus API kunne ikke nås efter {retries+1} forsøg "
            f"({type(last_err).__name__ if last_err else 'ukendt fejl'})."
        )

    root = ET.fromstring(xml_data)

    # Build group membership map: member_id -> list of group IDs
    group_map: dict[str, list[str]] = {}
    for gruppe in root.findall(".//relationer/gruppe"):
        gid = gruppe.findtext("id", "")
        for m in gruppe.findall("medlem/medlem"):
            mid = m.text or ""
            group_map.setdefault(mid, []).append(gid)

    # Parse member details
    members = []
    for medlem in root.findall(".//medlemmer/medlem"):
        mid = medlem.findtext("id", "")
        member = {
            "id": mid,
            "type": medlem.findtext("type", ""),
            "koen": medlem.findtext("koen", ""),
            "navn": medlem.findtext("navn", ""),
            "adresse1": medlem.findtext("adresse1", ""),
            "adresse2": medlem.findtext("adresse2", ""),
            "postnr": medlem.findtext("postnr", ""),
            "by": medlem.findtext("postnr_by", ""),
            "kommune": medlem.findtext("kommune_navn", ""),
            "tlf": medlem.findtext("tlf", ""),
            "mobil": medlem.findtext("mobil", ""),
            "email": medlem.findtext("email", ""),
            "foedselsdato": medlem.findtext("birth", ""),
            "indmeldelsesdato": medlem.findtext("indmeldelsesdato", ""),
            "slettet": medlem.findtext("slettet", ""),
            "grupper": [GROUP_NAMES.get(g, g) for g in group_map.get(mid, [])],
            "grupper_ids": group_map.get(mid, []),
        }
        members.append(member)

    return members


def resolve_groups(group_arg: str) -> list[str]:
    """Resolve a group alias or comma-separated IDs to a list of group IDs."""
    if group_arg in GROUP_ALIASES:
        return GROUP_ALIASES[group_arg]
    return [g.strip() for g in group_arg.split(",")]


def print_member(m: dict, verbose: bool = False) -> None:
    """Print a single member's details."""
    if verbose:
        # Felt-allowlist: adresser, fødselsdato, køn og øvrige rå API-felter
        # sendes ikke videre til stdout/LLM-kontekst ved et almindeligt opslag.
        allowed = ("id", "navn", "grupper")
        max_key = max(len(k) for k in allowed)
        for k in allowed:
            v = m.get(k, "")
            if k == "grupper":
                v = ", ".join(v) if v else "(ingen)"
            if v:
                print(f"  {k:{max_key}s}  {v}")
        print()
    else:
        grupper = ", ".join(m["grupper"]) if m["grupper"] else ""
        print(f"  {m['id']:>8s}  {m['navn']:35s}  {grupper}")


def cmd_search(args: argparse.Namespace) -> None:
    """Search for members by name."""
    try:
        search_term = reject_broad_query(args.name)
    except PolicyViolation as exc:
        raise SystemExit(str(exc)) from exc
    group_ids = resolve_groups(args.group)
    members = fetch_members(group_ids)

    matches = [m for m in members if search_term.lower() in m["navn"].lower()]
    try:
        matches = enforce_record_limit(matches, limit=args.limit, bulk_approved=False)
    except PolicyViolation as exc:
        raise SystemExit(str(exc)) from exc

    print(f"=== Conventus: Søger '{args.name}' i {len(members)} medlemmer ===\n")
    if not matches:
        print("  Ingen medlemmer fundet.")
        return

    print(f"  Fandt {len(matches)} medlem(mer):\n")
    for m in matches:
        print_member(m, verbose=True)


def cmd_list(args: argparse.Namespace) -> None:
    """List all members in a group."""
    group_ids = resolve_groups(args.group)
    members = fetch_members(group_ids)

    bulk_approved = False
    if args.approve_bulk:
        try:
            ApprovalContext.from_environment().require("conventus.bulk-read")
            bulk_approved = True
        except PolicyViolation as exc:
            raise SystemExit(str(exc)) from exc
    try:
        members = enforce_record_limit(members, limit=args.limit, bulk_approved=bulk_approved)
    except PolicyViolation as exc:
        raise SystemExit(str(exc)) from exc

    group_label = args.group if args.group in GROUP_ALIASES else ", ".join(group_ids)
    print(f"=== Conventus: {len(members)} medlemmer i '{group_label}' ===\n")
    print(f"  {'ID':>8s}  {'Navn':35s}  {'Email':35s}  {'Mobil':12s}  Grupper")
    print(f"  {'-'*8}  {'-'*35}  {'-'*35}  {'-'*12}  {'-'*30}")
    for m in sorted(members, key=lambda x: x["navn"]):
        print_member(m)

    print(f"\n  Total: {len(members)} medlemmer")


def cmd_stats(args: argparse.Namespace) -> None:  # noqa: ARG001
    """Show membership count statistics per year with churn/retention analysis."""
    all_group_ids = list({gid for ids in YEAR_GROUPS.values() for gid in ids})
    members = fetch_members(all_group_ids)

    # Build year → unique member ID set
    year_sets: dict[int, set[str]] = {
        year: {m["id"] for m in members if set(gids) & set(m["grupper_ids"])}
        for year, gids in sorted(YEAR_GROUPS.items())
    }
    years = sorted(year_sets)
    all_ids = {m["id"] for m in members}

    print("=== Padel Membership Statistics (2021-2026) ===\n")
    print(f"  {'År':>4}  {'Medlemmer':>9}  {'Ny':>5}  {'Forblev':>8}  {'Forlod':>7}  {'Fastholdelse':>14}")
    print(f"  {'-'*4}  {'-'*9}  {'-'*5}  {'-'*8}  {'-'*7}  {'-'*14}")

    prev_ids: set[str] | None = None
    prev_year: int | None = None
    notes: list[str] = []

    for year in years:
        ids = year_sets[year]
        total = len(ids)
        note = ""

        if prev_ids is None:
            new_s, ret_s, churn_s, pct_s = str(total), "–", "–", "–"
        else:
            if set(YEAR_GROUPS[year]) == set(YEAR_GROUPS[prev_year]):  # type: ignore[arg-type]
                note = " *"
                if not notes:
                    notes.append(
                        f"* År {prev_year} og {year} benytter de samme Conventus-grupper "
                        "(flersæson-kontingent) — churn kan ikke beregnes for dette skifte."
                    )
            retained = ids & prev_ids
            churned = prev_ids - ids
            new_members = ids - prev_ids
            new_s = str(len(new_members))
            ret_s = str(len(retained))
            churn_s = str(len(churned))
            pct_s = f"{100 * len(retained) / len(prev_ids):.1f}%" if prev_ids else "–"

        print(f"  {year:>4}  {total:>9}  {new_s:>5}  {ret_s:>8}  {churn_s:>7}  {pct_s:>14}{note}")
        prev_ids = ids
        prev_year = year

    print(f"\n  Total unikke medlemmer (alle år): {len(all_ids)}")
    if notes:
        print()
        for n in notes:
            print(f"  {n}")


def _normalize_name(name: str) -> str:
    """Lowercase, strip, collapse spaces — for fuzzy name matching."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", name.lower().strip())
    return " ".join("".join(c for c in nfkd if not unicodedata.combining(c)).split())


def cmd_compare(args: argparse.Namespace) -> None:  # noqa: ARG001
    """Compare all Conventus members against HalBooking and show differences."""
    print("[!] Cross-system compare kræver HalBooking automation.")
    print("    Brug bredballeif-padel-halbooking/analyze_memberships.py eller bredballeif-padel-halbooking export + bredballeif-padel-conventus stats.")


def cmd_create_americano(args: argparse.Namespace) -> None:
    """Create an Americano event group in Conventus via browser automation."""
    approval = require_write_approval("conventus.create-group")
    emit_audit_event(audit_event(
        "conventus.group.create", "approved", record_count=1,
        actor_role=approval.actor_role, correlation_id=approval.correlation_id,
    ))
    from conventus_group_automation import create_americano

    result = create_americano(
        title=args.title,
        date=args.date,
        max_participants=args.max,
        description=args.description,
        price=args.price,
        headless=not args.no_headless,
    )
    if result.success:
        print(f"\n✅ Americano oprettet!")
        print(f"   Gruppe ID: {result.group_id}")
        print(f"   Edit URL:  {result.edit_url}")
    else:
        print(f"\n❌ Fejl: {result.error}")
        sys.exit(1)


def cmd_create_mexicano(args: argparse.Namespace) -> None:
    """Create a Mexicano event group in Conventus via browser automation (duplicates template)."""
    approval = require_write_approval("conventus.create-group")
    emit_audit_event(audit_event(
        "conventus.group.create", "approved", record_count=1,
        actor_role=approval.actor_role, correlation_id=approval.correlation_id,
    ))
    from conventus_group_automation import create_mexicano

    result = create_mexicano(
        title=args.title,
        date=args.date,
        max_participants=args.max,
        description=args.description,
        price=args.price,
        headless=not args.no_headless,
    )
    if result.success:
        print(f"\n✅ Mexicano oprettet!")
        print(f"   Gruppe ID: {result.group_id}")
        print(f"   Edit URL:  {result.edit_url}")
    else:
        print(f"\n❌ Fejl: {result.error}")
        sys.exit(1)


def cmd_create_group(args: argparse.Namespace) -> None:
    """Create a generic group in Conventus via browser automation."""
    approval = require_write_approval("conventus.create-group")
    emit_audit_event(audit_event(
        "conventus.group.create", "approved", record_count=1,
        actor_role=approval.actor_role, correlation_id=approval.correlation_id,
    ))
    from conventus_group_automation import ConventusGroupAutomation, GroupConfig

    config = GroupConfig(
        title=args.title,
        date_from=args.date_from,
        date_to=args.date_to or args.date_from,
        department_id=args.department,
        activity_id=args.activity,
        max_participants=args.max,
        description=args.description,
        price=args.price,
        public=not args.no_public,
        waiting_list=not args.no_waiting_list,
        payment_required=not args.no_payment,
    )

    auto = ConventusGroupAutomation(headless=not args.no_headless)
    try:
        auto.start()
        if not auto.login():
            print("❌ Login fejlede")
            sys.exit(1)
        result = auto.create_group(config)
        if result.success and result.group_id:
            auto.edit_group(result.group_id, config)
        if result.success:
            print(f"\n✅ Gruppe oprettet! ID: {result.group_id}")
            print(f"   Edit URL: {result.edit_url}")
        else:
            print(f"\n❌ Fejl: {result.error}")
            sys.exit(1)
    finally:
        auto.stop()


def cmd_budget_report(args: argparse.Namespace) -> None:
    """Fetch a read-only income statement through Conventus browser automation."""
    from conventus_budget_automation import fetch_budget_report, print_report

    report = fetch_budget_report(
        department=args.department,
        year_count=args.years,
        headless=not args.no_headless,
    )
    print_report(report)


def main() -> None:
    parser = argparse.ArgumentParser(description="Conventus membership query agent")
    sub = parser.add_subparsers(dest="action", required=True)

    p_search = sub.add_parser("search", help="Search for a member by name")
    p_search.add_argument("--name", required=True, help="Name (or part of name) to search for")
    p_search.add_argument("--group", default="all", help="Group alias or comma-separated IDs (default: all)")
    p_search.add_argument("--limit", type=int, default=10, choices=range(1, 11), metavar="1..10")

    p_list = sub.add_parser("list", help="List all members in a group")
    p_list.add_argument("--group", default="all", help="Group alias or comma-separated IDs (default: all)")
    p_list.add_argument("--limit", type=int, default=10, help="Maksimalt antal poster (default: 10)")
    p_list.add_argument(
        "--approve-bulk", action="store_true",
        help="Kræver samtidig tidsbegrænset conventus.bulk-read-godkendelse fra gatewayen",
    )

    sub.add_parser("stats", help="Show membership statistics per year with churn analysis (2021-2026)")
    sub.add_parser("compare", help="Compare Conventus vs HalBooking — show members only in one system")

    p_budget = sub.add_parser(
        "budget-report", help="Fetch a read-only income statement (latest years)"
    )
    p_budget.add_argument(
        "--department",
        required=True,
        help="Department label; use 'Padel' as alias. Et tomt/all-department opslag er ikke tilladt.",
    )
    p_budget.add_argument(
        "--years", type=int, default=3, choices=range(1, 4), metavar="1..3",
        help="Number of latest accounting years (default: 3, maximum: 3)"
    )
    p_budget.add_argument("--no-headless", action="store_true", help="Show browser window")

    p_americano = sub.add_parser("create-americano", help="Create an Americano event (duplicates template)")
    p_americano.add_argument("--title", required=True, help="Event title")
    p_americano.add_argument("--date", required=True, help="Date (dd-mm-yyyy)")
    p_americano.add_argument("--max", type=int, default=12, help="Max participants (default: 12)")
    p_americano.add_argument("--description", default="", help="Event description")
    p_americano.add_argument("--price", default="", help="Price (e.g. 50)")
    p_americano.add_argument("--no-headless", action="store_true", help="Show browser window")

    p_mexicano = sub.add_parser("create-mexicano", help="Create a Mexicano event (duplicates template)")
    p_mexicano.add_argument("--title", required=True, help="Event title")
    p_mexicano.add_argument("--date", required=True, help="Date (dd-mm-yyyy)")
    p_mexicano.add_argument("--max", type=int, default=12, help="Max participants (default: 12)")
    p_mexicano.add_argument("--description", default="", help="Event description")
    p_mexicano.add_argument("--price", default="", help="Price (e.g. 50)")
    p_mexicano.add_argument("--no-headless", action="store_true", help="Show browser window")

    p_create = sub.add_parser("create-group", help="Create a group in Conventus (browser automation)")
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--date-from", required=True)
    p_create.add_argument("--date-to", default="")
    p_create.add_argument("--department", default="55804")
    p_create.add_argument("--activity", default="371")
    p_create.add_argument("--max", type=int, default=0)
    p_create.add_argument("--description", default="")
    p_create.add_argument("--price", default="")
    p_create.add_argument("--no-public", action="store_true")
    p_create.add_argument("--no-waiting-list", action="store_true")
    p_create.add_argument("--no-payment", action="store_true")
    p_create.add_argument("--no-headless", action="store_true")

    args = parser.parse_args()

    if args.action == "search":
        cmd_search(args)
    elif args.action == "list":
        cmd_list(args)
    elif args.action == "stats":
        cmd_stats(args)
    elif args.action == "compare":
        cmd_compare(args)
    elif args.action == "budget-report":
        cmd_budget_report(args)
    elif args.action == "create-americano":
        cmd_create_americano(args)
    elif args.action == "create-mexicano":
        cmd_create_mexicano(args)
    elif args.action == "create-group":
        cmd_create_group(args)


if __name__ == "__main__":
    main()

