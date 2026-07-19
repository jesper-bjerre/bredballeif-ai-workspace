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

# Load .env from project root (walk up from this script's location)
_script_dir = Path(__file__).resolve().parent
for _candidate in [_script_dir, *_script_dir.parents]:
    if (_candidate / ".env").exists():
        load_dotenv(_candidate / ".env")
        break

CONVENTUS_ID = os.environ.get("CONVENTUS_ID", "")
CONVENTUS_API_KEY = os.environ.get("CONVENTUS_API_KEY", "")

API_URL = "https://www.conventus.dk/dataudv/api/adressebog/get_grupper_medlemmer.php"
PADEL_VOLUNTEERS_GROUP_ID = "912134"

GROUP_ALIASES: dict[str, list[str]] = {
    "prime":        ["1019486", "1019508", "1046242"],
    "non-prime":    ["1019513", "1019517", "1046244"],
    "hele-2026":    ["1019486", "1019513"],
    "jan-jun-2026": ["1019508", "1019517"],
    "frivillige":   [PADEL_VOLUNTEERS_GROUP_ID],
    "all":          ["1019486", "1019508", "1019513", "1019517", "1046242", "1046244", PADEL_VOLUNTEERS_GROUP_ID],
    # Year-based aliases
    "2021":         ["704445", "704446", "720175"],
    "2022":         ["704445", "704446", "720175"],
    "2023":         ["704445", "791184", "854985"],
    "2024":         ["893985", "939685", "893982", "791187"],
    "2025":         ["959495", "959479", "959497", "959502", "959496", "959493"],
    "2026":         ["1019486", "1019508", "1019513", "1019517", "1046242", "1046244"],
}

GROUP_NAMES: dict[str, str] = {
    PADEL_VOLUNTEERS_GROUP_ID: "Padel Frivillige",
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
    group_ids = resolve_groups(args.group)
    members = fetch_members(group_ids)

    search_term = args.name.lower()
    matches = [m for m in members if search_term in m["navn"].lower()]

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
    import json
    import subprocess

    # -- 1. Conventus: alle grupper (alle år) ------------------------------
    all_group_ids = list({gid for ids in YEAR_GROUPS.values() for gid in ids})
    conv_members = fetch_members(all_group_ids)
    print(f"Conventus: {len(conv_members)} unikke medlemmer hentet.\n")

    conv_by_email: dict[str, dict] = {}
    conv_by_name:  dict[str, dict] = {}
    for m in conv_members:
        if m["email"]:
            conv_by_email[m["email"].lower().strip()] = m
        conv_by_name[_normalize_name(m["navn"])] = m

    # -- 2. HalBooking: export via agent CLI -------------------------------
    print("HalBooking: henter alle Padel-medlemmer via 'Alle medlemmer'-knap…")
    import tempfile
    script_dir = Path(__file__).resolve().parent
    env = {**__import__("os").environ, "PYTHONPATH": str(script_dir), "PYTHONIOENCODING": "utf-8"}
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name
    proc = subprocess.run(
        [__import__("sys").executable, "-m", "agent", "export", "--json", tmp_path],
        capture_output=True,
        cwd=str(script_dir.parent),
        env=env,
    )
    try:
        hb_members: list[dict] = json.loads(Path(tmp_path).read_text(encoding="utf-8"))
    except Exception as e:
        stderr = proc.stderr.decode("utf-8", errors="replace")
        stdout = proc.stdout.decode("utf-8", errors="replace")
        print(f"[!] Kunne ikke parse HalBooking output: {type(e).__name__}; rå streams er udeladt")
        return
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    print(f"HalBooking: {len(hb_members)} Padel-medlemmer fundet.\n")

    hb_by_email: dict[str, dict] = {}
    hb_by_name:  dict[str, dict] = {}
    for m in hb_members:
        email = (m.get("Email") or m.get("email") or "").lower().strip()
        navn  = m.get("Navn") or m.get("navn") or ""
        if email:
            hb_by_email[email] = m
        hb_by_name[_normalize_name(navn)] = m

    # -- 3. Compare --------------------------------------------------------
    only_in_hb:   list[dict] = []
    only_in_conv: list[dict] = []

    # HalBooking → find those not in Conventus
    for m in hb_members:
        email = (m.get("Email") or m.get("email") or "").lower().strip()
        navn  = _normalize_name(m.get("Navn") or m.get("navn") or "")
        if email and email in conv_by_email:
            continue
        if navn and navn in conv_by_name:
            continue
        only_in_hb.append(m)

    # Conventus → find those not in HalBooking
    for m in conv_members:
        email = m["email"].lower().strip() if m["email"] else ""
        navn  = _normalize_name(m["navn"])
        if email and email in hb_by_email:
            continue
        if navn and navn in hb_by_name:
            continue
        only_in_conv.append(m)

    # -- 4. Output ---------------------------------------------------------
    print(f"{'='*70}")
    print(f"  Kun i HalBooking (IKKE i Conventus): {len(only_in_hb)}")
    print(f"{'='*70}")
    if only_in_hb:
        print(f"  {'Medlemsnr':>10}  {'Navn':30}")
        print(f"  {'-'*10}  {'-'*30}")
        for m in sorted(only_in_hb, key=lambda x: x.get("Navn") or x.get("navn") or "")[:10]:
            nr    = m.get("Medlemsnr", "")
            navn  = m.get("Navn") or m.get("navn") or ""
            print(f"  {nr:>10}  {navn:30}")
    else:
        print("  (ingen)")

    print(f"\n{'='*70}")
    print(f"  Kun i Conventus (IKKE i HalBooking): {len(only_in_conv)}")
    print(f"{'='*70}")
    if only_in_conv:
        print(f"  {'ID':>8}  {'Navn':30}  Grupper")
        print(f"  {'-'*8}  {'-'*30}  {'-'*20}")
        for m in sorted(only_in_conv, key=lambda x: x["navn"])[:10]:
            grupper = ", ".join(m["grupper"]) if m["grupper"] else ""
            print(f"  {m['id']:>8}  {m['navn']:30}  {grupper}")
    else:
        print("  (ingen)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Conventus membership query agent")
    sub = parser.add_subparsers(dest="action", required=True)

    p_search = sub.add_parser("search", help="Search for a member by name")
    p_search.add_argument("--name", required=True, help="Name (or part of name) to search for")
    p_search.add_argument("--group", default="all", help="Group alias or comma-separated IDs (default: all)")

    p_list = sub.add_parser("list", help="List all members in a group")
    p_list.add_argument("--group", default="all", help="Group alias or comma-separated IDs (default: all)")

    sub.add_parser("stats", help="Show membership statistics per year with churn analysis (2021-2026)")
    sub.add_parser("compare", help="Compare Conventus vs HalBooking — show members only in one system")

    args = parser.parse_args()

    if args.action == "search":
        cmd_search(args)
    elif args.action == "list":
        cmd_list(args)
    elif args.action == "stats":
        cmd_stats(args)
    elif args.action == "compare":
        cmd_compare(args)


if __name__ == "__main__":
    main()

