"""Read-only web discovery and Fundraising Club scraping.

The module deliberately returns normalized metadata instead of persisting HTML.
Callers decide how and where records are stored. Authenticated cookies only live
in the in-memory requests session.
"""

from __future__ import annotations

import csv
import html as html_module
import ipaddress
import io
import json
import math
import re
import socket
import time
import urllib.robotparser
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo("Europe/Copenhagen")
USER_AGENT = "BredballeIF-Fondsindeks/1.0"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
STATE_GRANTS_FEED = "https://www.statens-tilskudspuljer.dk/DataExport/statens-tilskudspuljer.csv"
DGI_FUNDS_LANDING = (
    "https://www.dgi.dk/raad-og-vejledning/fundraising-i-foreningen/"
    "puljer-og-fonde/soeg-i-170-puljer-og-fonde"
)
EU_FUNDING_SEARCH_ENDPOINT = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
EU_FUNDING_API_DOCS = (
    "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/support/apis"
)

FUNDING_WORDS = (
    "fond",
    "pulje",
    "tilskud",
    "støtte",
    "stoette",
    "donation",
    "ansøg",
    "ansoeg",
    "grant",
    "funding",
)
REQUIREMENT_WORDS = (
    "ansøgningsfrist",
    "ansoegningsfrist",
    "hvem kan søge",
    "hvem kan soege",
    "vi støtter",
    "vi stoetter",
    "kriterier",
    "beløb",
    "beloeb",
)
SKIP_PATH_PARTS = (
    "/login",
    "/logout",
    "/wp-admin",
    "/wp-login",
    "/registrer",
    "/account",
    "/profil",
    "/kursus",
    "/module-",
    "/refer/",
    "/feed/",
)
NON_HTML_SUFFIXES = (
    ".csv",
    ".doc",
    ".docx",
    ".gif",
    ".jpeg",
    ".jpg",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".svg",
    ".webp",
    ".xls",
    ".xlsx",
    ".zip",
)
SOCIAL_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "instagram.com",
    "www.instagram.com",
    "linkedin.com",
    "www.linkedin.com",
    "youtube.com",
    "www.youtube.com",
}

ASSOCIATION_RELEVANCE_WORDS = (
    "idræt",
    "idraet",
    "sport",
    "forening",
    "frivillig",
    "fritid",
    "bevæg",
    "bevaeg",
    "børn",
    "boern",
    "unge",
    "fællesskab",
    "faellesskab",
    "inklusion",
    "handicap",
    "parasport",
    "facilitet",
    "lokalsamfund",
    "friluft",
    "sundhed",
    "trivsel",
    "social",
    "kultur",
    "klima",
    "natur",
    "landdistrikt",
    "uddannelse",
)

# The EU portal has no association-specific classification. These deliberately
# broad English signals produce discovery candidates, never application-ready
# records. Eligibility is researched on the individual official topic page.
EU_ASSOCIATION_RELEVANCE_WORDS = (
    "sport",
    "sports",
    "physical activity",
    "active lifestyle",
    "healthy lifestyle",
    "grassroots",
    "volunteer",
    "volunteers",
    "volunteering",
    "youth",
    "young people",
    "children",
    "child wellbeing",
    "community",
    "communities",
    "social inclusion",
    "inclusion",
    "inclusive",
    "disability",
    "mental health",
    "well-being",
    "wellbeing",
    "culture",
    "cultural",
    "nature",
    "environment",
    "environmental",
    "climate",
    "biodiversity",
    "rural",
    "local development",
    "recreational",
    "facility",
    "facilities",
)
EU_RELEVANT_IDENTIFIER_PREFIXES = (
    "ERASMUS-SPORT",
    "ERASMUS-YOUTH",
    "ESC-",
    "CERV-CITIZENS",
    "CREA-CULT",
)
EU_TYPE_LABELS = {"1": "Grant", "2": "Call", "8": "Cascade funding"}
EU_STATUS_LABELS = {"31094501": "Forthcoming", "31094502": "Open"}


class ScrapeError(RuntimeError):
    """Raised for a safe, user-facing scraping failure."""


@dataclass
class CrawlResult:
    records: list[dict[str, Any]] = field(default_factory=list)
    pages_visited: int = 0
    pages_skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    complete: bool = True


def _dependencies() -> tuple[Any, Any]:
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - exercised by CLI installs
        raise ScrapeError(
            "Websynkronisering kræver pakkerne requests og beautifulsoup4. "
            "Installér skillens requirements.txt."
        ) from exc
    return requests, BeautifulSoup


def _now_iso() -> str:
    return datetime.now(TIMEZONE).replace(microsecond=0).isoformat()


def _space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _safe_url(raw: str, base_url: str = "") -> str:
    raw = _space(raw)
    if not raw or raw.startswith(("mailto:", "tel:", "javascript:", "#")):
        return ""
    absolute = urljoin(base_url, raw)
    parsed = urlparse(absolute)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", "", urlencode(query), "")
    )


def _host_allowed(url: str, allowed_hosts: set[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in allowed_hosts)


def _is_html_page_link(url: str) -> bool:
    """Return whether the crawler can safely treat the link as an HTML page."""

    return not urlparse(url).path.casefold().endswith(NON_HTML_SUFFIXES)


def _assert_safe_public_url(url: str, allowed_hosts: set[str]) -> None:
    """Reject credentials, non-HTTPS and local/private network destinations."""

    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold().rstrip(".")
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or not _host_allowed(url, {item.casefold().rstrip(".") for item in allowed_hosts})
    ):
        raise ScrapeError("Netværkskilden skal være en tilladt HTTPS-host uden indlejrede credentials.")
    if host == "localhost" or host.endswith(".localhost"):
        raise ScrapeError("Lokale netværksmål er ikke tilladt.")
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
        addresses = [literal]
    except ValueError:
        try:
            addresses = [
                ipaddress.ip_address(item[4][0].split("%", 1)[0])
                for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
            ]
        except (OSError, ValueError) as exc:
            raise ScrapeError(f"Kildens host kunne ikke DNS-valideres: {host}") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ScrapeError("Kilden eller redirectet peger på en privat, lokal eller reserveret IP-adresse.")


def _download_public_bytes(
    url: str,
    *,
    allowed_hosts: set[str],
    timeout_seconds: float,
    max_bytes: int,
    accept: str,
) -> tuple[bytes, str, str]:
    requests, _ = _dependencies()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": accept})
    current = _safe_url(url)
    try:
        for _ in range(6):
            _assert_safe_public_url(current, allowed_hosts)
            try:
                response = session.get(
                    current,
                    timeout=max(10.0, float(timeout_seconds)),
                    stream=True,
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                raise ScrapeError(f"Kunne ikke hente {current}: {exc.__class__.__name__}") from exc
            if response.status_code in {301, 302, 303, 307, 308}:
                location = _safe_url(response.headers.get("Location", ""), current)
                response.close()
                if not location:
                    raise ScrapeError("Downloadkilden returnerede et redirect uden gyldig destination.")
                current = location
                continue
            try:
                response.raise_for_status()
                final_url = _safe_url(response.url) or current
                _assert_safe_public_url(final_url, allowed_hosts)
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ScrapeError(f"Downloadet overstiger sikkerhedsgrænsen på {max_bytes} byte.")
                    chunks.append(chunk)
                return (
                    b"".join(chunks),
                    final_url,
                    response.headers.get("Content-Type", "").casefold(),
                )
            finally:
                response.close()
        raise ScrapeError("Downloadkilden returnerede for mange redirects.")
    finally:
        session.close()


def _is_relevant_link(text: str, url: str) -> bool:
    haystack = f"{_space(text).casefold()} {urlparse(url).path.casefold()}"
    return any(word in haystack for word in FUNDING_WORDS)


def _main_node(soup: Any) -> Any:
    return soup.select_one("main, article, #content, .entry-content, .prose") or soup.body or soup


def _has_auth_challenge(soup: Any) -> bool:
    if soup.select_one(
        "input[name*='captcha' i], input[name*='otp' i], input[name*='mfa' i], "
        "iframe[src*='captcha' i], .g-recaptcha, [data-sitekey]"
    ):
        return True
    text = _space(soup.get_text(" ", strip=True)).casefold()
    return any(
        marker in text
        for marker in (
            "captcha",
            "to-faktor",
            "tofaktor",
            "multi-factor",
            "engangskode",
            "bekræft at du er et menneske",
            "verify you are human",
        )
    )


def _structured_fields(main: Any) -> dict[str, str]:
    fields: dict[str, str] = {}
    for row in main.select("dl"):
        labels = row.select("dt")
        values = row.select("dd")
        for label, value in zip(labels, values):
            key = _space(label.get_text(" ", strip=True))
            val = _space(value.get_text(" ", strip=True))
            if key and val:
                fields[key[:160]] = val[:2000]
    for row in main.select("table tr"):
        cells = row.select(":scope > th, :scope > td")
        if len(cells) == 2:
            key = _space(cells[0].get_text(" ", strip=True))
            val = _space(cells[1].get_text(" ", strip=True))
            if key and val and len(key) <= 160:
                fields.setdefault(key, val[:2000])
    for node in main.select("p, li"):
        text = _space(node.get_text(" ", strip=True))
        if ":" not in text or len(text) > 2500:
            continue
        key, value = text.split(":", 1)
        if 2 <= len(key.strip()) <= 80 and value.strip():
            lowered = key.casefold()
            if any(word in lowered for word in ("frist", "beløb", "beloeb", "geografi", "søge", "soege", "krav")):
                fields.setdefault(_space(key), _space(value)[:2000])
    return fields


def _external_official_url(main: Any, page_url: str, excluded_hosts: set[str]) -> str:
    page_host = (urlparse(page_url).hostname or "").lower()
    candidates: list[tuple[int, str]] = []
    for anchor in main.select("a[href]"):
        url = _safe_url(anchor.get("href", ""), page_url)
        host = (urlparse(url).hostname or "").lower()
        if not url or host == page_host or host in excluded_hosts or host in SOCIAL_HOSTS:
            continue
        text = _space(anchor.get_text(" ", strip=True)).casefold()
        score = 0
        if any(word in text for word in ("officiel", "hjemmeside", "ansøg", "ansoeg", "læs mere", "laes mere")):
            score += 4
        if any(word in url.casefold() for word in FUNDING_WORDS):
            score += 2
        if urlparse(url).scheme == "https":
            score += 1
        candidates.append((score, url))
    return max(candidates, default=(0, ""))[1]


def extract_fund_record(
    html: str,
    page_url: str,
    *,
    source_name: str,
    source_kind: str,
    geography: str = "",
    official_url: str = "",
    force: bool = False,
    excluded_external_hosts: Iterable[str] = (),
) -> dict[str, Any] | None:
    """Extract a compact fund candidate from one HTML page.

    Page text is untrusted data. Only bounded metadata and labeled fields are
    returned; scripts, forms and full HTML are never retained.
    """

    _, BeautifulSoup = _dependencies()
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script, style, noscript, form, nav, footer"):
        node.decompose()
    main = _main_node(soup)
    heading = main.select_one("h1") or soup.select_one("h1")
    title = _space(heading.get_text(" ", strip=True) if heading else "")
    if not title:
        title_tag = soup.select_one("title")
        title = _space(title_tag.get_text(" ", strip=True) if title_tag else "")
        title = re.split(r"\s+[|–—-]\s+", title, maxsplit=1)[0]
    text = _space(main.get_text(" ", strip=True))
    lowered = f"{title} {text[:6000]}".casefold()
    if not title or (not force and not any(word in lowered for word in REQUIREMENT_WORDS)):
        return None
    if title.casefold() in {"fonde", "puljer", "login", "mine fonde", "søg støtte", "soeg stoette"}:
        return None
    structured = _structured_fields(main)
    if source_kind == "licensed_directory":
        structured = {
            key[:120]: value[:500]
            for key, value in list(structured.items())[:20]
        }
    external = official_url or _external_official_url(
        main, page_url, {host.lower() for host in excluded_external_hosts}
    )
    status = "directory_only" if source_kind == "licensed_directory" else "discovered_official"
    return {
        "name": title[:500],
        "type": "Fond/pulje",
        "official_url": external or (page_url if source_kind != "licensed_directory" else ""),
        "url": external or (page_url if source_kind != "licensed_directory" else ""),
        "directory_url": page_url,
        "geography": geography,
        "description": text[:600] if source_kind == "licensed_directory" else text[:3000],
        "verification_status": status,
        "last_seen_at": _now_iso(),
        "source_name": source_name,
        "source_kind": source_kind,
        "source_url": page_url,
        "extra": {"labeled_fields": structured},
    }


def sync_state_grants_feed(
    *,
    feed_url: str = STATE_GRANTS_FEED,
    include_inactive: bool = False,
    include_all_active: bool = False,
    timeout_seconds: float = 60.0,
) -> tuple[CrawlResult, dict[str, int]]:
    """Read the official semicolon-separated Danish state grants feed.

    The provider explicitly publishes the export as open basic data. By
    default, active rows are filtered with broad association/sport keywords;
    ``include_all_active`` can retain every active government opportunity.
    """

    try:
        content, final_url, _content_type = _download_public_bytes(
            feed_url,
            allowed_hosts={"statens-tilskudspuljer.dk", "www.statens-tilskudspuljer.dk"},
            timeout_seconds=timeout_seconds,
            max_bytes=25 * 1024 * 1024,
            accept="text/csv,*/*;q=0.5",
        )
    except Exception as exc:
        if isinstance(exc, ScrapeError):
            raise
        raise ScrapeError(f"Kunne ikke hente Statens Tilskudspuljer-feedet: {exc.__class__.__name__}") from exc

    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    result = CrawlResult(pages_visited=1)
    counts = {"total": 0, "active": 0, "included": 0, "filtered_irrelevant": 0}
    for raw_row in reader:
        # Det offentlige feed har historisk haft enkelte rækker med flere
        # afsluttende felter end headeren. DictReader lægger dem under None som
        # en liste; de er ikke navngivne data og skal derfor ignoreres.
        row = {
            key.strip(): _space(value or "")
            for key, value in raw_row.items()
            if isinstance(key, str) and key.strip()
        }
        counts["total"] += 1
        active = row.get("IsActive", "").casefold() == "true"
        if active:
            counts["active"] += 1
        if not active and not include_inactive:
            continue
        haystack = " ".join(
            (row.get("Title", ""), row.get("Keywords", ""), row.get("AuthorityName", ""))
        ).casefold()
        if active and not include_all_active and not any(word in haystack for word in ASSOCIATION_RELEVANCE_WORDS):
            counts["filtered_irrelevant"] += 1
            continue
        title = row.get("Title", "")
        if not title:
            continue
        official_url = row.get("PoolViewLink", "") or row.get("AuthorityPoolApplicationLink", "")
        keywords = [item.strip() for item in row.get("Keywords", "").split(",") if item.strip()]
        next_deadline = row.get("NextDeadline", "")
        all_deadlines = row.get("AllDeadlines", "")
        record = {
            "name": title,
            "provider": row.get("AuthorityName", ""),
            "type": "Statslig pulje",
            "official_url": official_url,
            "url": official_url,
            "directory_url": final_url,
            "geography": "Danmark/EU" if row.get("IsEUFunded", "").casefold() == "true" else "Danmark",
            "purposes": keywords,
            "deadline": next_deadline or all_deadlines,
            "verification_status": "discovered_official" if active else "closed",
            "last_seen_at": _now_iso(),
            "source_name": "Statens Tilskudspuljer",
            "source_kind": "official_feed",
            "source_url": final_url,
            "extra": {
                "active": active,
                "is_eu_funded": row.get("IsEUFunded", "").casefold() == "true",
                "all_deadlines": all_deadlines,
                "modified": row.get("Modified", ""),
                "application_url": row.get("AuthorityPoolApplicationLink", ""),
            },
        }
        result.records.append(record)
        counts["included"] += 1
    return result, counts


def _metadata_values(metadata: dict[str, Any], key: str) -> list[Any]:
    value = metadata.get(key, [])
    if value in (None, ""):
        return []
    return value if isinstance(value, list) else [value]


def _metadata_text(metadata: dict[str, Any], key: str) -> str:
    values = _metadata_values(metadata, key)
    return _space(str(values[0])) if values else ""


def _metadata_json(metadata: dict[str, Any], key: str, default: Any) -> Any:
    values = _metadata_values(metadata, key)
    if not values:
        return default
    value = values[0]
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _plain_html(value: str, *, limit: int) -> str:
    # API text is untrusted content. Strip tags and retain only a compact
    # discovery summary, not a local copy of the programme documentation.
    without_tags = re.sub(r"<[^>]*>", " ", value or "")
    return _space(html_module.unescape(without_tags))[:limit]


def _eu_program_name(identifier: str) -> str:
    prefix = identifier.split("-", 1)[0].upper()
    return {
        "ERASMUS": "Erasmus+",
        "CERV": "Citizens, Equality, Rights and Values",
        "ESC": "European Solidarity Corps",
        "CREA": "Creative Europe",
        "LIFE": "LIFE",
        "HORIZON": "Horizon Europe",
        "DIGITAL": "Digital Europe",
        "AMIF": "Asylum, Migration and Integration Fund",
    }.get(prefix, prefix)


def _eu_relevance_signals(metadata: dict[str, Any]) -> list[str]:
    identifier = _metadata_text(metadata, "identifier").upper()
    if any(identifier.startswith(prefix) for prefix in EU_RELEVANT_IDENTIFIER_PREFIXES):
        prefix_signal = [f"program:{identifier.split('-', 2)[0]}"]
    else:
        prefix_signal = []
    # Portal keywords can be an exhaustive taxonomy unrelated to the topic,
    # so only title/call/tags and a bounded scope description are considered.
    searchable = " ".join(
        [
            _metadata_text(metadata, "title"),
            _metadata_text(metadata, "callTitle"),
            " ".join(str(item) for item in _metadata_values(metadata, "tags")),
            _plain_html(_metadata_text(metadata, "descriptionByte"), limit=6000),
        ]
    ).casefold()
    words = []
    for word in EU_ASSOCIATION_RELEVANCE_WORDS:
        phrase = re.escape(word).replace(r"\ ", r"\s+")
        if re.search(rf"(?<!\w){phrase}(?!\w)", searchable, re.IGNORECASE):
            words.append(word)
    return (prefix_signal + words)[:30]


def _eu_deadlines(metadata: dict[str, Any]) -> list[str]:
    values: list[Any] = list(_metadata_values(metadata, "deadlineDate"))
    actions = _metadata_json(metadata, "actions", [])
    if isinstance(actions, list):
        for action in actions:
            if isinstance(action, dict) and isinstance(action.get("deadlineDates"), list):
                values.extend(action["deadlineDates"])
    result: list[str] = []
    for value in values:
        candidate = str(value).strip()[:10]
        try:
            datetime.strptime(candidate, "%Y-%m-%d")
        except ValueError:
            continue
        if candidate not in result:
            result.append(candidate)
    return sorted(result)


def _eu_budget_summary(metadata: dict[str, Any], identifier: str) -> tuple[str, dict[str, Any]]:
    overview = _metadata_json(metadata, "budgetOverview", {})
    if not isinstance(overview, dict):
        return "", {}
    action_map = overview.get("budgetTopicActionMap", {})
    if not isinstance(action_map, dict):
        return "", {}
    entries: list[dict[str, Any]] = []
    for rows in action_map.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and str(row.get("action", "")).startswith(identifier + " "):
                entries.append(row)
    if not entries:
        return "", {}
    def number(value: Any) -> float:
        try:
            parsed = float(value or 0)
        except (TypeError, ValueError):
            return 0.0
        return parsed if math.isfinite(parsed) else 0.0

    minimums = [number(row.get("minContribution", 0)) for row in entries]
    maximums = [number(row.get("maxContribution", 0)) for row in entries]
    programme_budgets: list[float] = []
    for row in entries:
        years = row.get("budgetYearMap", {})
        if isinstance(years, dict):
            for value in years.values():
                try:
                    parsed = float(value)
                    if math.isfinite(parsed):
                        programme_budgets.append(parsed)
                except (TypeError, ValueError):
                    continue
    positive_mins = [value for value in minimums if value > 0]
    positive_maxes = [value for value in maximums if value > 0]
    amount = ""
    if positive_mins and positive_maxes:
        amount = f"EUR {min(positive_mins):,.0f}–{max(positive_maxes):,.0f}"
    elif positive_maxes:
        amount = f"Op til EUR {max(positive_maxes):,.0f}"
    return amount, {
        "programme_budget_eur": sum(programme_budgets) if programme_budgets else None,
        "min_contribution_eur": min(positive_mins) if positive_mins else None,
        "max_contribution_eur": max(positive_maxes) if positive_maxes else None,
    }


def _eu_submission_url(metadata: dict[str, Any]) -> str:
    links = _metadata_json(metadata, "links", [])
    if not isinstance(links, list):
        return ""
    for item in links:
        if not isinstance(item, dict):
            continue
        candidate = _safe_url(str(item.get("url", "")))
        if candidate and _host_allowed(candidate, {"ec.europa.eu", "europa.eu"}):
            return candidate
    return ""


def _normalize_eu_result(item: dict[str, Any], *, api_version: str) -> dict[str, Any] | None:
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        return None
    identifier = _metadata_text(metadata, "identifier") or _space(str(item.get("reference", "")))
    title = _metadata_text(metadata, "title") or _space(str(item.get("summary", "")))
    if not identifier or not title:
        return None
    official_url = _safe_url(
        _metadata_text(metadata, "url") or _metadata_text(metadata, "esST_URL") or str(item.get("url", ""))
    )
    if not official_url or not _host_allowed(official_url, {"ec.europa.eu", "europa.eu"}):
        return None
    signals = _eu_relevance_signals(metadata)
    deadlines = _eu_deadlines(metadata)
    today = datetime.now(TIMEZONE).date().isoformat()
    future_deadlines = [value for value in deadlines if value >= today]
    deadline = min(future_deadlines) if future_deadlines else (max(deadlines) if deadlines else "")
    expired_by_deadline = bool(deadlines) and max(deadlines) < today
    start = _metadata_text(metadata, "startDate")
    status_code = _metadata_text(metadata, "status")
    type_code = _metadata_text(metadata, "type")
    amount, budget = _eu_budget_summary(metadata, identifier)
    tags = [_space(str(value)) for value in _metadata_values(metadata, "tags") if _space(str(value))]
    call_identifier = _metadata_text(metadata, "callIdentifier")
    programme = _eu_program_name(identifier)
    checked = _now_iso()
    return {
        # Include the stable topic identifier in the name so recurring calls
        # with identical titles do not collapse into one domain/name record.
        "name": f"{title} — {identifier}"[:500],
        "provider": "European Commission / Funding & Tenders Portal",
        "type": f"EU {EU_TYPE_LABELS.get(type_code, 'opportunity')}",
        "official_url": official_url,
        "url": official_url,
        "directory_url": EU_FUNDING_API_DOCS,
        "geography": "EU/internationalt",
        "purposes": tags[:30],
        "description": _plain_html(_metadata_text(metadata, "descriptionByte"), limit=1500),
        "amount": amount,
        "deadline": deadline,
        "verification_status": "closed" if expired_by_deadline else "discovered_official",
        "last_checked": checked[:10],
        "last_seen_at": checked,
        "relevance": "Automatisk EU-discovery; kontrollér ansøgerberettigelse og alle krav på topicsiden.",
        "source_name": "EU Funding & Tenders Portal API",
        "source_kind": "official_api",
        "source_url": official_url,
        "source_record_id": identifier,
        "extra": {
            "identifier": identifier,
            "call_identifier": call_identifier,
            "call_title": _metadata_text(metadata, "callTitle"),
            "programme": programme,
            "programme_period": _metadata_text(metadata, "programmePeriod"),
            "status_code": status_code,
            "status_label": EU_STATUS_LABELS.get(status_code, status_code),
            "deadlines": deadlines,
            "expired_by_official_deadline": expired_by_deadline,
            "type_code": type_code,
            "planned_start": start[:10] if start else "",
            "relevance_signals": signals,
            "budget": budget,
            "application_url": _eu_submission_url(metadata),
            "topic_conditions_available": bool(_metadata_text(metadata, "topicConditions")),
            "support_info_available": bool(_metadata_text(metadata, "supportInfo")),
            "api_version": api_version,
        },
    }


def sync_eu_funding_feed(
    *,
    include_all_open: bool = False,
    page_size: int = 50,
    max_pages: int = 100,
    delay_seconds: float = 1.0,
    timeout_seconds: float = 60.0,
) -> tuple[CrawlResult, dict[str, Any]]:
    """Discover open/forthcoming official EU Funding & Tenders opportunities.

    The public Search API uses the documented SEDIA service selector and no
    user credential. Results remain ``discovered_official`` because topic
    eligibility and application documents still require per-fund research.
    """

    requests, _ = _dependencies()
    page_size = max(1, min(int(page_size), 100))
    max_pages = max(1, min(int(max_pages), 200))
    delay_seconds = max(1.0, float(delay_seconds))
    timeout_seconds = max(10.0, float(timeout_seconds))
    query = {
        "bool": {
            "must": [
                {"terms": {"type": ["1", "2", "8"]}},
                {"terms": {"status": ["31094501", "31094502"]}},
                {"terms": {"language": ["en"]}},
            ]
        }
    }
    # Identifier gives stable page boundaries; deadlineDate has many ties and
    # produced shifting duplicates between otherwise identical full runs.
    sort = {"order": "ASC", "field": "identifier"}
    result = CrawlResult()
    counts: dict[str, Any] = {
        "available": 0,
        "processed": 0,
        "included": 0,
        "filtered_irrelevant": 0,
        "duplicates": 0,
        "invalid": 0,
        "truncated": False,
        "api_version": "",
    }
    seen: set[str] = set()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        page_number = 1
        pages_to_fetch = 1
        while page_number <= pages_to_fetch and page_number <= max_pages:
            files = {
                "query": ("blob", json.dumps(query), "application/json"),
                "sort": ("blob", json.dumps(sort), "application/json"),
                "languages": ("blob", json.dumps(["en"]), "application/json"),
            }
            response = None
            for attempt in range(1, 4):
                try:
                    response = session.post(
                        EU_FUNDING_SEARCH_ENDPOINT,
                        params={
                            "apiKey": "SEDIA",
                            "text": "***",
                            "pageSize": page_size,
                            "pageNumber": page_number,
                        },
                        files=files,
                        timeout=timeout_seconds,
                        allow_redirects=False,
                        stream=True,
                    )
                except requests.RequestException as exc:
                    if attempt == 3:
                        raise ScrapeError(
                            f"Kunne ikke hente EU Funding API side {page_number}: {exc.__class__.__name__}"
                        ) from exc
                    time.sleep(delay_seconds * attempt)
                    continue
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                    response.close()
                    time.sleep(delay_seconds * attempt)
                    continue
                break
            assert response is not None
            try:
                if 300 <= response.status_code < 400:
                    raise ScrapeError("EU Funding API returnerede et uventet redirect.")
                try:
                    response.raise_for_status()
                except requests.RequestException as exc:
                    raise ScrapeError(
                        f"EU Funding API afviste side {page_number} med HTTP {response.status_code}."
                    ) from exc
                chunks: list[bytes] = []
                response_size = 0
                for chunk in response.iter_content(65536):
                    response_size += len(chunk)
                    if response_size > 10 * 1024 * 1024:
                        raise ScrapeError("Et EU Funding API-svar overstiger sikkerhedsgrænsen på 10 MB.")
                    chunks.append(chunk)
                response_bytes = b"".join(chunks)
            finally:
                response.close()
            try:
                payload = json.loads(response_bytes.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
                raise ScrapeError("EU Funding API returnerede ikke gyldig JSON.") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                raise ScrapeError("EU Funding API-svaret havde et ukendt format.")
            try:
                total = max(0, int(payload.get("totalResults", 0)))
            except (TypeError, ValueError):
                total = 0
            counts["available"] = max(int(counts["available"]), total)
            counts["api_version"] = _space(str(payload.get("apiVersion", "")))[:50]
            pages_to_fetch = max(1, math.ceil(total / page_size)) if total else page_number
            for item in payload["results"]:
                counts["processed"] += 1
                if not isinstance(item, dict):
                    counts["invalid"] += 1
                    continue
                record = _normalize_eu_result(item, api_version=str(counts["api_version"]))
                if record is None:
                    counts["invalid"] += 1
                    continue
                identifier = str(record["source_record_id"])
                signals = record["extra"].get("relevance_signals", [])
                if not include_all_open and not signals:
                    counts["filtered_irrelevant"] += 1
                    continue
                if identifier in seen:
                    counts["duplicates"] += 1
                    continue
                seen.add(identifier)
                result.records.append(record)
                counts["included"] += 1
            result.pages_visited += 1
            page_number += 1
            if page_number <= pages_to_fetch and page_number <= max_pages:
                time.sleep(delay_seconds)
        if pages_to_fetch > max_pages:
            counts["truncated"] = True
            result.complete = False
            result.warnings.append(
                f"EU-feedet krævede {pages_to_fetch} sider, men max_pages var {max_pages}."
            )
    finally:
        session.close()
    if result.pages_visited == 0:
        raise ScrapeError("Ingen sider blev hentet fra EU Funding API.")
    return result, counts


def fetch_current_dgi_workbook(
    *, landing_url: str = DGI_FUNDS_LANDING, timeout_seconds: float = 60.0
) -> tuple[bytes, str]:
    """Discover and download DGI's current public fund workbook.

    The opaque Mimer document URL is intentionally discovered from the stable
    landing page on every run instead of being committed as a permanent URL.
    """

    _, BeautifulSoup = _dependencies()
    try:
        landing_content, landing_final_url, _ = _download_public_bytes(
            landing_url,
            allowed_hosts={"dgi.dk", "www.dgi.dk"},
            timeout_seconds=timeout_seconds,
            max_bytes=MAX_RESPONSE_BYTES,
            accept="text/html,application/xhtml+xml",
        )
    except Exception as exc:
        if isinstance(exc, ScrapeError):
            raise
        raise ScrapeError(f"Kunne ikke hente DGI's fondsoversigt: {exc.__class__.__name__}") from exc
    landing_text = landing_content.decode("utf-8", errors="replace")
    soup = BeautifulSoup(landing_text, "html.parser")
    candidates = [
        _safe_url(html_module.unescape(anchor.get("href", "")), landing_final_url)
        for anchor in soup.select("a[href]")
    ]
    if not any("xlsx" in candidate.casefold() or "xls" in candidate.casefold() for candidate in candidates):
        decoded = html_module.unescape(landing_text)
        candidates.extend(
            _safe_url(match, landing_url)
            for match in re.findall(r"https?://[^\"'<>\s]+(?:xlsx|xls)[^\"'<>\s]*", decoded, re.IGNORECASE)
        )
    workbook_url = next(
        (
            candidate
            for candidate in candidates
            if candidate
            and ("xlsx" in candidate.casefold() or "xls" in candidate.casefold())
            and _host_allowed(candidate, {"dgi.dk", "mimer.dgi.dk"})
        ),
        "",
    )
    if not workbook_url:
        raise ScrapeError("DGI-landingssiden indeholdt ikke et genkendeligt Excel-download.")
    try:
        content, final_url, _ = _download_public_bytes(
            workbook_url,
            allowed_hosts={"dgi.dk", "www.dgi.dk", "mimer.dgi.dk"},
            timeout_seconds=timeout_seconds,
            max_bytes=25 * 1024 * 1024,
            accept="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*;q=0.5",
        )
    except Exception as exc:
        if isinstance(exc, ScrapeError):
            raise
        raise ScrapeError(f"Kunne ikke hente DGI-regnearket: {exc.__class__.__name__}") from exc
    if not content.startswith(b"PK"):
        raise ScrapeError("DGI-downloadet var ikke en gyldig XLSX-fil.")
    return content, final_url


class _Crawler:
    def __init__(self, *, delay_seconds: float = 1.25, timeout_seconds: float = 30.0) -> None:
        requests, _ = _dependencies()
        self.requests = requests
        self.delay_seconds = max(float(delay_seconds), 1.0)
        self.timeout_seconds = max(float(timeout_seconds), 5.0)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "da,en;q=0.7"})
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last_request_at = 0.0

    def close(self) -> None:
        self.session.close()

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)

    def _safe_get_response(self, url: str, *, allowed_hosts: set[str]) -> Any:
        current = url
        for _ in range(6):
            _assert_safe_public_url(current, allowed_hosts)
            self._wait()
            try:
                response = self.session.get(
                    current,
                    timeout=self.timeout_seconds,
                    stream=True,
                    allow_redirects=False,
                )
                self._last_request_at = time.monotonic()
            except self.requests.RequestException as exc:
                raise ScrapeError(f"Kunne ikke hente {current}: {exc.__class__.__name__}") from exc
            if response.status_code in {301, 302, 303, 307, 308}:
                location = _safe_url(response.headers.get("Location", ""), current)
                response.close()
                if not location:
                    raise ScrapeError("Kilden returnerede et redirect uden gyldig destination.")
                current = location
                continue
            try:
                response.raise_for_status()
            except self.requests.RequestException as exc:
                response.close()
                raise ScrapeError(f"Kunne ikke hente {current}: {exc.__class__.__name__}") from exc
            _assert_safe_public_url(_safe_url(response.url) or current, allowed_hosts)
            return response
        raise ScrapeError("Kilden returnerede for mange redirects.")

    def _get(self, url: str, *, allowed_hosts: set[str]) -> tuple[str, str]:
        response = self._safe_get_response(url, allowed_hosts=allowed_hosts)
        try:
            content_type = response.headers.get("Content-Type", "").casefold()
            if "html" not in content_type and "xhtml" not in content_type:
                raise ScrapeError(f"Ikke-HTML svar fra {url}: {content_type or 'ukendt type'}")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ScrapeError(f"Siden er større end {MAX_RESPONSE_BYTES} byte: {url}")
                chunks.append(chunk)
            payload = b"".join(chunks)
            encoding = response.encoding or "utf-8"
            return payload.decode(encoding, errors="replace"), _safe_url(response.url)
        finally:
            response.close()

    def _robots_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        if root not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(root + "/robots.txt")
            try:
                response = self._safe_get_response(
                    parser.url,
                    allowed_hosts={(parsed.hostname or "").casefold()},
                )
                try:
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > 512 * 1024:
                            raise ScrapeError("robots.txt oversteg sikkerhedsgrænsen på 512 KB.")
                        chunks.append(chunk)
                    encoding = response.encoding or "utf-8"
                    parser.parse(b"".join(chunks).decode(encoding, errors="replace").splitlines())
                    self._robots[root] = parser
                finally:
                    response.close()
            except ScrapeError:
                self._robots[root] = None
        parser = self._robots[root]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)


class PublicSourceCrawler(_Crawler):
    """Crawl only URLs declared in the committed source registry."""

    def crawl(self, source: dict[str, Any], *, max_pages: int = 50) -> CrawlResult:
        start = _safe_url(str(source.get("url", "")))
        if not start:
            raise ScrapeError("Kilden mangler en gyldig http(s)-URL.")
        max_pages = max(1, min(int(max_pages), 500))
        allowed_hosts = {
            (urlparse(start).hostname or "").lower(),
            *{str(value).lower() for value in source.get("allowed_hosts", [])},
        }
        max_depth = max(0, min(int(source.get("crawl_depth", 1)), 2))
        queue: deque[tuple[str, int, str]] = deque([(start, 0, str(source.get("name", "")))])
        queued = {start}
        visited: set[str] = set()
        result = CrawlResult()
        depth_warning_added = False

        while queue and len(visited) < max_pages:
            url, depth, anchor_text = queue.popleft()
            if url in visited:
                continue
            visited.add(url)
            if not self._robots_allowed(url):
                result.pages_skipped += 1
                result.complete = False
                result.warnings.append(f"robots.txt fravalgte {url}")
                continue
            try:
                html, final_url = self._get(url, allowed_hosts=allowed_hosts)
            except ScrapeError as exc:
                result.pages_skipped += 1
                result.complete = False
                result.warnings.append(str(exc))
                continue
            result.pages_visited += 1
            force = str(source.get("kind", "directory")) == "opportunity" and depth == 0
            record = extract_fund_record(
                html,
                final_url,
                source_name=str(source.get("name", "Officiel kilde")),
                source_kind="official_web",
                geography=str(source.get("geography", "")),
                force=force,
            )
            if record and (depth > 0 or force):
                result.records.append(record)
            elif depth > 0 and _is_relevant_link(anchor_text, final_url):
                result.records.append(
                    {
                        "name": _space(anchor_text)[:500] or urlparse(final_url).path.rstrip("/").split("/")[-1],
                        "type": "Fond/pulje",
                        "official_url": final_url,
                        "url": final_url,
                        "directory_url": start,
                        "geography": str(source.get("geography", "")),
                        "verification_status": "candidate",
                        "last_seen_at": _now_iso(),
                        "source_name": str(source.get("name", "Officiel kilde")),
                        "source_kind": "official_web",
                        "source_url": final_url,
                        "extra": {},
                    }
                )
            _, BeautifulSoup = _dependencies()
            soup = BeautifulSoup(html, "html.parser")
            main = _main_node(soup)
            followable: list[tuple[str, str]] = []
            for anchor in main.select("a[href]"):
                link = _safe_url(anchor.get("href", ""), final_url)
                text = _space(anchor.get_text(" ", strip=True))
                path = urlparse(link).path.casefold()
                if (
                    not link
                    or link in queued
                    or not _host_allowed(link, allowed_hosts)
                    or not _is_html_page_link(link)
                    or any(part in path for part in SKIP_PATH_PARTS)
                    or not _is_relevant_link(text, link)
                ):
                    continue
                followable.append((link, text or anchor_text))
            if depth >= max_depth:
                if followable:
                    result.complete = False
                    if not depth_warning_added:
                        result.warnings.append(
                            f"Kilden blev afkortet ved crawl_depth={max_depth}; "
                            "dækningskørslen er ikke komplet."
                        )
                        depth_warning_added = True
                continue
            for link, text in followable:
                queued.add(link)
                queue.append((link, depth + 1, text))
        if queue:
            result.complete = False
            result.warnings.append(
                f"Kilden blev afkortet ved max_pages={max_pages}; dækningskørslen er ikke komplet."
            )
        return result


class FundraisingClubCrawler(_Crawler):
    """Use the subscriber's own account to normalize Fundraising Club metadata."""

    def __init__(
        self,
        *,
        base_url: str = "https://app.fundraisingclub.dk",
        delay_seconds: float = 1.5,
        timeout_seconds: float = 30.0,
        confirm_authorized_use: bool = False,
    ) -> None:
        if not confirm_authorized_use:
            raise ScrapeError(
                "Kør kun den autentificerede scraper, når brugeren har bekræftet egen adgang "
                "og at brugen er tilladt; brug --confirm-authorized-use."
            )
        super().__init__(delay_seconds=delay_seconds, timeout_seconds=timeout_seconds)
        self.base_url = _safe_url(base_url).rstrip("/")
        parsed_base = urlparse(self.base_url)
        if (
            not self.base_url
            or parsed_base.scheme != "https"
            or (parsed_base.hostname or "").lower() != "app.fundraisingclub.dk"
            or parsed_base.username
            or parsed_base.password
        ):
            raise ScrapeError("FUNDRAISINGCLUB_BASE_URL skal pege på app.fundraisingclub.dk.")

    def _private_html_request(
        self,
        method: str,
        url: str,
        *,
        data: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        """Follow only same-host HTTPS redirects; never replay login data on 307/308."""

        host = "app.fundraisingclub.dk"
        current = _safe_url(url, self.base_url + "/")
        request_method = method.upper()
        request_data = data
        for _ in range(6):
            parsed = urlparse(current)
            if (
                parsed.scheme != "https"
                or (parsed.hostname or "").lower() != host
                or parsed.username
                or parsed.password
            ):
                raise ScrapeError("Fundraising Club-request eller redirect forlod den tilladte HTTPS-host.")
            _assert_safe_public_url(current, {host})
            self._wait()
            try:
                response = self.session.request(
                    request_method,
                    current,
                    data=request_data,
                    timeout=self.timeout_seconds,
                    stream=True,
                    allow_redirects=False,
                )
                self._last_request_at = time.monotonic()
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = _safe_url(response.headers.get("Location", ""), current)
                    if not location:
                        raise ScrapeError("Fundraising Club returnerede et redirect uden gyldig destination.")
                    if request_method == "POST" and response.status_code in {307, 308}:
                        raise ScrapeError("Login stoppet: serveren bad om at gensende credentials via redirect.")
                    current = location
                    request_method = "GET"
                    request_data = None
                    response.close()
                    continue
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").casefold()
                if "html" not in content_type and "xhtml" not in content_type:
                    raise ScrapeError("Fundraising Club returnerede ikke HTML.")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise ScrapeError("Fundraising Club-svaret overskred størrelsesgrænsen.")
                    chunks.append(chunk)
                payload = b"".join(chunks)
                encoding = response.encoding or "utf-8"
                return payload.decode(encoding, errors="replace"), _safe_url(response.url)
            except self.requests.RequestException as exc:
                raise ScrapeError(f"Fundraising Club-request fejlede: {exc.__class__.__name__}") from exc
        raise ScrapeError("Fundraising Club returnerede for mange redirects.")

    def login(self, username: str, password: str) -> None:
        if not username or not password:
            raise ScrapeError(
                "FUNDRAISINGCLUB_USERNAME og FUNDRAISINGCLUB_PASSWORD skal sættes i miljøet eller .env."
            )
        login_url = self.base_url + "/login/?redirect=" + self.base_url + "/"
        html, final_url = self._private_html_request("GET", login_url)
        _, BeautifulSoup = _dependencies()
        soup = BeautifulSoup(html, "html.parser")
        if _has_auth_challenge(soup):
            raise ScrapeError("Fundraising Club viste MFA/CAPTCHA/challenge; automatiseringen stoppede.")
        form = soup.select_one("form#rcp_login_form, form[action*='/login']")
        if form is None:
            raise ScrapeError("Fundraising Club-loginformularen blev ikke fundet.")
        nonce = form.select_one("input[name='rcp_login_nonce']")
        if nonce is None or not str(nonce.get("value", "")).strip():
            raise ScrapeError("Fundraising Club-login mangler en frisk login-nonce.")
        payload = {
            "rcp_user_login": username,
            "rcp_user_pass": password,
            "rcp_user_remember": "0",
            "rcp_action": "login",
            "rcp_redirect": self.base_url + "/",
            "rcp_login_nonce": nonce.get("value", "") if nonce else "",
        }
        action = _safe_url(form.get("action", ""), final_url) or login_url
        action_parsed = urlparse(action)
        if action_parsed.scheme != "https" or (action_parsed.hostname or "").lower() != "app.fundraisingclub.dk":
            raise ScrapeError("Loginformularens action forlod app.fundraisingclub.dk; credentials blev ikke sendt.")
        response_html, response_url = self._private_html_request("POST", action, data=payload)
        response_soup = BeautifulSoup(response_html, "html.parser")
        if _has_auth_challenge(response_soup):
            raise ScrapeError("Fundraising Club krævede MFA/CAPTCHA/challenge; automatiseringen stoppede.")
        if response_soup.select_one("form#rcp_login_form") or "/login" in urlparse(response_url).path:
            raise ScrapeError("Login til Fundraising Club blev afvist. Kontrollér credentials og abonnement.")

    @staticmethod
    def _catalog_page_info(html: str) -> tuple[int | None, int | None]:
        """Read FacetWP's bounded pager metadata without retaining its JSON payload."""

        values: dict[str, int] = {}
        for key in ("total_rows", "total_pages"):
            match = re.search(rf'["\']{key}["\']\s*:\s*["\']?(\d+)', html, re.IGNORECASE)
            if match:
                values[key] = int(match.group(1))
        return values.get("total_rows"), values.get("total_pages")

    @staticmethod
    def _is_catalog_url(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.path.rstrip("/").casefold() == "/fonde"

    @staticmethod
    def _is_fund_detail_url(url: str) -> bool:
        path = urlparse(url).path
        return bool(re.fullmatch(r"/fonde/[^/]+/?", path, re.IGNORECASE))

    @staticmethod
    def _catalog_url(base_url: str, page: int) -> str:
        if page <= 1:
            return base_url.rstrip("/") + "/fonde/"
        return base_url.rstrip("/") + f"/fonde/?_paged={page}"

    @staticmethod
    def _detail_sections(main: Any) -> dict[str, str]:
        """Extract compact, labeled sections from a subscribed fund detail page."""

        sections: dict[str, str] = {}
        for heading in main.select("h2, h3"):
            label = _space(heading.get_text(" ", strip=True))
            if not label or "nyheder" in label.casefold() or len(sections) >= 10:
                continue
            parts: list[str] = []
            total = 0
            for node in heading.next_siblings:
                if getattr(node, "name", None) in {"h1", "h2", "h3"}:
                    break
                if not hasattr(node, "get_text"):
                    continue
                value = _space(node.get_text(" ", strip=True))
                if not value:
                    continue
                remaining = 1500 - total
                if remaining <= 0:
                    break
                parts.append(value[:remaining])
                total += len(parts[-1])
            value = _space(" ".join(parts))
            if value:
                sections[label[:120]] = value[:1500]
        return sections

    def _extract_detail_record(self, html: str, final_url: str, host: str) -> dict[str, Any] | None:
        record = extract_fund_record(
            html,
            final_url,
            source_name="Fundraising Club",
            source_kind="licensed_directory",
            geography="Danmark",
            # Detail-URL'en er allerede afgrænset af det autentificerede
            # `/fonde/`-katalog, så også korte poster uden kravnøgleord skal med.
            force=True,
            excluded_external_hosts={host, "fundraisingclub.dk", "www.fundraisingclub.dk"},
        )
        if not record:
            return None
        _, BeautifulSoup = _dependencies()
        soup = BeautifulSoup(html, "html.parser")
        for node in soup.select("script, style, noscript, form, nav, footer"):
            node.decompose()
        sections = self._detail_sections(_main_node(soup))
        if sections:
            extra = dict(record.get("extra", {}))
            extra["sections"] = sections
            record["extra"] = extra
        record["source_record_id"] = urlparse(final_url).path.rstrip("/").rsplit("/", 1)[-1]
        return record

    def crawl(self, *, start_urls: Iterable[str] = (), max_pages: int = 500, max_depth: int = 3) -> CrawlResult:
        max_pages = max(1, min(int(max_pages), 2000))
        max_depth = max(1, min(int(max_depth), 5))
        starts = list(start_urls) or [self.base_url + "/fonde/"]
        normalized_starts = [_safe_url(value, self.base_url + "/") for value in starts]
        host = (urlparse(self.base_url).hostname or "").lower()
        if any(
            urlparse(url).scheme != "https" or (urlparse(url).hostname or "").lower() != host
            for url in normalized_starts
            if url
        ):
            raise ScrapeError("Alle Fundraising Club-start-URL'er skal ligge på app.fundraisingclub.dk via HTTPS.")
        queue: deque[tuple[str, int]] = deque((url, 0) for url in normalized_starts if url)
        queued = {url for url in normalized_starts if url}
        visited: set[str] = set()
        result = CrawlResult()
        depth_warning_added = False
        expected_rows: int | None = None
        discovered_details: set[str] = set()

        while queue and len(visited) < max_pages:
            url, depth = queue.popleft()
            if url in visited:
                continue
            visited.add(url)
            try:
                html, final_url = self._private_html_request("GET", url)
            except ScrapeError as exc:
                result.pages_skipped += 1
                result.complete = False
                result.warnings.append(str(exc))
                continue
            if "/login" in urlparse(final_url).path:
                raise ScrapeError("Fundraising Club-sessionen udløb under synkronisering.")
            if (urlparse(final_url).hostname or "").lower() != host:
                raise ScrapeError("Fundraising Club-sessionen blev redirectet til en ekstern host.")
            _, BeautifulSoup = _dependencies()
            challenge_soup = BeautifulSoup(html, "html.parser")
            if _has_auth_challenge(challenge_soup):
                raise ScrapeError("Fundraising Club viste MFA/CAPTCHA/challenge; automatiseringen stoppede.")
            result.pages_visited += 1
            soup = BeautifulSoup(html, "html.parser")
            if self._is_catalog_url(final_url):
                rows, total_pages = self._catalog_page_info(html)
                if rows is not None:
                    expected_rows = max(expected_rows or 0, rows)
                if total_pages is None:
                    result.complete = False
                    result.warnings.append(
                        "Fundraising Clubs FacetWP-sideantal kunne ikke aflæses; dækningskørslen er ikke komplet."
                    )
                    total_pages = 1
                for page in range(1, min(total_pages, 1000) + 1):
                    link = self._catalog_url(self.base_url, page)
                    if link not in queued and link not in visited:
                        queued.add(link)
                        queue.append((link, depth))
                detail_links: list[str] = []
                for anchor in _main_node(soup).select("a[href]"):
                    link = _safe_url(anchor.get("href", ""), final_url)
                    if (
                        link
                        and (urlparse(link).hostname or "").lower() == host
                        and self._is_fund_detail_url(link)
                    ):
                        clean = urlunparse(urlparse(link)._replace(query="", fragment=""))
                        discovered_details.add(clean)
                        if clean not in queued and clean not in visited:
                            detail_links.append(clean)
                if depth >= max_depth:
                    if detail_links:
                        result.complete = False
                        if not depth_warning_added:
                            result.warnings.append(
                                f"Fundraising Club blev afkortet ved max_depth={max_depth}; "
                                "dækningskørslen er ikke komplet."
                            )
                            depth_warning_added = True
                else:
                    for link in detail_links:
                        queued.add(link)
                        queue.append((link, depth + 1))
                continue

            if self._is_fund_detail_url(final_url):
                record = self._extract_detail_record(html, final_url, host)
                if record:
                    result.records.append(record)
                else:
                    result.complete = False
                    result.warnings.append(
                        f"Fondssiden {urlparse(final_url).path} gav ingen genkendelig fondspost."
                    )
                continue

            result.complete = False
            result.pages_skipped += 1
            result.warnings.append(
                f"Fundraising Club-startsiden {urlparse(final_url).path} var hverken katalog eller fondsdetalje."
            )
        if queue:
            result.complete = False
            result.warnings.append(
                f"Fundraising Club blev afkortet ved max_pages={max_pages}; dækningskørslen er ikke komplet."
            )
        if expected_rows is not None and len(discovered_details) != expected_rows:
            result.complete = False
            result.warnings.append(
                "Fundraising Club oplyste "
                f"{expected_rows} poster, men crawleren fandt {len(discovered_details)} unikke fondslinks."
            )
        if result.pages_visited == 0:
            raise ScrapeError("Ingen Fundraising Club-sider blev hentet; kørslen markeres ikke som aktuel.")
        if not result.records:
            raise ScrapeError(
                "Fundraising Club gav ingen genkendelige fondsposter; kontrollér abonnement, start-URL og sidelayout."
            )
        return result
