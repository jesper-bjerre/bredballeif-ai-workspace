"""
Børneattest-agent for Bredballe IF.

Hjælper med at administrere indhentning af børneattester på frivillige
på tværs af alle afdelinger i Bredballe IF (undtagen fodbold, som ikke bruger Conventus).

Brug:
  python -m agent list
  python -m agent list --group 912134
  python -m agent welcome-email --name "Per Hansen" --afdeling "Padel"
  python -m agent welcome-email --name "Per Hansen" --afdeling "Padel" --link "https://..."
  python -m agent annual-report
  python -m agent afdelinger

Bemærk om Conventus-felter:
  Børneattest hentes fra ekstra felt med titel "Børneattest".
  I denne forening ses feltet aktuelt som ID 16407 (legacy-dokumentation nævner 88).

Bemærk om grupper:
  Den autoritative kilde til `list` og `annual-report` er fælles-gruppen
  1002724 ("06 - Børneattest frivillige"). FRIVILLIGE_GROUPS er kun vejledende
  og bruges alene til at slå velkomst-mail-links op pr. afdeling.

Krav:
  CONVENTUS_ID og CONVENTUS_API_KEY i .env eller miljøvariabler.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

# Sikrer UTF-8 output på Windows-terminaler (æ/ø/å)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

# Indlæs .env fra projekt-roden (søger opad fra scriptets placering)
_script_dir = Path(__file__).resolve().parent
for _candidate in [_script_dir, *_script_dir.parents]:
    if (_candidate / ".env").exists():
        load_dotenv(_candidate / ".env")
        break

CONVENTUS_ID = os.environ.get("CONVENTUS_ID", "")
CONVENTUS_API_KEY = os.environ.get("CONVENTUS_API_KEY", "")
API_URL = "https://www.conventus.dk/dataudv/api/adressebog/get_grupper_medlemmer.php"
API_GRUPPER_URL = "https://www.conventus.dk/dataudv/api/adressebog/get_grupper.php"
API_AFDELINGER_URL = "https://www.conventus.dk/dataudv/api/adressebog/get_afdelinger.php"

# ─── Vejledende: frivillige-grupper pr. afdeling (IKKE autoritativ) ─────────
# VIGTIGT: Den autoritative kilde til lister og årsrapport er fælles-gruppen
#          COMMON_BIF_GROUP_ID (1002724) "06 - Børneattest frivillige".
#          Denne dict er KUN vejledende og bruges alene til at slå
#          afdelingens Conventus-tilmeldingslink op i velkomst-mailen
#          (FRIVILLIGE_LINKS). Den er hverken komplet eller opdateret og må
#          IKKE bruges som kilde til hvem der skal have børneattest.
#
# OBS: Fodbold bruger IKKE Conventus.
#      De sender liste direkte til daglig leder senest 15. januar hvert år.

FRIVILLIGE_GROUPS: dict[str, str] = {
    "912134": "Padel Frivillige",
    # Øvrige afdelinger tilføjes her efterhånden som gruppe-ID'erne kendes:
    # "XXXXXX": "Håndbold Frivillige",
    # "XXXXXX": "Badminton Frivillige",
    # "XXXXXX": "Svømning Frivillige",
    # "XXXXXX": "Tennis Frivillige",
    # "XXXXXX": "Atletik Frivillige",
    # "XXXXXX": "Fitness Frivillige",
    # "XXXXXX": "Gymnastik Frivillige",
    # "XXXXXX": "Skydning Frivillige",
    # "XXXXXX": "Cykling Frivillige",
    # "XXXXXX": "Dart Frivillige",
    # "XXXXXX": "E-sport Frivillige",
    # "XXXXXX": "Petanque Frivillige",
}

# Conventus tilmeldingslinks pr. gruppe (bruges i velkomst-mail, trin 1).
# Via linket kan den frivillige oprette sig i Conventus-gruppen selv.
# Format: "gruppe_id": "https://..."

FRIVILLIGE_LINKS: dict[str, str] = {
    "912134": (
        "https://www.conventus.dk/dataudv/www/new_tilmelding.php"
        "?foreningsid=2296&gruppe=912134&skjul_nyt_medlem=0&skjul_allerede_medlem=0&sprog=da"
    ),
    # Øvrige afdelinger tilføjes parallelt med FRIVILLIGE_GROUPS:
    # "XXXXXX": "https://www.conventus.dk/dataudv/www/new_tilmelding.php?foreningsid=2296&gruppe=XXXXXX&...",
}

# Fælles gruppe: den AUTORITATIVE kilde til lister og årsrapport.
# Alle frivillige i BIF (undtagen fodbold) skal være med i denne gruppe.
COMMON_BIF_GROUP_ID = "1002724"
COMMON_BIF_GROUP_NAME = "06 - Børneattest frivillige"

# Navnetabel til visning. Fælles-gruppen er den autoritative kilde;
# FRIVILLIGE_GROUPS er kun vejledende (bruges til velkomst-mail-links).
GROUP_NAMES: dict[str, str] = {**FRIVILLIGE_GROUPS, COMMON_BIF_GROUP_ID: COMMON_BIF_GROUP_NAME}

# DGI anbefaler fornyelse hvert 2. år (ikke kun ved opstart)
ATTESTATION_RENEWAL_YEARS = 2


# ─── Conventus API ───────────────────────────────────────────────────────────

def fetch_members(group_ids: list[str], timeout: float = 20.0, retries: int = 2) -> list[dict]:
    """Hent frivillige fra Conventus API for de givne gruppe-ID'er."""
    if not CONVENTUS_ID or not CONVENTUS_API_KEY:
        raise RuntimeError("CONVENTUS_ID og CONVENTUS_API_KEY skal sættes (env eller .env)")

    groups_param = ",".join(group_ids)
    url = f"{API_URL}?" + urllib.parse.urlencode(
        {
            "forening": CONVENTUS_ID,
            "key": CONVENTUS_API_KEY,
            "grupper": groups_param,
            "ekstra_felter": "true",
        }
    )

    last_err: Exception | None = None
    xml_data: str | None = None
    for attempt in range(retries + 1):
        try:
            resp = urllib.request.urlopen(url, timeout=timeout)  # noqa: S310
            xml_data = resp.read().decode("utf-8")
            break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < retries:
                wait = 2 ** attempt
                print(
                    f"[!] Conventus API fejl (forsøg {attempt + 1}/{retries + 1}),"
                    f" prøver igen om {wait}s: {e}",
                    file=sys.stderr,
                )
                time.sleep(wait)

    if xml_data is None:
        raise RuntimeError(
            f"Conventus API kunne ikke nås efter {retries + 1} forsøg: {last_err}"
        )

    root = ET.fromstring(xml_data)

    # Byg gruppe-mapping: member_id → liste af gruppe-ID'er
    group_map: dict[str, list[str]] = {}
    for gruppe in root.findall(".//relationer/gruppe"):
        gid = gruppe.findtext("id", "")
        for m in gruppe.findall("medlem/medlem"):
            mid = m.text or ""
            group_map.setdefault(mid, []).append(gid)

    def _extract_boerneattest_dato(medlem_node: ET.Element) -> str:
        """Find Børneattest-værdi i ekstra felter (titel-match + id-fallbacks)."""
        extra_fields = medlem_node.findall(".//ekstra_felter/ekstra_felt")
        if not extra_fields:
            return ""

        fallback_value = ""
        for field in extra_fields:
            field_id = (field.findtext("id", "") or "").strip()
            title = (field.findtext("titel", "") or "").strip().lower()
            value = (field.findtext("indhold", "") or "").strip()

            if field_id in {"16407", "88"} and value and not fallback_value:
                fallback_value = value

            if title == "børneattest":
                return value

        return fallback_value

    members = []
    for medlem in root.findall(".//medlemmer/medlem"):
        mid = medlem.findtext("id", "")
        members.append({
            "id": mid,
            "navn": medlem.findtext("navn", ""),
            "email": medlem.findtext("email", ""),
            "mobil": medlem.findtext("mobil", ""),
            "foedselsdato": medlem.findtext("birth", ""),
            "grupper_ids": group_map.get(mid, []),
            "grupper_navne": [GROUP_NAMES.get(g, g) for g in group_map.get(mid, [])],
            "boerneattest_dato": _extract_boerneattest_dato(medlem),
        })
    return members



def fetch_afdelinger(timeout: float = 20.0, retries: int = 2) -> list[dict]:
    """Hent alle afdelinger i foreningen."""
    if not CONVENTUS_ID or not CONVENTUS_API_KEY:
        raise RuntimeError("CONVENTUS_ID og CONVENTUS_API_KEY skal sættes (env eller .env)")

    url = f"{API_AFDELINGER_URL}?" + urllib.parse.urlencode({"forening": CONVENTUS_ID, "key": CONVENTUS_API_KEY})

    last_err: Exception | None = None
    xml_data: str | None = None
    for attempt in range(retries + 1):
        try:
            resp = urllib.request.urlopen(url, timeout=timeout)  # noqa: S310
            xml_data = resp.read().decode("utf-8")
            break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(2 ** attempt)

    if xml_data is None:
        raise RuntimeError(f"Conventus API kunne ikke nås efter {retries + 1} forsøg: {last_err}")

    root = ET.fromstring(xml_data)
    return [
        {"id": a.findtext("id", ""), "titel": (a.findtext("titel", "") or "").strip()}
        for a in root.findall(".//afdelinger/afdeling")
    ]


def fetch_grupper(afdeling_id: str | None = None, timeout: float = 20.0, retries: int = 2) -> list[dict]:
    """Hent grupper, evt. filtreret på afdeling."""
    if not CONVENTUS_ID or not CONVENTUS_API_KEY:
        raise RuntimeError("CONVENTUS_ID og CONVENTUS_API_KEY skal sættes (env eller .env)")

    params = {"forening": CONVENTUS_ID, "key": CONVENTUS_API_KEY}
    if afdeling_id:
        params["afdeling"] = afdeling_id
    url = f"{API_GRUPPER_URL}?" + urllib.parse.urlencode(params)

    last_err: Exception | None = None
    xml_data: str | None = None
    for attempt in range(retries + 1):
        try:
            resp = urllib.request.urlopen(url, timeout=timeout)  # noqa: S310
            xml_data = resp.read().decode("utf-8")
            break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(2 ** attempt)

    if xml_data is None:
        raise RuntimeError(f"Conventus API kunne ikke nås efter {retries + 1} forsøg: {last_err}")

    root = ET.fromstring(xml_data)
    grupper = []
    for g in root.findall(".//grupper/gruppe"):
        grupper.append(
            {
                "id": g.findtext("id", ""),
                "afdeling": g.findtext("afdeling", ""),
                "type": (g.findtext("type", "") or "").strip(),
                "titel": (g.findtext("titel", "") or "").strip(),
                "aldersgruppe": (g.findtext("aldersgruppe", "") or "").strip(),
            }
        )
    return grupper


def fetch_group_roles(group_ids: list[str], timeout: float = 20.0, retries: int = 2) -> tuple[dict, dict]:
    """Hent leder-/medlem-roller samt medlemsdetaljer for grupper."""
    if not CONVENTUS_ID or not CONVENTUS_API_KEY:
        raise RuntimeError("CONVENTUS_ID og CONVENTUS_API_KEY skal sættes (env eller .env)")

    url = f"{API_URL}?" + urllib.parse.urlencode(
        {
            "forening": CONVENTUS_ID,
            "key": CONVENTUS_API_KEY,
            "grupper": ",".join(group_ids),
            "titler": "true",
            "ekstra_felter": "true",
        }
    )

    last_err: Exception | None = None
    xml_data: str | None = None
    for attempt in range(retries + 1):
        try:
            resp = urllib.request.urlopen(url, timeout=timeout)  # noqa: S310
            xml_data = resp.read().decode("utf-8")
            break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(2 ** attempt)

    if xml_data is None:
        raise RuntimeError(f"Conventus API kunne ikke nås efter {retries + 1} forsøg: {last_err}")

    root = ET.fromstring(xml_data)

    group_roles: dict[str, dict[str, list[dict]]] = {}
    for grp in root.findall(".//relationer/gruppe"):
        gid = grp.findtext("id", "")
        role_data = {"leder": [], "medlem": []}
        for role in ("leder", "medlem"):
            node = grp.find(role)
            if node is None:
                continue
            for profil in node.findall("profil"):
                pid = profil.findtext("id", "")
                titles = [
                    (t.findtext("titel", "") or "").strip()
                    for t in profil.findall(".//titler/titel")
                    if (t.findtext("titel", "") or "").strip()
                ]
                role_data[role].append({"id": pid, "titles": titles})
        group_roles[gid] = role_data

    people: dict[str, dict] = {}
    for medlem in root.findall(".//medlemmer/medlem"):
        mid = medlem.findtext("id", "")
        people[mid] = {
            "id": mid,
            "navn": (medlem.findtext("navn", "") or "").strip(),
            "email": (medlem.findtext("email", "") or "").strip(),
            "mobil": (medlem.findtext("mobil", "") or "").strip(),
            "foedselsdato": (medlem.findtext("birth", "") or "").strip(),
        }

    return group_roles, people


def _is_under_15(dob: str) -> bool:
    if not dob:
        return False
    try:
        born = datetime.strptime(dob, "%Y-%m-%d").date()
    except ValueError:
        return False
    today = date.today()
    years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return years < 15


def _is_u15_from_aldersgruppe(aldersgruppe: str) -> bool:
    if not aldersgruppe:
        return False
    # Check for birth years (1900-2099)
    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", aldersgruppe or "")]
    if years:
        cutoff = date.today().year - 15
        return any(y > cutoff for y in years)
    # Check for age ranges like "7 til 14", "8 til 14", "10-16", etc.
    # If any number in range is < 15, then group contains U15 children
    ages = [int(a) for a in re.findall(r"\b(\d{1,2})\b", aldersgruppe)]
    if ages:
        return any(age < 15 for age in ages)
    return False

def _is_volunteer_group_title(title: str) -> bool:
    """Best effort-match af afdelingsgrupper med frivillige trænere/ledere."""
    t = (title or "").strip().lower()
    if not t:
        return False

    keywords = ("frivillig", "instruktør", "instruktor", "træner", "traener", "leder")
    return any(k in t for k in keywords)
def resolve_afdeling(afdeling_input: str) -> dict | None:
    """Find afdeling via ID eller navn (eksakt eller delvist match)."""
    afdelinger = fetch_afdelinger()
    afdeling = None
    if afdeling_input.isdigit():
        afdeling = next((a for a in afdelinger if a["id"] == afdeling_input), None)
    if afdeling is None:
        afdeling = next((a for a in afdelinger if a["titel"].lower() == afdeling_input.lower()), None)
    if afdeling is None:
        afdeling = next((a for a in afdelinger if afdeling_input.lower() in a["titel"].lower()), None)
    return afdeling

# ─── Atteststatus-hjælpere (aktive i fase 2) ─────────────────────────────────

def parse_attest_date(raw: str) -> date | None:
    """Parser dato fra attestfeltet, fx 'Godkendt 13-06-2026' eller '13.06.2026'."""
    for fmt in ("%d-%m-%Y", "%d.%m.%Y", "%d-%m-%y", "%d.%m.%y"):
        for part in raw.split():
            try:
                return datetime.strptime(part, fmt).date()
            except ValueError:
                continue
    return None


def attest_status(raw: str) -> str:
    """Fortolker attestindhold til en læsbar status-streng."""
    if not raw:
        return "Mangler"
    lower = raw.lower()
    if lower.startswith("godkendt"):
        d = parse_attest_date(raw)
        if d:
            years_ago = (date.today() - d).days / 365.25
            if years_ago > ATTESTATION_RENEWAL_YEARS:
                return f"FORÆLDET ({d.strftime('%d-%m-%Y')}) — skal fornyes"
            return f"OK ({d.strftime('%d-%m-%Y')})"
        return "Godkendt (dato mangler)"
    if lower.startswith("ansøgt"):
        return f"Afventer — {raw}"
    if lower.startswith("afvist"):
        return f"AFVIST — bestil igen: {raw}"
    if lower.startswith("ikke godkendt"):
        return f"IKKE GODKENDT — kontakt HB: {raw}"

    # Accepter også dato alene (fx 18.04.24) som godkendelsesdato jf. procedure.
    d = parse_attest_date(raw)
    if d:
        years_ago = (date.today() - d).days / 365.25
        if years_ago > ATTESTATION_RENEWAL_YEARS:
            return f"FORÆLDET ({d.strftime('%d-%m-%Y')}) — skal fornyes"
        return f"OK ({d.strftime('%d-%m-%Y')})"

    return raw


# ─── Kommandoer ──────────────────────────────────────────────────────────────

def cmd_list(args: argparse.Namespace) -> int:
    """List alle frivillige — som standard fra fælles-gruppen 1002724."""
    group_ids = [g.strip() for g in args.group.split(",")] if args.group else [COMMON_BIF_GROUP_ID]
    if not group_ids:
        print("Ingen grupper angivet.", file=sys.stderr)
        return 1

    group_label = args.group or f"{COMMON_BIF_GROUP_NAME} ({COMMON_BIF_GROUP_ID})"
    print(f"[*] Henter frivillige fra Conventus ({group_label})…")
    members = fetch_members(group_ids)

    if not members:
        print("  Ingen frivillige fundet i de valgte grupper.")
        return 0

    # Fællesgruppen checkes altid sammen med en afdelingsliste, da den bruges til årsrapporten.
    common_ids = {m.get("id", "") for m in fetch_members([COMMON_BIF_GROUP_ID])}

    print(f"\n=== Bredballe IF: {len(members)} frivillige ===\n")
    print(
        f"  {'ID':>8}  {'Navn':35}  {'Email':35}  {'Mobil':13}  {'Atteststatus':30}  {'Fællesgruppe':12}  Gruppe"
    )
    print(
        f"  {'─' * 8}  {'─' * 35}  {'─' * 35}  {'─' * 13}  {'─' * 30}  {'─' * 12}  {'─' * 30}"
    )

    missing_common = []
    for m in sorted(members, key=lambda x: x["navn"]):
        grupper = ", ".join(m["grupper_navne"]) or "(ingen)"
        status = attest_status(m.get("boerneattest_dato", ""))
        in_common = "Ja" if m.get("id", "") in common_ids else "NEJ"
        if in_common == "NEJ":
            missing_common.append(m)
        print(
            f"  {m['id']:>8}  {m['navn']:35}  {m['email']:35}  {m['mobil']:13}  {status:30}  {in_common:12}  {grupper}"
        )

    print(f"\n  Total: {len(members)} frivillige")
    print("\n  [i] Atteststatus er udledt fra Conventus ekstra felt 'Børneattest'.")
    print(f"  [i] Fællesgruppe checket: {COMMON_BIF_GROUP_NAME} ({COMMON_BIF_GROUP_ID}).")
    if missing_common:
        print("\n  [ADVARSEL] Følgende frivillige mangler i fællesgruppen:")
        for m in missing_common:
            print(f"    - {m.get('navn', '')} (ID {m.get('id', '')})")
    return 0


def _find_link_for_afdeling(afdeling: str) -> str:
    """Slår Conventus-tilmeldingslink op baseret på afdelingsnavn (case-insensitivt substring-match)."""
    afd_lower = afdeling.lower()
    for gid, gname in FRIVILLIGE_GROUPS.items():
        if afd_lower in gname.lower():
            return FRIVILLIGE_LINKS.get(gid, "")
    return ""


def cmd_welcome_email(args: argparse.Namespace) -> int:
    """Generér velkomst-mail til ny frivillig (skabelon fra Bredballe IF's procedure)."""
    navn = args.name
    afdeling = args.afdeling
    already_registered = getattr(args, "already_registered", False)
    link = args.link or _find_link_for_afdeling(afdeling) or "<indsæt link til afdelingens frivillighedsgruppe i Conventus>"

    if already_registered:
        trin1_tekst = "Du er allerede oprettet i vores medlemssystem Conventus — tak for det!"
    else:
        trin1_tekst = (
            f"Trin 1: Du skal oprette dig i medlemssystemet Conventus med fulde navn og fødselsdato.\n{link}"
        )

    print("\n" + "=" * 70)
    print(f"VELKOMST-MAIL TIL NY FRIVILLIG — {afdeling.upper()}")
    print(f"Kopiér teksten nedenfor og send den til {navn}")
    print("=" * 70)
    print(f"""
Emne: Bredballe IF — indhentning af børneattest

Hej {navn}

Bredballe IF har pligt til at indhente børneattest på nye frivillige over 15 år,
som skal arbejde med børn under 15 år.

{trin1_tekst}

{'Trin 2' if not already_registered else 'Vi mangler blot'}: Oplys dit fulde navn og de SIDSTE 4 CIFRE af dit CPR-NR til udvalget:

  Afdelingsnavn:             Bredballe IF {afdeling}
  Dit fulde navn:            {navn}
  4 sidste cifre i CPR-NR:  ________________________________

Hvis du ikke ønsker at sende disse oplysninger via email, kan du i stedet
oplyse dem ved fysisk fremmøde, pr. telefon eller med post.
Dette aftales nærmere med afdelingens udvalg.

{'Trin 3' if not already_registered else 'Herefter'}: Afdelingens udvalg anmoder politiet om at udlevere din børneattest.
Din email med CPR-NR slettes permanent bagefter.

{'Trin 4' if not already_registered else 'Til sidst'}: Via e-Boks vil politiet anmode dig om tilladelse til at sende din
børneattest til Bredballe IF. Du har 14 dage til at acceptere.

Mange tak for din hjælp — vi glæder os til samarbejdet!

Med venlig hilsen
{afdeling}s udvalg i Bredballe IF
""")
    print("=" * 70)
    print("\n  Husk (udvalget):")
    print("  1. Bestil børneattesten på https://politi.dk/straffeattest/bestil-boerneattest")
    print("     (login med erhvervs MitID)")
    print("  2. Opdater Conventus Børneattest-felt med 'Ansøgt dd-mm-yyyy' straks efter bestilling")
    print("  3. Tjek virk.dk 14 dage efter — opdater Børneattest-feltet med resultatet")
    print("=" * 70 + "\n")
    return 0


def cmd_annual_report(args: argparse.Namespace) -> int:
    """Generér årsrapport til brug for 1. februar-erklæringen.

    Rapporten bygger udelukkende på fælles-gruppen "06 - Børneattest frivillige"
    (COMMON_BIF_GROUP_ID) — den autoritative kilde til samtlige frivillige i BIF.
    """
    today = date.today()

    print(f"[*] Henter frivillige fra {COMMON_BIF_GROUP_NAME} ({COMMON_BIF_GROUP_ID})…")
    members = fetch_members([COMMON_BIF_GROUP_ID])

    print(f"\n{'=' * 70}")
    print("ÅRSRAPPORT — BØRNEATTESTER I BREDBALLE IF")
    print(f"Genereret: {today.strftime('%d-%m-%Y')}")
    print(f"Kilde: {COMMON_BIF_GROUP_NAME} (gruppe {COMMON_BIF_GROUP_ID})")
    print(f"{'=' * 70}\n")

    if not members:
        print("Ingen frivillige fundet i fælles-gruppen.")
        return 0

    print(f"Samtlige frivillige ({len(members)} i alt):\n")
    print(f"  {'Navn':35}  {'Email':35}  Atteststatus")
    print(f"  {'─' * 35}  {'─' * 35}  {'─' * 30}")

    for m in sorted(members, key=lambda x: x["navn"]):
        status = attest_status(m.get("boerneattest_dato", ""))
        print(f"  {m['navn']:35}  {m['email']:35}  {status}")

    mangler = [
        m for m in members
        if not attest_status(m.get("boerneattest_dato", "")).startswith("OK (")
    ]
    if mangler:
        print(f"\n{'─' * 70}")
        print("[ADVARSEL] Følgende frivillige mangler en gyldig godkendt børneattest:")
        for m in sorted(mangler, key=lambda x: x["navn"]):
            print(f"  - {m['navn']} (ID {m['id']}): {attest_status(m.get('boerneattest_dato', ''))}")

    print(f"\n{'─' * 70}")
    print("ERKLÆRING (underskrives senest 1. februar hvert år af tegningsberettigede):")
    print()
    print("  Undertegnede erklærer på tro og love, at Bredballe IF har bestilt")
    print("  børneattest på alle frivillige, der er i kontakt med børn under 15 år.")
    print()
    print(f"  Dato: {today.strftime('%d-%m-%Y')}")
    print( "  Underskrift: ________________________________")
    print( "  Navn (blokbogstaver): ______________________")
    print(f"\n{'=' * 70}\n")

    print("  NÆSTE SKRIDT:")
    print(f"  1. Gennemgå listen — er alle frivillige med i fælles-gruppen {COMMON_BIF_GROUP_ID}?")
    print(f"  2. Kilde er fælles-gruppen {COMMON_BIF_GROUP_NAME} ({COMMON_BIF_GROUP_ID}).")
    print("  3. Atteststatus hentes fra Conventus ekstra felt 'Børneattest'.")
    print("  4. Fodbold er IKKE i denne rapport — de sender separat liste til daglig leder.")
    return 0



def cmd_u15_trainers(args: argparse.Namespace) -> int:
    """List frivillige over 15 år som træner/leder hold med børn under 15 år i en afdeling."""
    afdeling_navn = (args.afdeling or "Padel").strip()
    print(f"[*] Henter grupper og roller for afdeling '{afdeling_navn}'…")

    afdeling = resolve_afdeling(afdeling_navn)
    if afdeling is None:
        print(f"[!] Kunne ikke finde afdeling '{afdeling_navn}'.", file=sys.stderr)
        return 1

    all_grupper = fetch_grupper(afdeling_id=afdeling["id"])
    hold_grupper = [g for g in all_grupper if g.get("type") == "hold"]

    # Træningshold i afdelingen: ekskludér medlemskabs-/frivillig-hold (fx "Padel: ...", "Frivillige")
    training_hold = []
    for g in hold_grupper:
        t = (g.get("titel") or "").lower()
        a = (g.get("aldersgruppe") or "").lower()
        if "frivillig" in t or t.startswith("padel:"):
            continue
        if "holdtræning" in t or "årgang" in a or _is_u15_from_aldersgruppe(g.get("aldersgruppe", "")):
            training_hold.append(g)

    if not training_hold:
        print("Ingen træningshold fundet i afdelingen.")
        return 0

    group_ids = [g["id"] for g in training_hold]
    group_lookup = {g["id"]: g for g in training_hold}
    group_roles, people = fetch_group_roles(group_ids)

    u15_hold_ids: list[str] = []
    for gid in group_ids:
        roles = group_roles.get(gid, {"leder": [], "medlem": []})
        member_ids = [m["id"] for m in roles.get("medlem", [])]
        has_u15 = any(_is_under_15(people.get(mid, {}).get("foedselsdato", "")) for mid in member_ids)
        if not has_u15:
            has_u15 = _is_u15_from_aldersgruppe(group_lookup[gid].get("aldersgruppe", ""))
        if has_u15:
            u15_hold_ids.append(gid)

    if not u15_hold_ids:
        print("Ingen U15-hold fundet i afdelingen.")
        return 0

    frivillig_group_ids = [g["id"] for g in all_grupper if _is_volunteer_group_title(g.get("titel", ""))]
    frivillig_ids: set[str] = set()
    if frivillig_group_ids:
        for m in fetch_members(frivillig_group_ids):
            frivillig_ids.add(m["id"])

    trainer_map: dict[str, dict] = {}
    for gid in u15_hold_ids:
        hold_titel = group_lookup[gid]["titel"]
        for leder in group_roles.get(gid, {}).get("leder", []):
            mid = leder["id"]
            # Børneattestkravet gælder kun frivillige over 15 år.
            if _is_under_15(people.get(mid, {}).get("foedselsdato", "")):
                continue
            if mid not in trainer_map:
                person = people.get(mid, {"navn": "", "email": ""})
                trainer_map[mid] = {
                    "id": mid,
                    "navn": person.get("navn", ""),
                    "email": person.get("email", ""),
                    "titles": set(),
                    "hold": set(),
                    "i_frivilliggruppe": (mid in frivillig_ids) if frivillig_ids else True,
                }
            trainer_map[mid]["titles"].update(leder.get("titles", []))
            trainer_map[mid]["hold"].add(hold_titel)

    frivillige_trainere = [t for t in trainer_map.values() if t["i_frivilliggruppe"]]
    mangler_frivilliggruppe = [t for t in trainer_map.values() if not t["i_frivilliggruppe"]]

    # Hent attestdata for frivillige i afdelingens frivilliggrupper,
    # så attestsjek kun køres på personer der faktisk træner/leder U15-hold.
    frivillig_member_map: dict[str, dict] = {}
    if frivillig_group_ids:
        for m in fetch_members(frivillig_group_ids):
            frivillig_member_map[m["id"]] = m

    for t in frivillige_trainere:
        member = frivillig_member_map.get(t["id"], {})
        raw = member.get("boerneattest_dato", "") if member else ""
        t["atteststatus"] = attest_status(raw)

    # Fællesgruppen checkes altid sammen med afdelingskontrollen.
    common_ids = {m.get("id", "") for m in fetch_members([COMMON_BIF_GROUP_ID])}
    for t in frivillige_trainere:
        t["i_faellesgruppe"] = t.get("id", "") in common_ids

    print(f"\n=== {afdeling['titel']}: frivillige over 15 år der træner/leder U15-hold ===\n")
    if not frivillige_trainere:
        print("Ingen fundet i afdelingens frivilliggruppe.")
    else:
        print(f"  {'ID':>8}  {'Navn':35}  {'Rolle':18}  {'Atteststatus':30}  {'Fællesgruppe':12}  {'Email':35}")
        print(f"  {'─' * 8}  {'─' * 35}  {'─' * 18}  {'─' * 30}  {'─' * 12}  {'─' * 35}")
        for t in sorted(frivillige_trainere, key=lambda x: x['navn']):
            rolle = ", ".join(sorted(t["titles"])) or "Leder"
            status = t.get("atteststatus", "Mangler")
            in_common = "Ja" if t.get("i_faellesgruppe") else "NEJ"
            print(f"  {t['id']:>8}  {t['navn']:35}  {rolle:18}  {status:30}  {in_common:12}  {t['email']:35}")

    print(f"\n  U15-hold kontrolleret: {len(u15_hold_ids)}")
    for gid in u15_hold_ids:
        print(f"  - {group_lookup[gid]['titel']}")

    if mangler_frivilliggruppe:
        print("\n[ADVARSEL] Disse trænere/ledere er på U15-hold men mangler i afdelingens frivilliggruppe:")
        for t in sorted(mangler_frivilliggruppe, key=lambda x: x['navn']):
            print(f"  - {t['navn']} (ID {t['id']})")

    needs_followup = [
        t for t in frivillige_trainere
        if not str(t.get("atteststatus", "")).startswith("OK (")
    ]
    if needs_followup:
        print("\n[ADVARSEL] Følgende U15-trænere/ledere mangler gyldig børneattest:")
        for t in sorted(needs_followup, key=lambda x: x["navn"]):
            print(f"  - {t['navn']} (ID {t['id']}): {t.get('atteststatus', 'Mangler')}")

    missing_common_trainers = [t for t in frivillige_trainere if not t.get("i_faellesgruppe")]
    if missing_common_trainers:
        print(f"\n[ADVARSEL] Følgende U15-trænere/ledere mangler i fællesgruppen {COMMON_BIF_GROUP_NAME} ({COMMON_BIF_GROUP_ID}):")
        for t in sorted(missing_common_trainers, key=lambda x: x["navn"]):
            print(f"  - {t['navn']} (ID {t['id']})")

    return 0


def cmd_afdeling_attest(args: argparse.Namespace) -> int:
    """Deterministisk afdelingsliste: Afdeling, Navn, Børneattest status for relevante U15-frivillige."""
    afdeling_input = (args.afdeling or "").strip()
    if not afdeling_input:
        print("[!] Angiv afdeling via navn eller ID.", file=sys.stderr)
        return 1

    afdeling = resolve_afdeling(afdeling_input)
    if afdeling is None:
        print(f"[!] Kunne ikke finde afdeling '{afdeling_input}'.", file=sys.stderr)
        return 1

    all_grupper = fetch_grupper(afdeling_id=afdeling["id"])
    hold_grupper = [g for g in all_grupper if g.get("type") == "hold"]

    training_hold = []
    for g in hold_grupper:
        titel = (g.get("titel") or "").lower()
        alder = (g.get("aldersgruppe") or "").lower()
        if "frivillig" in titel or titel.startswith("padel:"):
            continue
        if "holdtræning" in titel or "årgang" in alder or _is_u15_from_aldersgruppe(g.get("aldersgruppe", "")):
            training_hold.append(g)

    if not training_hold:
        print("Ingen træningshold fundet i afdelingen.")
        return 0

    group_ids = [g["id"] for g in training_hold]
    group_lookup = {g["id"]: g for g in training_hold}
    group_roles, people = fetch_group_roles(group_ids)

    u15_hold_ids: list[str] = []
    for gid in group_ids:
        roles = group_roles.get(gid, {"leder": [], "medlem": []})
        member_ids = [m["id"] for m in roles.get("medlem", [])]
        has_u15 = any(_is_under_15(people.get(mid, {}).get("foedselsdato", "")) for mid in member_ids)
        if not has_u15:
            has_u15 = _is_u15_from_aldersgruppe(group_lookup[gid].get("aldersgruppe", ""))
        if has_u15:
            u15_hold_ids.append(gid)

    if not u15_hold_ids:
        print("Ingen U15-hold fundet i afdelingen.")
        return 0

    frivillig_group_ids = [g["id"] for g in all_grupper if _is_volunteer_group_title(g.get("titel", ""))]
    frivillig_ids: set[str] = set()
    if frivillig_group_ids:
        for m in fetch_members(frivillig_group_ids):
            frivillig_ids.add(m["id"])

    trainer_map: dict[str, dict] = {}
    for gid in u15_hold_ids:
        for leder in group_roles.get(gid, {}).get("leder", []):
            mid = leder["id"]
            if _is_under_15(people.get(mid, {}).get("foedselsdato", "")):
                continue
            if mid not in trainer_map:
                person = people.get(mid, {"navn": "", "email": ""})
                trainer_map[mid] = {
                    "id": mid,
                    "navn": person.get("navn", ""),
                    "i_frivilliggruppe": (mid in frivillig_ids) if frivillig_ids else True,
                }

    relevante = [t for t in trainer_map.values() if t["i_frivilliggruppe"]]

    frivillig_member_map: dict[str, dict] = {}
    if frivillig_group_ids:
        for m in fetch_members(frivillig_group_ids):
            frivillig_member_map[m["id"]] = m

    common_ids = {m.get("id", "") for m in fetch_members([COMMON_BIF_GROUP_ID])}

    rows = []
    for t in sorted(relevante, key=lambda x: x["navn"]):
        member = frivillig_member_map.get(t["id"], {})
        raw = member.get("boerneattest_dato", "") if member else ""
        rows.append({
            "afdeling": afdeling["titel"],
            "navn": t["navn"],
            "status": attest_status(raw),
            "id": t["id"],
            "i_faellesgruppe": t["id"] in common_ids,
        })

    if not rows:
        print("Ingen relevante frivillige fundet (over 15 år som træner/leder U15-hold).")
        return 0

    print("\n=== Frivillige med børneattest i afdeling ===\n")
    print(f"  {'Afdeling':20}  {'Navn':35}  {'Børneattest status':40}")
    print(f"  {'─' * 20}  {'─' * 35}  {'─' * 40}")
    for r in rows:
        print(f"  {r['afdeling']:20}  {r['navn']:35}  {r['status']:40}")

    invalid = [r for r in rows if not str(r["status"]).startswith("OK (")]
    if invalid:
        print("\n[ADVARSEL] Frivillige over 15 år som træner børn under 15 år skal have en godkendt børneattest:")
        for r in invalid:
            print(f"  - {r['navn']} (ID {r['id']}): {r['status']}")

    missing_common = [r for r in rows if not r["i_faellesgruppe"]]
    if missing_common:
        print(f"\n[ADVARSEL] Følgende mangler i fællesgruppen {COMMON_BIF_GROUP_NAME} ({COMMON_BIF_GROUP_ID}):")
        for r in missing_common:
            print(f"  - {r['navn']} (ID {r['id']})")

    return 0

def cmd_afdelinger(args: argparse.Namespace) -> int:  # noqa: ARG001
    """List samtlige afdelinger i Conventus for den konfigurerede forening."""
    print("[*] Henter alle afdelinger fra Conventus…")
    afdelinger = fetch_afdelinger()

    if not afdelinger:
        print("Ingen afdelinger fundet i Conventus.")
        return 0

    rows = sorted(
        afdelinger,
        key=lambda a: ((a.get("titel") or "").lower(), a.get("id") or ""),
    )

    print(f"\n=== Conventus afdelinger ({len(rows)}) ===\n")
    print(f"  {'ID':>8}  {'Afdeling'}")
    print(f"  {'─' * 8}  {'─' * 50}")
    for afd in rows:
        print(f"  {afd.get('id', ''):>8}  {afd.get('titel', '')}")

    return 0

def cmd_grupper(args: argparse.Namespace) -> int:
    """List samtlige grupper (hold) i en afdeling."""
    afdeling_input = (args.afdeling or "").strip()
    if not afdeling_input:
        print("[!] Angiv afdeling via navn eller ID.", file=sys.stderr)
        return 1

    afdeling = resolve_afdeling(afdeling_input)
    if afdeling is None:
        print(f"[!] Kunne ikke finde afdeling '{afdeling_input}'.", file=sys.stderr)
        return 1

    grupper = fetch_grupper(afdeling_id=afdeling["id"])
    if not grupper:
        print(f"Ingen grupper fundet i afdelingen {afdeling.get('titel', '')} ({afdeling.get('id', '')}).")
        return 0

    # Filtrer på U15-hold hvis ønsket
    if args.u15_only:
        grupper = [g for g in grupper if _is_u15_from_aldersgruppe(g.get("aldersgruppe", ""))]
        if not grupper:
            print(f"Ingen U15-hold fundet i afdelingen {afdeling.get('titel', '')} ({afdeling.get('id', '')}).")
            return 0

    rows = sorted(
        grupper,
        key=lambda g: ((g.get("type") or "").lower(), (g.get("titel") or "").lower(), g.get("id") or ""),
    )

    filter_label = " (U15-hold)" if args.u15_only else ""
    print(f"\n=== {afdeling.get('titel', '')}: grupper/hold ({len(rows)}){filter_label} ===\n")
    print(f"  {'ID':>8}  {'Type':10}  {'Titel':45}  {'Aldersgruppe'}")
    print(f"  {'─' * 8}  {'─' * 10}  {'─' * 45}  {'─' * 25}")
    for g in rows:
        print(
            f"  {g.get('id', ''):>8}  {g.get('type', ''):10}  {g.get('titel', ''):45}  {g.get('aldersgruppe', '')}"
        )

    return 0

# ─── Main# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bredballeif-boerneattest",
        description="Børneattest-agent for Bredballe IF — administrér frivilliges atteststatus",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Eksempler:
  python -m agent list
  python -m agent list --group 912134
  python -m agent welcome-email --name "Per Hansen" --afdeling "Padel"
  python -m agent welcome-email --name "Trine Rose" --afdeling "Padel" --already-registered
  python -m agent annual-report
  python -m agent afdelinger
  python -m agent grupper --afdeling "Esport"
  python -m agent afdeling-attest --afdeling "Esport"
        """,
    )
    sub = parser.add_subparsers(dest="action", metavar="<action>")

    # list
    p_list = sub.add_parser("list", help="List frivillige (standard: fælles-gruppe 1002724)")
    p_list.add_argument(
        "--group",
        metavar="ID[,ID]",
        help="Kommaseparerede Conventus gruppe-ID'er (default: fælles-gruppe 1002724)",
    )

    # welcome-email
    p_welcome = sub.add_parser(
        "welcome-email",
        help="Generér velkomst-mail med børneattest-instruktioner til ny frivillig",
    )
    p_welcome.add_argument("--name", required=True, metavar="NAVN", help="Den frivilliges fulde navn")
    p_welcome.add_argument("--afdeling", required=True, metavar="AFDELING", help="Afdelingsnavn, fx 'Padel'")
    p_welcome.add_argument("--link", metavar="URL", help="Link til Conventus frivillighedsgruppe (valgfrit)")
    p_welcome.add_argument(
        "--already-registered",
        action="store_true",
        help="Den frivillige er allerede oprettet i Conventus — springer Trin 1 over",
    )

    # annual-report
    sub.add_parser(
        "annual-report",
        help="Generér årsrapport til 1. februar-erklæringen (fælles-gruppe 1002724)",
    )

    # afdelinger
    sub.add_parser(
        "afdelinger",
        help="List samtlige afdelinger fra Conventus",
    )

    # grupper
    p_grupper = sub.add_parser(
        "grupper",
        help="List samtlige grupper (hold) i en afdeling",
    )
    p_grupper.add_argument(
        "--afdeling",
        required=True,
        metavar="AFDELING",
        help="Afdeling der skal vises (navn eller ID, fx Esport eller 35130)",
    )

    p_grupper.add_argument(
        "--u15-only",
        action="store_true",
        help="Vis kun hold med børn under 15 år",
    )

    # afdeling-attest
    p_afdeling = sub.add_parser(
        "afdeling-attest",
        help="Vis frivillige med børneattest i afdeling (deterministisk output)",
    )
    p_afdeling.add_argument(
        "--afdeling",
        required=True,
        metavar="AFDELING",
        help="Afdeling der skal vises (navn eller ID, fx Esport eller 35130)",
    )

    # u15-trainers
    p_u15 = sub.add_parser(
        "u15-trainers",
        help="List frivillige trænere/ledere på hold med børn under 15 år",
    )
    p_u15.add_argument(
        "--afdeling",
        default="Padel",
        metavar="AFDELING",
        help="Afdeling der skal kontrolleres (navn eller ID, default: Padel)",
    )

    args = parser.parse_args()

    if args.action is None:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "list": cmd_list,
        "welcome-email": cmd_welcome_email,
        "annual-report": cmd_annual_report,
        "afdelinger": cmd_afdelinger,
        "grupper": cmd_grupper,
        "afdeling-attest": cmd_afdeling_attest,
        "u15-trainers": cmd_u15_trainers,
    }
    sys.exit(dispatch[args.action](args))


if __name__ == "__main__":
    main()












