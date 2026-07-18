"""Forbered højst ti fondsspecifikke ansøgningspakker lokalt.

Modulet indsender aldrig noget og foretager ingen netværkskald.  En pakke er
først et kontrollerbart arbejdsprodukt: ``requirements.json``,
``application.md`` og ``approval.json``.  Approval-hashen binder krav og tekst
sammen, så en godkendelse ikke utilsigtet kan genbruges efter en ændring.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import unicodedata
from urllib.parse import urlparse

try:  # Virker både som top-level modul og som namespace-package.
    from .matching import (
        ProjectValidationError,
        get_fund_record,
        match_funds,
        validate_project,
    )
except ImportError:  # pragma: no cover - dækkes af CLI-importformen
    from matching import (  # type: ignore
        ProjectValidationError,
        get_fund_record,
        match_funds,
        validate_project,
    )


MAX_BATCH_SIZE = 10
DEFAULT_SOURCE_MAX_AGE_DAYS = 30
REQUIRED_RESEARCH_CRITERIA = (
    "applicant_eligibility",
    "purpose_and_target_group",
    "eligible_and_excluded_costs",
    "deadline_and_project_period",
    "attachments_and_formalia",
)

_PLACEHOLDER_PATTERNS = (
    re.compile(r"\{\{[^{}]+\}\}"),
    re.compile(r"\$\{[^{}]+\}"),
    re.compile(r"\[\[(?:[^\[\]])+\]\]"),
    re.compile(r"\[(?:UDFYLD|INDSÆT|TODO)(?::[^\]]*)?\]", re.IGNORECASE),
    re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b", re.IGNORECASE),
    re.compile(r"_{4,}"),
)


class BatchPreparationError(ValueError):
    """En sikker, handlingsrettet fejl ved batchforberedelse."""

    def __init__(self, message: str, *, errors: Sequence[Mapping[str, Any]] | None = None) -> None:
        self.errors = [dict(error) for error in (errors or [])]
        super().__init__(message)


def _first(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, "", [], {}):
            return mapping[key]
    return default


def _extra(fund: Mapping[str, Any]) -> Mapping[str, Any]:
    value = fund.get("extra", {})
    return value if isinstance(value, Mapping) else {}


def _fund_value(fund: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    value = _first(fund, *keys, default=None)
    return value if value is not None else _first(_extra(fund), *keys, default=default)


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, Mapping):
        value = _first(value, "date", "deadline", "value", "next", "at", default=None)
        if value is None:
            return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    for pattern in ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _as_of(value: date | datetime | str | None) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    parsed = _parse_date(value)
    if parsed is None:
        raise ValueError("as_of skal være en ISO-dato eller date/datetime")
    return parsed


def _slug(value: Any, fallback: str = "fond") -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").casefold()
    return slug[:80] or fallback


def _json_text(value: Any) -> str:
    return json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        _json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _stringify(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, Mapping):
        return "; ".join(f"{key}: {_stringify(item)}" for key, item in value.items() if item not in (None, "", [], {}))
    if isinstance(value, (list, tuple, set)):
        return "; ".join(filter(None, (_stringify(item) for item in value)))
    return str(value).strip()


def _format_dkk(value: float | int | None) -> str:
    if value is None:
        return "0"
    rounded = round(float(value))
    return f"{rounded:,}".replace(",", ".")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _valid_https_url(value: Any) -> bool:
    parsed = urlparse(str(value or "").strip())
    return bool(
        parsed.scheme.casefold() == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
    )


def _parse_display_amount(value: str) -> float | None:
    token = value.replace("\u00a0", "").replace(" ", "").strip()
    if not token:
        return None
    if "," in token:
        token = token.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", token):
        token = token.replace(".", "")
    try:
        amount = float(token)
    except ValueError:
        return None
    return amount if math.isfinite(amount) else None


def _application_requested_amounts(application: str) -> list[float]:
    pattern = re.compile(
        r"(?:der\s+søges|vi\s+søger|ansøgt\s+beløb|ansøgningsbeløb)\s*(?:om\s+)?[:=]?\s*"
        r"(?P<amount>\d[\d .]*(?:,\d{1,2})?)\s*(?:kr\.?|dkk)\b",
        re.IGNORECASE,
    )
    result: list[float] = []
    for match in pattern.finditer(application):
        amount = _parse_display_amount(match.group("amount"))
        if amount is not None:
            result.append(amount)
    return result


def _source_info(fund: Mapping[str, Any]) -> dict[str, Any]:
    explicit = _fund_value(fund, "official_source", default={})
    if not isinstance(explicit, Mapping):
        explicit = {}
    url = _first(
        explicit,
        "url",
        "source_url",
        default=_fund_value(fund, "official_url", "url", "website", default=""),
    )
    checked_at = _first(
        explicit,
        "checked_at",
        "last_checked",
        default=_fund_value(fund, "last_checked", "last_verified_at", "checked_at", default=None),
    )
    official = explicit.get("official", explicit.get("is_official", True))
    return {
        "url": str(url or "").strip(),
        "checked_at": _parse_date(checked_at),
        "official": bool(official),
        "verification_status": str(_fund_value(fund, "verification_status", default="")).casefold().strip(),
    }


def validate_official_source(
    fund: Mapping[str, Any],
    *,
    as_of: date | datetime | str | None = None,
    max_age_days: int = DEFAULT_SOURCE_MAX_AGE_DAYS,
) -> dict[str, Any]:
    """Kontrollér at fondsposten har en frisk, officiel HTTP(S)-kilde."""

    if isinstance(max_age_days, bool) or max_age_days < 0:
        raise ValueError("max_age_days skal være et ikke-negativt heltal")
    reference_date = _as_of(as_of)
    source = _source_info(fund)
    errors: list[dict[str, str]] = []
    if not _valid_https_url(source["url"]):
        errors.append(
            {
                "code": "missing_official_source",
                "message": "Der mangler en officiel HTTPS-kilde uden indlejrede credentials",
            }
        )
    if not source["official"]:
        errors.append({"code": "source_not_official", "message": "Kilden er markeret som ikke-officiel"})
    if source["verification_status"] != "verified":
        errors.append(
            {
                "code": "fund_not_verified",
                "message": "Fondsposten skal have verification_status='verified' før ansøgningskladde",
            }
        )
    checked_at = source["checked_at"]
    age_days: int | None = None
    if checked_at is None:
        errors.append({"code": "missing_checked_at", "message": "Den officielle kilde mangler kontroldato"})
    else:
        age_days = (reference_date - checked_at).days
        if age_days < 0:
            errors.append({"code": "checked_at_in_future", "message": "Kildens kontroldato ligger i fremtiden"})
        elif age_days > max_age_days:
            errors.append(
                {
                    "code": "stale_official_source",
                    "message": f"Kilden er {age_days} dage gammel; maksimum er {max_age_days}",
                }
            )
    return {
        "valid": not errors,
        "errors": errors,
        "url": source["url"],
        "checked_at": checked_at.isoformat() if checked_at else None,
        "age_days": age_days,
        "max_age_days": max_age_days,
    }


def find_placeholders(value: Any) -> list[str]:
    """Returnér stabile, deduplikerede placeholder-træffere i tekst/JSON."""

    text = (
        value
        if isinstance(value, str)
        else json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True)
    )
    matches: list[str] = []
    for pattern in _PLACEHOLDER_PATTERNS:
        matches.extend(match.group(0) for match in pattern.finditer(text))
    return list(dict.fromkeys(matches))


def contains_placeholders(value: Any) -> bool:
    return bool(find_placeholders(value))


def validate_requirement_research(
    requirements: Mapping[str, Any],
    *,
    allow_no_go: bool = False,
    as_of: date | datetime | str | None = None,
) -> dict[str, Any]:
    """Reject index summaries posing as a completed official-source review."""

    errors: list[dict[str, str]] = []

    def error(code: str, message: str) -> None:
        errors.append({"code": code, "message": message})

    if not isinstance(requirements, Mapping):
        return {
            "valid": False,
            "errors": [{"code": "requirements_not_structured", "message": "Fondskrav skal være et struktureret objekt"}],
        }
    placeholders = find_placeholders(requirements)
    if placeholders:
        error("research_placeholders", "Kravresearch indeholder placeholders: " + ", ".join(placeholders))

    go_no_go = str(requirements.get("go_no_go", "")).casefold().strip()
    lifecycle = str(requirements.get("status", "open")).casefold().strip()
    no_go_mode = allow_no_go and (
        go_no_go in {"no_go", "no-go", "no go"}
        or lifecycle in {"closed", "lukket", "inactive", "inaktiv"}
    )
    official_url = str(requirements.get("official_source_url", "")).strip()
    application_url = str(requirements.get("application_url", "")).strip()
    urls_to_validate = [
        ("missing_research_official_url", "officiel programside", official_url)
    ]
    if not no_go_mode:
        urls_to_validate.append(
            ("missing_application_url", "ansøgningsside eller officiel indsendelsesvejledning", application_url)
        )
    for code, label, value in urls_to_validate:
        if not _valid_https_url(value):
            error(code, f"Kravresearch mangler en gyldig HTTPS-URL uden credentials til {label}")
    reference_date = _as_of(as_of)
    research_checked_at = _parse_date(requirements.get("checked_at"))
    if research_checked_at is None:
        error("missing_research_checked_at", "Kravresearch mangler en gyldig checked_at-dato")
    elif research_checked_at > reference_date:
        error("research_checked_at_in_future", "Kravresearchens checked_at-dato ligger i fremtiden")
    if not no_go_mode and not str(requirements.get("project_id", "")).strip():
        error("research_project_id_missing", "Kravresearch mangler project_id")
    if go_no_go != "go" and not no_go_mode:
        error("research_not_go", "Kravresearch skal have en eksplicit go-beslutning")

    deadline = requirements.get("deadline")
    if not no_go_mode:
        if not isinstance(deadline, Mapping):
            error("research_deadline_missing", "Frist eller eksplicit løbende ansøgning er ikke dokumenteret")
        else:
            rolling = deadline.get("rolling") is True
            deadline_value = deadline.get("value")
            parsed_deadline = _parse_date(deadline_value)
            if not rolling and parsed_deadline is None:
                error("research_deadline_invalid", "En ikke-løbende frist skal være en gyldig dato")
            elif parsed_deadline is not None and parsed_deadline < reference_date:
                error("research_deadline_passed", "Den dokumenterede ansøgningsfrist er passeret")
            if not isinstance(deadline.get("project_may_start_before_decision"), bool):
                error(
                    "project_start_rule_missing",
                    "Kravresearch skal eksplicit angive om projektet må starte før afgørelse",
                )
    amount = requirements.get("amount")
    requested_amount = (
        _first(amount, "requested_dkk", "requested", default=None)
        if isinstance(amount, Mapping)
        else None
    )
    requested_number = _number(requested_amount)
    if not no_go_mode:
        if requested_number is None or requested_number <= 0:
            error("research_requested_amount_missing", "Det fondsspecifikke ansøgningsbeløb skal være større end 0")
        if not isinstance(amount, Mapping):
            error("research_amount_invalid", "Beløbskrav skal være et struktureret objekt")
        else:
            minimum_raw = _first(amount, "minimum_dkk", "min", "minimum", default=None)
            maximum_raw = _first(amount, "maximum_dkk", "max", "maximum", default=None)
            minimum = _number(minimum_raw)
            maximum = _number(maximum_raw)
            if minimum_raw not in (None, "") and (minimum is None or minimum < 0):
                error("research_minimum_invalid", "Fondens minimumsbeløb skal være et ikke-negativt tal eller null")
            if maximum_raw not in (None, "") and (maximum is None or maximum <= 0):
                error("research_maximum_invalid", "Fondens maksimumsbeløb skal være et positivt tal eller null")
            if minimum is not None and maximum is not None and minimum > maximum:
                error("research_amount_bounds_invalid", "Fondens minimumsbeløb overstiger maksimumsbeløbet")
            if requested_number is not None and minimum is not None and requested_number < minimum:
                error("research_requested_below_minimum", "Ansøgningsbeløbet er under fondens dokumenterede minimum")
            if requested_number is not None and maximum is not None and requested_number > maximum:
                error("research_requested_above_maximum", "Ansøgningsbeløbet overstiger fondens dokumenterede maksimum")
            if not isinstance(amount.get("cofinancing_required"), bool):
                error("cofinancing_rule_missing", "Kravresearch skal eksplicit angive krav om medfinansiering")

    criteria = requirements.get("criteria")
    by_category: dict[str, Mapping[str, Any]] = {}
    if isinstance(criteria, list):
        by_category = {
            str(item.get("category", "")).strip(): item
            for item in criteria
            if isinstance(item, Mapping) and str(item.get("category", "")).strip()
        }
    for category in (() if no_go_mode else REQUIRED_RESEARCH_CRITERIA):
        item = by_category.get(category)
        if item is None:
            error("research_criterion_missing", f"Kravresearch mangler kriteriet {category}")
            continue
        if not str(item.get("requirement", "")).strip():
            error("research_requirement_missing", f"Kriteriet {category} mangler konkret fondskrav")
        if not str(item.get("project_response", "")).strip():
            error("research_project_response_missing", f"Kriteriet {category} mangler projektets konkrete svar")
        evidence_url = str(item.get("source_url", "")).strip()
        if not _valid_https_url(evidence_url):
            error("research_evidence_url_missing", f"Kriteriet {category} mangler evidens-URL")
        if not str(item.get("evidence_note", "")).strip():
            error("research_evidence_note_missing", f"Kriteriet {category} mangler evidensnote")
        if item.get("satisfied") is not True:
            error("research_criterion_not_satisfied", f"Kriteriet {category} er ikke eksplicit opfyldt")

    documents = requirements.get("source_documents")
    document_kinds: set[str] = set()
    if isinstance(documents, list):
        for index, item in enumerate(documents, start=1):
            if not isinstance(item, Mapping):
                error("research_source_not_structured", f"Kildedokument {index} skal være et struktureret objekt")
                continue
            kind = str(item.get("kind", "")).strip()
            document_url = str(item.get("url", "")).strip()
            document_checked_at = _parse_date(item.get("checked_at"))
            document_valid = True
            if not _valid_https_url(document_url):
                error("research_source_url_invalid", f"Kildedokument {index} mangler en gyldig HTTPS-URL")
                document_valid = False
            if document_checked_at is None:
                error("research_source_checked_at_missing", f"Kildedokument {index} mangler en gyldig checked_at-dato")
                document_valid = False
            elif document_checked_at > reference_date:
                error("research_source_checked_at_in_future", f"Kildedokument {index} har checked_at i fremtiden")
                document_valid = False
            if kind and document_valid:
                document_kinds.add(kind)
    for kind in (("program_page",) if no_go_mode else ("program_page", "application_process")):
        if kind not in document_kinds:
            error("research_source_missing", f"Kildelisten mangler {kind}")
    if not no_go_mode and requirements.get("portal_fields_reviewed") is not True:
        error("portal_fields_not_reviewed", "Portalfelter/indsendelsesfelter er ikke eksplicit gennemgået")
    if not no_go_mode and requirements.get("attachments_reviewed") is not True:
        error("attachments_not_reviewed", "Bilagskrav er ikke eksplicit gennemgået")
    portal_fields = requirements.get("portal_fields")
    if not no_go_mode and not isinstance(portal_fields, list):
        error("portal_fields_invalid", "portal_fields skal være en liste, også når den er tom")
    elif not no_go_mode and isinstance(portal_fields, list):
        for index, field in enumerate(portal_fields, start=1):
            if not isinstance(field, Mapping):
                error("portal_field_not_structured", f"Portalfelt {index} skal være et struktureret objekt")
                continue
            if not str(_first(field, "field", "name", "label", default="")).strip():
                error("portal_field_name_missing", f"Portalfelt {index} mangler feltnavn")
            project_response = str(_first(field, "project_response", "response", default="")).strip()
            if not project_response:
                error("portal_field_response_missing", f"Portalfelt {index} mangler projektets konkrete svar")
            if "character_limit" not in field:
                error(
                    "portal_field_limit_missing",
                    f"Portalfelt {index} skal angive character_limit som positivt heltal eller null",
                )
            elif field.get("character_limit") is not None and (
                isinstance(field.get("character_limit"), bool)
                or not isinstance(field.get("character_limit"), int)
                or int(field["character_limit"]) <= 0
            ):
                error("portal_field_limit_invalid", f"Portalfelt {index} har ugyldig character_limit")
            elif field.get("character_limit") is not None and len(project_response) > int(field["character_limit"]):
                error(
                    "portal_field_response_too_long",
                    f"Portalfelt {index} er {len(project_response)} tegn, men grænsen er {field['character_limit']}",
                )
    if not no_go_mode and not isinstance(requirements.get("attachments"), list):
        error("attachments_invalid", "attachments skal være en liste, også når den er tom")
    if no_go_mode and not (
        requirements.get("hard_blockers")
        or str(requirements.get("go_no_go_reason", "")).strip()
    ):
        error("no_go_reason_missing", "Lukket/no-go research mangler blocker eller begrundelse")
    return {"valid": not errors, "errors": errors}


def fund_research_fingerprint(fund: Mapping[str, Any]) -> str:
    """Fingerprint every indexed field that can change eligibility or wording."""

    payload = {
        "official_source": _source_info(fund),
        "geography": _fund_value(fund, "geography", "area", default=[]),
        "applicant_types": _fund_value(fund, "applicant_types", default=[]),
        "purposes": _fund_value(fund, "purposes", default=[]),
        "target_groups": _fund_value(fund, "target_groups", default=[]),
        "amount": _fund_value(fund, "amount", default={}),
        "deadline": _fund_value(fund, "deadline", default={}),
        "requirements": _requirement_mapping(fund),
        "exclusions": _fund_value(fund, "exclusions", default=[]),
    }
    return "sha256:" + hashlib.sha256(_canonical_json(payload)).hexdigest()


def project_snapshot_fingerprint(project: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(project)).hexdigest()


def calculate_approval_hash(
    requirements: Mapping[str, Any],
    application: str,
    submission: Mapping[str, Any] | None = None,
) -> str:
    """Hash det præcise indhold, som en intern godkender tager stilling til."""

    digest = hashlib.sha256()
    digest.update(b"requirements.json\0")
    digest.update(_canonical_json(requirements))
    digest.update(b"\0application.md\0")
    digest.update(application.replace("\r\n", "\n").encode("utf-8"))
    if submission is not None:
        digest.update(b"\0submission\0")
        digest.update(_canonical_json(submission))
    return "sha256:" + digest.hexdigest()


def verify_approval_hash(
    requirements: Mapping[str, Any],
    application: str,
    approval: Mapping[str, Any],
) -> bool:
    submission = approval.get("submission")
    if not isinstance(submission, Mapping):
        submission = None
    expected = calculate_approval_hash(requirements, application, submission)
    return expected == approval.get("approval_hash")


def _template_context(
    project: Mapping[str, Any],
    fund: Mapping[str, Any],
    match: Mapping[str, Any],
    source: Mapping[str, Any],
) -> dict[str, str]:
    fund_id = _first(fund, "fund_id", "id", "canonical_key", default="")
    context = {
        "FUND_ID": str(fund_id),
        "FUND_NAME": str(_first(fund, "name", "fund_name", default=fund_id)),
        "PROJECT_ID": str(project["project_id"]),
        "PROJECT_TITLE": str(project["title"]),
        "REQUESTED_AMOUNT_DKK": _format_dkk(project["requested_amount"]),
        "OFFICIAL_URL": str(source["url"]),
        "CHECKED_AT": str(source["checked_at"]),
        "MATCH_SCORE": str(match["score"]),
    }
    context.update({key.casefold(): value for key, value in list(context.items())})
    return context


def _replace_tokens(value: Any, context: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        rendered = value
        for key, replacement in context.items():
            rendered = rendered.replace("{{" + key + "}}", replacement)
            rendered = rendered.replace("{" + key + "}", replacement)
        return rendered
    if isinstance(value, list):
        return [_replace_tokens(item, context) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _replace_tokens(item, context) for key, item in value.items()}
    return value


def _load_application_template(
    template: str | Path | Callable[[Mapping[str, Any]], str] | None,
    template_dir: str | Path | None,
) -> str | Callable[[Mapping[str, Any]], str] | None:
    if callable(template):
        return template
    if isinstance(template, Path):
        return template.read_text(encoding="utf-8")
    if isinstance(template, str):
        return template
    directory = Path(template_dir) if template_dir is not None else Path(__file__).resolve().parent.parent / "assets"
    path = directory / "application.template.md"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _load_requirements_template(
    template: Mapping[str, Any] | str | Path | Callable[[Mapping[str, Any]], Mapping[str, Any]] | None,
    template_dir: str | Path | None,
) -> Mapping[str, Any] | Callable[[Mapping[str, Any]], Mapping[str, Any]] | None:
    if callable(template) or isinstance(template, Mapping):
        return template
    if isinstance(template, Path):
        return json.loads(template.read_text(encoding="utf-8"))
    if isinstance(template, str):
        return json.loads(template)
    directory = Path(template_dir) if template_dir is not None else Path(__file__).resolve().parent.parent / "assets"
    path = directory / "fund-requirements.template.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _requirement_mapping(fund: Mapping[str, Any]) -> Mapping[str, Any]:
    value = fund.get("requirements", {})
    result: dict[str, Any] = dict(value) if isinstance(value, Mapping) else {}
    if value and not isinstance(value, Mapping):
        result["description"] = _stringify(value)
    extra = _extra(fund)
    # Research-workflowet gemmer den fulde, strukturerede læsning i extra,
    # mens topniveauet bevarer et søgbart resumeret felt.
    for key in ("requirements_data", "requirements"):
        detailed = extra.get(key, {})
        if isinstance(detailed, Mapping):
            result.update(deepcopy(dict(detailed)))
    return result


def _amount_bounds(fund: Mapping[str, Any]) -> tuple[Any, Any]:
    raw = _fund_value(fund, "amount", default={})
    if isinstance(raw, Mapping):
        return (
            _first(raw, "min", "minimum", "from", default=None),
            _first(raw, "max", "maximum", "to", default=None),
        )
    return None, raw or None


def _deadline_payload(fund: Mapping[str, Any]) -> tuple[str, bool]:
    raw = _fund_value(fund, "deadline", default="")
    raw_text = _stringify(raw)
    rolling = any(term in raw_text.casefold() for term in ("løbende", "lobende", "rolling", "ingen frist"))
    parsed = _parse_date(raw)
    return (parsed.isoformat() if parsed else raw_text), rolling


def _criterion_values(
    category: str,
    project: Mapping[str, Any],
    fund: Mapping[str, Any],
    source_url: str,
) -> dict[str, Any]:
    requirements = _requirement_mapping(fund)
    category_key = category.casefold()
    source_criterion = next(
        (
            item
            for item in requirements.get("criteria", [])
            if isinstance(item, Mapping) and str(item.get("category", "")).casefold() == category_key
        ),
        {},
    )
    if category_key == "applicant_eligibility":
        requirement = _stringify(_fund_value(fund, "applicant_types", default=[])) or _stringify(
            requirements.get("applicant_eligibility")
        )
        response = f"{project['applicant']['name']} er {project['applicant']['type']} (CVR {project['applicant']['cvr']})."
    elif category_key == "purpose_and_target_group":
        requirement = _stringify(_fund_value(fund, "purposes", default=[])) or _stringify(
            requirements.get("purpose")
        )
        response = (
            f"Projektets formål er {_stringify(project['purposes'])}. "
            f"Målgruppen er {_stringify(project['target_groups'])}."
        )
    elif category_key == "eligible_and_excluded_costs":
        requirement = _stringify(
            _first(
                requirements,
                "eligible_expenses",
                "supported_expenses",
                default=_fund_value(fund, "exclusions", default=[]),
            )
        )
        response = f"Der søges til disse udgiftskategorier: {_stringify(project['expenses'])}."
    elif category_key == "deadline_and_project_period":
        deadline, rolling = _deadline_payload(fund)
        requirement = f"Ansøgningsfrist: {deadline or 'løbende' if rolling else deadline}."
        response = f"Projektperioden er {project['start_date'].isoformat()} til {project['end_date'].isoformat()}."
    else:
        requirement = _stringify(requirements) or "De offentliggjorte formalia på fondens officielle side"
        attachments = project.get("documentation") or []
        response = (
            "Tilgængelige bilag: " + _stringify(attachments)
            if attachments
            else "Bilag kontrolleres mod portalens aktuelle felter før intern godkendelse."
        )
    researched_requirement = str(source_criterion.get("requirement", "")).strip()
    return {
        "category": category,
        "requirement": researched_requirement or requirement,
        "project_response": response,
        "satisfied": source_criterion.get("satisfied") is True,
        "source_url": str(source_criterion.get("source_url") or source_url),
        "evidence_note": str(source_criterion.get("evidence_note") or ""),
    }


def _render_requirements(
    template: Mapping[str, Any] | Callable[[Mapping[str, Any]], Mapping[str, Any]] | None,
    context: Mapping[str, str],
    project: Mapping[str, Any],
    fund: Mapping[str, Any],
    match: Mapping[str, Any],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    render_context: dict[str, Any] = {
        **context,
        "project": project,
        "fund": fund,
        "match": match,
        "source": source,
    }
    if callable(template):
        raw = template(render_context)
        if not isinstance(raw, Mapping):
            raise BatchPreparationError("requirements_template-callable skal returnere et objekt")
        payload = deepcopy(dict(raw))
    elif isinstance(template, Mapping):
        payload = deepcopy(dict(template))
    else:
        payload = {}
    payload = dict(_replace_tokens(payload, context))

    requirements = _requirement_mapping(fund)
    research_deadline = requirements.get("deadline", {})
    if isinstance(research_deadline, Mapping):
        deadline = str(research_deadline.get("value", "")).strip()
        rolling = research_deadline.get("rolling") is True
        project_may_start = research_deadline.get("project_may_start_before_decision")
    else:
        deadline, rolling = _deadline_payload(fund)
        project_may_start = requirements.get("project_may_start_before_decision")
    research_amount = requirements.get("amount", {})
    if isinstance(research_amount, Mapping):
        minimum = _first(research_amount, "minimum_dkk", "min", "minimum", default=None)
        maximum = _first(research_amount, "maximum_dkk", "max", "maximum", default=None)
        cofinancing_required = research_amount.get("cofinancing_required")
        requested_dkk = _first(
            research_amount,
            "requested_dkk",
            "requested",
            default=project["requested_amount"],
        )
    else:
        minimum, maximum = _amount_bounds(fund)
        cofinancing_required = requirements.get("cofinancing_required")
        requested_dkk = project["requested_amount"]
    payload.update(
        {
            "schema_version": 1,
            "fund_id": context["FUND_ID"],
            "fund_name": context["FUND_NAME"],
            "project_id": context["PROJECT_ID"],
            "official_source_url": source["url"],
            "application_url": str(
                _first(requirements, "application_url", "portal_url", default=source["url"])
            ),
            "checked_at": source["checked_at"],
            "go_no_go": "go",
            "go_no_go_reason": f"Ingen hårde stop; deterministisk matchscore {match['score']}/100.",
            "hard_blockers": list(match["hard_blockers"]),
            "deadline": {
                "value": deadline,
                "timezone": "Europe/Copenhagen",
                "rolling": rolling,
                "project_may_start_before_decision": project_may_start,
            },
            "amount": {
                "requested_dkk": round(float(requested_dkk)),
                "minimum_dkk": minimum,
                "maximum_dkk": maximum,
                "cofinancing_required": cofinancing_required,
                "project_financing": {
                    "total_budget_dkk": round(float(project["total_budget"])),
                    "this_fund_requested_dkk": round(float(requested_dkk)),
                    "own_financing_dkk": round(float(project["own_financing"])),
                    "other_confirmed_dkk": round(float(project["other_confirmed_financing"])),
                    "other_pending_dkk": round(float(project["other_pending_financing"])),
                    "remaining_financing_to_secure_dkk": round(
                        float(project["total_budget"])
                        - float(requested_dkk)
                        - float(project["own_financing"])
                        - float(project["other_confirmed_financing"])
                        - float(project["other_pending_financing"])
                    ),
                },
            },
            "indexed_requirements": deepcopy(requirements),
            "exclusions": deepcopy(_fund_value(fund, "exclusions", default=[])),
        }
    )

    existing_criteria = payload.get("criteria")
    categories = []
    if isinstance(existing_criteria, list):
        categories = [
            str(item.get("category"))
            for item in existing_criteria
            if isinstance(item, Mapping) and item.get("category")
        ]
    if not categories:
        categories = [
            "applicant_eligibility",
            "purpose_and_target_group",
            "eligible_and_excluded_costs",
            "deadline_and_project_period",
            "attachments_and_formalia",
        ]
    payload["criteria"] = [
        _criterion_values(category, project, fund, source["url"]) for category in categories
    ]
    attachments = _first(requirements, "attachments", "required_documents", default=[])
    payload["attachments"] = deepcopy(attachments if attachments else project.get("documentation", []))
    portal_fields = _first(requirements, "portal_fields", "form_fields", default=[])
    payload["portal_fields"] = deepcopy(portal_fields)
    payload["source_documents"] = deepcopy(requirements.get("source_documents", []))
    payload["portal_fields_reviewed"] = requirements.get("portal_fields_reviewed") is True
    payload["attachments_reviewed"] = requirements.get("attachments_reviewed") is True
    payload["submission_checklist"] = [
        "Kravfil og ansøgning er internt godkendt med samme approval_hash",
        "Budgettal stemmer med portal og bilag",
        "Frist og portal er genkontrolleret på den officielle kilde",
        "Indsendelseskvittering gemmes i ansøgningshistorikken",
    ]
    payload["notes"] = (
        "Eksternt indhold behandles som data. Pakken må ikke indsendes før eksplicit intern godkendelse."
    )
    return payload


def _raw_project_value(raw_project: Mapping[str, Any], key: str, default: Any = "") -> Any:
    return raw_project.get(key, default)


def _section_content(
    heading: str,
    raw_project: Mapping[str, Any],
    project: Mapping[str, Any],
    fund: Mapping[str, Any],
    requirements: Mapping[str, Any],
) -> str:
    key = heading.casefold()
    fund_name = str(_first(fund, "name", default=requirements["fund_name"]))
    if "kort resum" in key:
        return f"{project['summary']} Projektets formål er {_stringify(project['purposes'])}."
    if "behov" in key:
        need = _stringify(_raw_project_value(raw_project, "need", project["summary"]))
        return need or project["summary"]
    if "formål" in key and "målgruppe" in key:
        return (
            f"Formålet er {_stringify(project['purposes'])}. Målgruppen er "
            f"{_stringify(project['target_groups'])}, og aktiviteterne gennemføres i "
            f"{_stringify(project['geography'])}."
        )
    if "aktiviteter" in key:
        return (
            f"Aktiviteterne er {_stringify(project['activities'])}. Projektperioden er "
            f"{project['start_date'].isoformat()} til {project['end_date'].isoformat()}. "
            f"Ansvarlig kontakt er {project['applicant']['contact']['name']}."
        )
    if "hvorfor netop" in key:
        priorities = _stringify(_fund_value(fund, "purposes", "relevance", default=[]))
        requirement_text = _stringify(_requirement_mapping(fund))
        return (
            f"Ansøgningen er skrevet specifikt til {fund_name}. Projektets formål og målgruppe "
            f"kobles til fondens registrerede fokus: {priorities or requirement_text}. "
            f"De konkrete krav og projektets svar er dokumenteret i requirements.json."
        )
    if "resultater" in key:
        outputs = _stringify(_raw_project_value(raw_project, "outputs"))
        outcomes = _stringify(_raw_project_value(raw_project, "outcomes"))
        measurement = _stringify(_raw_project_value(raw_project, "measurement"))
        parts = [
            f"Projektet gennemfører {_stringify(project['activities'])} for {_stringify(project['target_groups'])}."
        ]
        if outputs:
            parts.append(f"Leverancer: {outputs}.")
        if outcomes:
            parts.append(f"Forventet virkning: {outcomes}.")
        if measurement:
            parts.append(f"Måling: {measurement}.")
        return " ".join(parts)
    if "forankring" in key:
        operation = _stringify(_raw_project_value(raw_project, "continued_operation"))
        volunteers = _stringify(_raw_project_value(raw_project, "volunteer_involvement"))
        return operation or volunteers or (
            f"{project['applicant']['name']} har ansvar for projektets forankring og fortsatte drift."
        )
    if "budget" in key:
        requested = _first(requirements.get("amount", {}), "requested_dkk", default=project["requested_amount"])
        financing = requirements.get("amount", {}).get("project_financing", {})
        remaining = _number(financing.get("remaining_financing_to_secure_dkk")) if isinstance(financing, Mapping) else None
        remaining_text = (
            f" Den resterende finansiering, der skal sikres, er {_format_dkk(remaining)} kr."
            if remaining is not None and remaining > 0
            else ""
        )
        return (
            f"Det samlede projektbudget er {_format_dkk(project['total_budget'])} kr. Der søges "
            f"{_format_dkk(requested)} kr. hos {fund_name}. Egenfinansieringen er "
            f"{_format_dkk(project['own_financing'])} kr. Midlerne anvendes til "
            f"{_stringify(project['expenses'])}.{remaining_text}"
        )
    if "portalens" in key:
        portal_fields = requirements.get("portal_fields") or []
        return (
            _stringify(portal_fields)
            if portal_fields
            else "Portalens aktuelle felter fremgår af den kontrollerede officielle kilde og besvares med oplysningerne i denne ansøgning."
        )
    if "bilag" in key:
        attachments = requirements.get("attachments") or project.get("documentation") or []
        return (
            f"Bilag: {_stringify(attachments)}. Ansøgning sker via {requirements['application_url']} "
            f"efter intern godkendelse; fristen er {_stringify(requirements['deadline'])}."
        )
    return f"Dette afsnit er udfyldt specifikt for {fund_name} på baggrund af requirements.json."


def _fill_markdown_scaffold(
    template: str,
    raw_project: Mapping[str, Any],
    project: Mapping[str, Any],
    fund: Mapping[str, Any],
    requirements: Mapping[str, Any],
) -> str:
    current_heading = ""
    result: list[str] = []
    for line in template.splitlines():
        if line.startswith("## "):
            current_heading = line[3:].strip()
            result.append(line)
            continue
        if re.fullmatch(r"\s*\[(?:UDFYLD|INDSÆT|TODO)(?::[^\]]*)?\]\s*", line, re.IGNORECASE):
            result.append(_section_content(current_heading, raw_project, project, fund, requirements))
        else:
            result.append(line)
    return "\n".join(result).rstrip() + "\n"


def _embedded_application(
    raw_project: Mapping[str, Any],
    project: Mapping[str, Any],
    fund: Mapping[str, Any],
    requirements: Mapping[str, Any],
) -> str:
    fund_name = requirements["fund_name"]
    headings = [
        "Kort resumé",
        "Behov og dokumentation",
        "Formål, målgruppe og geografi",
        "Aktiviteter, tidsplan og ansvar",
        "Hvorfor netop denne fond",
        "Resultater, virkning og måling",
        "Forankring og fortsat drift",
        "Budget og finansieringsplan",
        "Portalens spørgsmål og svar",
        "Bilag og indsendelse",
    ]
    lines = [
        f"# {project['title']} — ansøgning til {fund_name}",
        "",
        f"Ansøger: {project['applicant']['name']} (CVR {project['applicant']['cvr']})",
        f"Officiel kilde: {requirements['official_source_url']}",
        f"Krav kontrolleret: {requirements['checked_at']}",
        "Status: UDKAST — MÅ IKKE INDSENDES FØR INTERN GODKENDELSE",
        "",
    ]
    for heading in headings:
        lines.extend(
            [
                f"## {heading}",
                "",
                _section_content(heading, raw_project, project, fund, requirements),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _render_application(
    template: str | Callable[[Mapping[str, Any]], str] | None,
    context: Mapping[str, str],
    raw_project: Mapping[str, Any],
    project: Mapping[str, Any],
    fund: Mapping[str, Any],
    match: Mapping[str, Any],
    requirements: Mapping[str, Any],
) -> str:
    if callable(template):
        application = template(
            {
                **context,
                "project": project,
                "raw_project": raw_project,
                "fund": fund,
                "match": match,
                "requirements": requirements,
            }
        )
        if not isinstance(application, str):
            raise BatchPreparationError("application_template-callable skal returnere tekst")
    elif isinstance(template, str):
        application = str(_replace_tokens(template, context))
        application = _fill_markdown_scaffold(application, raw_project, project, fund, requirements)
    else:
        application = _embedded_application(raw_project, project, fund, requirements)
    return application.replace("\r\n", "\n").rstrip() + "\n"


def validate_application_package(
    *,
    project: Mapping[str, Any],
    fund: Mapping[str, Any],
    match: Mapping[str, Any],
    requirements: Mapping[str, Any],
    application: str,
    as_of: date | datetime | str | None = None,
    source_max_age_days: int = DEFAULT_SOURCE_MAX_AGE_DAYS,
) -> dict[str, Any]:
    """Validér de stopkriterier der skal være sande før filskrivning."""

    errors: list[dict[str, str]] = []

    def error(code: str, message: str) -> None:
        errors.append({"code": code, "message": message})

    source_check = validate_official_source(fund, as_of=as_of, max_age_days=source_max_age_days)
    errors.extend(source_check["errors"])
    if match.get("go_no_go") != "go" or match.get("hard_blockers"):
        error("no_go", "Matchresultatet er no-go eller indeholder hårde stop")
    if requirements.get("go_no_go") != "go":
        error("requirements_not_go", "requirements.json skal have en eksplicit go-beslutning")
    rendered_research = validate_requirement_research(requirements, as_of=as_of)
    errors.extend(rendered_research["errors"])
    researched = _requirement_mapping(fund)
    if not researched:
        error("missing_fund_requirements", "Fondens aktuelle krav er ikke registreret")
    else:
        errors.extend(validate_requirement_research(researched, as_of=as_of)["errors"])
    deadline_value, rolling = _deadline_payload(fund)
    if not deadline_value and not rolling:
        error("unverified_deadline", "Frist eller eksplicit løbende ansøgning skal være registreret")

    amount = requirements.get("amount")
    requested = _number(_first(amount, "requested_dkk", default=None)) if isinstance(amount, Mapping) else None
    project_total = _number(project.get("total_budget"))
    project_grant_need = _number(project.get("requested_amount"))
    if requested is None or requested <= 0:
        error("package_requested_amount_invalid", "Pakkens ansøgningsbeløb skal være et positivt tal")
    else:
        if project_total is not None and requested > project_total + 1:
            error("package_amount_exceeds_budget", "Ansøgningsbeløbet overstiger projektets totalbudget")
        if project_grant_need is not None and requested > project_grant_need + 1:
            error(
                "package_amount_exceeds_financing_need",
                "Ansøgningsbeløbet overstiger projektbriefets samlede finansieringsbehov fra fonde",
            )
    if isinstance(amount, Mapping):
        financing = amount.get("project_financing")
        if not isinstance(financing, Mapping):
            error("package_financing_plan_missing", "Pakken mangler en fondsspecifik finansieringsplan")
        elif requested is not None and project_total is not None:
            expected = {
                "total_budget_dkk": project_total,
                "this_fund_requested_dkk": requested,
                "own_financing_dkk": _number(project.get("own_financing")) or 0.0,
                "other_confirmed_dkk": _number(project.get("other_confirmed_financing")) or 0.0,
                "other_pending_dkk": _number(project.get("other_pending_financing")) or 0.0,
            }
            expected["remaining_financing_to_secure_dkk"] = (
                expected["total_budget_dkk"]
                - expected["this_fund_requested_dkk"]
                - expected["own_financing_dkk"]
                - expected["other_confirmed_dkk"]
                - expected["other_pending_dkk"]
            )
            for key, expected_value in expected.items():
                actual = _number(financing.get(key))
                if actual is None or abs(actual - expected_value) > 1:
                    error(
                        "package_financing_plan_mismatch",
                        f"Pakkens finansieringsfelt {key} stemmer ikke med projektbrief og ansøgningsbeløb",
                    )
            if expected["remaining_financing_to_secure_dkk"] < -1:
                error("package_financing_overfunded", "Pakkens finansieringsplan overstiger totalbudgettet")
    deadline_mapping = requirements.get("deadline")
    if isinstance(deadline_mapping, Mapping) and deadline_mapping.get("project_may_start_before_decision") is False:
        deadline_date = _parse_date(deadline_mapping.get("value"))
        project_start = _parse_date(project.get("start_date"))
        if deadline_date is not None and project_start is not None and project_start <= deadline_date:
            error(
                "project_starts_before_possible_decision",
                "Projektet starter senest ved ansøgningsfristen, selv om fonden ikke tillader start før afgørelse",
            )

    requirement_placeholders = find_placeholders(requirements)
    if requirement_placeholders:
        error(
            "requirements_placeholders",
            "Kravfilen indeholder placeholders: " + ", ".join(requirement_placeholders),
        )
    application_placeholders = find_placeholders(application)
    if application_placeholders:
        error(
            "application_placeholders",
            "Ansøgningen indeholder placeholders: " + ", ".join(application_placeholders),
        )
    fund_name = str(_first(fund, "name", "fund_name", default="")).strip()
    if fund_name.casefold() not in application.casefold():
        error("fund_name_missing", "Ansøgningen nævner ikke den valgte fond")
    if str(project["title"]).casefold() not in application.casefold():
        error("project_title_missing", "Ansøgningen nævner ikke projektets titel")
    application_amounts = _application_requested_amounts(application)
    if requested is not None:
        if not application_amounts:
            error(
                "application_requested_amount_missing",
                "Ansøgningsteksten skal angive det fondsspecifikke ansøgningsbeløb som 'Der søges ... kr.'",
            )
        elif any(abs(value - requested) > 1 for value in application_amounts):
            error(
                "application_requested_amount_mismatch",
                "Et ansøgningsbeløb i ansøgningsteksten stemmer ikke med requirements.json",
            )
    specific_markers = [
        source_check["url"],
        _stringify(_fund_value(fund, "purposes", default=[])),
        deadline_value,
        _stringify(_requirement_mapping(fund)),
    ]
    if not any(marker and marker.casefold() in application.casefold() for marker in specific_markers):
        error(
            "draft_not_fund_specific",
            "Ansøgningen mangler fondsspecifik kilde, frist, formål eller kravtekst",
        )
    if len(application.strip()) < 300:
        error("application_too_short", "Ansøgningen er for kort til en kontrollerbar, fondsspecifik kladde")
    return {
        "valid": not errors,
        "errors": errors,
        "checks": {
            "official_source_current": source_check["valid"],
            "go_no_go": match.get("go_no_go") == "go" and not match.get("hard_blockers"),
            "requirements_complete": (
                not requirement_placeholders
                and bool(researched)
                and validate_requirement_research(researched, as_of=as_of)["valid"]
                and rendered_research["valid"]
            ),
            "no_application_placeholders": not application_placeholders,
            "fund_specific": not any(item["code"] == "draft_not_fund_specific" for item in errors),
        },
        "source": source_check,
    }


def _submission_payload(
    project: Mapping[str, Any],
    fund: Mapping[str, Any],
    requirements: Mapping[str, Any],
    *,
    raw_project: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    fund_id = _first(fund, "fund_id", "id", "canonical_key", default=None)
    return {
        "status": "not_submitted",
        "network_action_performed": False,
        "project_id": project["project_id"],
        "fund_id": fund_id,
        "fund_name": requirements["fund_name"],
        "application_url": requirements["application_url"],
        "deadline": requirements["deadline"],
        "requested_amount_dkk": round(float(requirements["amount"]["requested_dkk"])),
        "project_snapshot_fingerprint": project_snapshot_fingerprint(
            {"raw": dict(raw_project or {}), "normalized": dict(project)}
        ),
        "attachments": deepcopy(requirements.get("attachments", [])),
        "portal_fields": deepcopy(requirements.get("portal_fields", [])),
        # Kan efter faktisk indsendelse kopieres til IndexStore.record_sent_application().
        "history_record_after_submission": {
            "fund_id": fund_id,
            "fund_name": requirements["fund_name"],
            "fund_url": requirements["official_source_url"],
            "project_id": project["project_id"],
            "project_name": project["title"],
            "amount_requested": round(float(requirements["amount"]["requested_dkk"])),
            "submitted_at": None,
            "status": None,
            "source_kind": "prepared_application_batch",
        },
    }


def _write_text(path: Path, content: str, *, overwrite: bool) -> None:
    if path.is_symlink():
        raise BatchPreparationError(f"Afviser at skrive gennem et symlink: {path}")
    if path.exists() and not overwrite:
        raise BatchPreparationError(f"Filen findes allerede; brug overwrite=True for at erstatte den: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        except FileExistsError as exc:
            raise BatchPreparationError(f"Filen findes allerede: {path}") from exc
    else:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="." + path.name + ".",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
    if os.name == "posix":
        os.chmod(path, 0o600)


def prepare_application_batch(
    store: Any,
    project: Mapping[str, Any],
    output_dir: str | Path,
    *,
    fund_ids: Sequence[Any] | None = None,
    limit: int = MAX_BATCH_SIZE,
    ready: bool = False,
    as_of: date | datetime | str | None = None,
    source_max_age_days: int = DEFAULT_SOURCE_MAX_AGE_DAYS,
    template_dir: str | Path | None = None,
    application_template: str | Path | Callable[[Mapping[str, Any]], str] | None = None,
    requirements_template: (
        Mapping[str, Any]
        | str
        | Path
        | Callable[[Mapping[str, Any]], Mapping[str, Any]]
        | None
    ) = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Forbered 1–10 lokale ansøgningspakker; foretag aldrig indsendelse.

    ``ready=True`` (eller ``project['ready_to_apply'] is True``) er et bevidst
    sikkerhedssignal fra brugeren. Ved automatisk udvælgelse springes no-go og
    ikke-aktuelle poster over. Ved eksplicitte ``fund_ids`` fejler hele batchen,
    hvis blot én valgt fond ikke er ansøgningsklar.
    """

    if not (ready or project.get("ready_to_apply") is True):
        raise BatchPreparationError(
            "Projektet er ikke markeret ansøgningsklart; angiv ready=True efter brugerens bekræftelse"
        )
    if isinstance(limit, bool) or not 1 <= int(limit) <= MAX_BATCH_SIZE:
        raise BatchPreparationError(f"En batch skal indeholde mellem 1 og {MAX_BATCH_SIZE} fonde")
    limit = int(limit)
    if fund_ids is not None:
        if not fund_ids:
            raise BatchPreparationError("fund_ids må ikke være tom")
        if len(fund_ids) > MAX_BATCH_SIZE:
            raise BatchPreparationError(f"Der kan højst udvælges {MAX_BATCH_SIZE} fonde pr. batch")
        if len({str(item) for item in fund_ids}) != len(fund_ids):
            raise BatchPreparationError("Den samme fond er valgt mere end én gang")

    try:
        project_report = validate_project(project, stage="application", as_of=as_of, raise_on_error=True)
    except ProjectValidationError as exc:
        raise BatchPreparationError("Projektbriefet er ikke ansøgningsklart", errors=exc.errors) from exc
    normalised = project_report["project"]
    reference_date = _as_of(as_of)

    if fund_ids is None:
        ranked = match_funds(store, normalised, as_of=reference_date, include_blocked=True)
    else:
        ranked_raw = match_funds(
            store,
            normalised,
            fund_ids=fund_ids,
            as_of=reference_date,
            include_blocked=True,
        )
        by_id = {str(item.get("fund_id")): item for item in ranked_raw}
        ranked = [by_id[str(fund_id)] for fund_id in fund_ids]

    selected: list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]] = []
    skipped: list[dict[str, Any]] = []
    explicit = fund_ids is not None
    for match in ranked:
        fund = get_fund_record(store, match["fund_id"])
        source_check = validate_official_source(
            fund, as_of=reference_date, max_age_days=source_max_age_days
        )
        preflight_errors = list(source_check["errors"])
        if match["go_no_go"] != "go":
            preflight_errors.extend(match.get("blocker_details", []))
        researched = _requirement_mapping(fund)
        if not researched:
            preflight_errors.append(
                {"code": "missing_fund_requirements", "message": "Aktuelle fondskrav mangler"}
            )
        else:
            preflight_errors.extend(
                validate_requirement_research(researched, as_of=reference_date)["errors"]
            )
            if str(researched.get("project_id", "")) != str(normalised["project_id"]):
                preflight_errors.append(
                    {
                        "code": "research_project_mismatch",
                        "message": "Fondskrav og ansøgningsbeløb er researchet til et andet projekt",
                    }
                )
        deadline, rolling = _deadline_payload(fund)
        if not deadline and not rolling:
            preflight_errors.append(
                {"code": "unverified_deadline", "message": "Aktuel frist eller løbende status mangler"}
            )
        if preflight_errors:
            skipped.append(
                {
                    "fund_id": match["fund_id"],
                    "fund_name": match["fund_name"],
                    "errors": preflight_errors,
                }
            )
            if explicit:
                continue
        else:
            selected.append((fund, match, source_check))
        if not explicit and len(selected) >= limit:
            break

    if explicit and skipped:
        raise BatchPreparationError(
            "Mindst én udvalgt fond er ikke klar til ansøgning",
            errors=[error for item in skipped for error in item["errors"]],
        )
    if not selected:
        raise BatchPreparationError(
            "Ingen fonde bestod go/no-go og kildekontrollen",
            errors=[error for item in skipped for error in item["errors"]],
        )
    if explicit:
        selected = selected[:limit]

    funding_strategy: dict[str, Any] = {}
    if len(selected) > 1:
        raw_strategy = project.get("multi_funding_strategy", {})
        if not isinstance(raw_strategy, Mapping):
            raw_strategy = {}
        funding_strategy = deepcopy(dict(raw_strategy))
        mode = str(funding_strategy.get("mode", "")).casefold().strip()
        overaward_plan = str(funding_strategy.get("overaward_plan", "")).strip()
        allocation_note = str(funding_strategy.get("allocation_note", "")).strip()
        try:
            max_total_grants = float(funding_strategy.get("max_total_grants_dkk", 0))
        except (TypeError, ValueError):
            max_total_grants = 0.0
        strategy_errors: list[dict[str, str]] = []
        if mode not in {"alternatives", "complementary", "mixed"}:
            strategy_errors.append(
                {"code": "multi_funding_mode_missing", "message": "Angiv alternatives, complementary eller mixed"}
            )
        if max_total_grants <= 0 or max_total_grants > float(normalised["requested_amount"]):
            strategy_errors.append(
                {
                    "code": "multi_funding_cap_invalid",
                    "message": "max_total_grants_dkk skal være positivt og højst projektets dokumenterede fondsfinansieringsbehov",
                }
            )
        if not overaward_plan:
            strategy_errors.append(
                {"code": "overaward_plan_missing", "message": "Beskriv håndtering hvis flere fonde giver tilsagn"}
            )
        if not allocation_note:
            strategy_errors.append(
                {"code": "funding_allocation_missing", "message": "Beskriv hvilke budgetdele ansøgningerne dækker"}
            )
        if strategy_errors:
            raise BatchPreparationError(
                "Et batch med flere fonde kræver en eksplicit dobbeltfinansieringsstrategi",
                errors=strategy_errors,
            )

    loaded_application_template = _load_application_template(application_template, template_dir)
    loaded_requirements_template = _load_requirements_template(requirements_template, template_dir)

    prepared: list[dict[str, Any]] = []
    rendered_digests: set[str] = set()
    rendered_packages: list[dict[str, Any]] = []
    for position, (fund, match, source) in enumerate(selected, start=1):
        context = _template_context(normalised, fund, match, source)
        requirements = _render_requirements(
            loaded_requirements_template,
            context,
            normalised,
            fund,
            match,
            source,
        )
        context = dict(context)
        context["REQUESTED_AMOUNT_DKK"] = _format_dkk(requirements["amount"]["requested_dkk"])
        application = _render_application(
            loaded_application_template,
            context,
            project,
            normalised,
            fund,
            match,
            requirements,
        )
        validation = validate_application_package(
            project=normalised,
            fund=fund,
            match=match,
            requirements=requirements,
            application=application,
            as_of=reference_date,
            source_max_age_days=source_max_age_days,
        )
        if not validation["valid"]:
            raise BatchPreparationError(
                f"Ansøgningspakken til {match['fund_name']} bestod ikke kvalitetskontrollen",
                errors=validation["errors"],
            )
        draft_digest = hashlib.sha256(application.encode("utf-8")).hexdigest()
        if draft_digest in rendered_digests:
            raise BatchPreparationError(
                "To fonde fik identiske ansøgningstekster; hver kladde skal være fondsspecifik"
            )
        rendered_digests.add(draft_digest)
        submission = _submission_payload(
            normalised,
            fund,
            requirements,
            raw_project=project,
        )
        approval_hash = calculate_approval_hash(requirements, application, submission)
        approval = {
            "schema_version": 1,
            "fund_id": match["fund_id"],
            "fund_name": match["fund_name"],
            "project_id": normalised["project_id"],
            "status": "pending_review",
            "go_no_go": "go",
            "approval_hash_algorithm": "sha256",
            "approval_hash": approval_hash,
            "fund_research_fingerprint": fund_research_fingerprint(fund),
            "approved_by": None,
            "approved_at": None,
            "content_files": ["requirements.json", "application.md"],
            "checks": validation["checks"],
            "submission": submission,
            "created_on": reference_date.isoformat(),
        }
        rendered_packages.append(
            {
                "position": position,
                "fund": fund,
                "match": match,
                "requirements": requirements,
                "application": application,
                "approval": approval,
            }
        )

    if len(rendered_packages) > 1:
        requested_total = sum(
            float(package["requirements"]["amount"]["requested_dkk"])
            for package in rendered_packages
        )
        max_total_grants = float(funding_strategy["max_total_grants_dkk"])
        if funding_strategy["mode"].casefold() == "complementary" and requested_total > max_total_grants + 1:
            raise BatchPreparationError(
                "Komplementære ansøgningsbeløb overstiger den samlede tilskudsramme",
                errors=[
                    {
                        "code": "multi_funding_amount_exceeds_cap",
                        "message": f"Der søges samlet {requested_total:.0f} kr. mod en ramme på {max_total_grants:.0f} kr.",
                    }
                ],
            )
        funding_strategy["sum_requested_dkk"] = round(requested_total)

    raw_output = Path(output_dir).expanduser()
    if raw_output.is_symlink():
        raise BatchPreparationError("Outputmappen må ikke være et symlink")
    output = raw_output.resolve()
    if output.exists() and not output.is_dir():
        raise BatchPreparationError(f"Outputstien er ikke en mappe: {output}")
    output_existed = output.exists()
    output.mkdir(parents=True, exist_ok=True)
    if os.name == "posix" and not output_existed:
        os.chmod(output, 0o700)
    project_snapshot = {
        "schema_version": 1,
        "validated_on": reference_date.isoformat(),
        "stage": "application",
        "raw": deepcopy(dict(project)),
        "normalized": normalised,
        "warnings": project_report["warnings"],
    }
    _write_text(
        output / "project.json",
        _json_text(project_snapshot),
        overwrite=overwrite,
    )
    for package in rendered_packages:
        position = package["position"]
        match = package["match"]
        folder_name = f"{position:02d}-{_slug(match['fund_name'], str(match['fund_id']))}"
        fund_dir = output / folder_name
        if fund_dir.is_symlink():
            raise BatchPreparationError(f"Fondsmappen må ikke være et symlink: {fund_dir}")
        fund_dir_existed = fund_dir.exists()
        fund_dir.mkdir(parents=False, exist_ok=True)
        if os.name == "posix" and not fund_dir_existed:
            os.chmod(fund_dir, 0o700)
        _write_text(
            fund_dir / "fund.json",
            _json_text(package["fund"]),
            overwrite=overwrite,
        )
        _write_text(
            fund_dir / "match.json",
            _json_text(package["match"]),
            overwrite=overwrite,
        )
        _write_text(
            fund_dir / "requirements.json",
            _json_text(package["requirements"]),
            overwrite=overwrite,
        )
        _write_text(
            fund_dir / "application.md",
            package["application"],
            overwrite=overwrite,
        )
        _write_text(
            fund_dir / "approval.json",
            _json_text(package["approval"]),
            overwrite=overwrite,
        )
        prepared.append(
            {
                "fund_id": match["fund_id"],
                "fund_name": match["fund_name"],
                "score": match["score"],
                "folder": str(fund_dir),
                "relative_folder": folder_name,
                "approval_hash": package["approval"]["approval_hash"],
                "fund_research_fingerprint": package["approval"]["fund_research_fingerprint"],
                "status": "pending_review",
                "files": [
                    "fund.json",
                    "match.json",
                    "requirements.json",
                    "application.md",
                    "approval.json",
                ],
            }
        )

    batch_identity = {
        "project_id": normalised["project_id"],
        "as_of": reference_date.isoformat(),
        "fund_ids": [item["fund_id"] for item in prepared],
    }
    manifest = {
        "schema_version": 1,
        "batch_id": "batch-" + hashlib.sha256(_canonical_json(batch_identity)).hexdigest()[:16],
        "project_id": normalised["project_id"],
        "created_on": reference_date.isoformat(),
        "ready_confirmed": True,
        "network_action_performed": False,
        "project_file": "project.json",
        "max_batch_size": MAX_BATCH_SIZE,
        "count": len(prepared),
        "applications": prepared,
        "skipped": skipped if not explicit else [],
        "multi_funding_strategy": funding_strategy if len(prepared) > 1 else None,
    }
    _write_text(output / "batch.json", _json_text(manifest), overwrite=overwrite)
    return manifest


def _read_json_file(path: Path) -> Mapping[str, Any]:
    if path.is_symlink():
        raise BatchPreparationError(f"Afviser at læse JSON gennem et symlink: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchPreparationError(f"Kan ikke læse gyldig JSON fra {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise BatchPreparationError(f"JSON-roden skal være et objekt: {path}")
    return value


def _manifest_folder(root: Path, item: Mapping[str, Any]) -> Path:
    raw = item.get("relative_folder") or item.get("folder")
    if not raw:
        raise BatchPreparationError("En manifestpost mangler folder")
    path = Path(str(raw))
    candidate = path if path.is_absolute() else root / path
    candidate = candidate.resolve()
    if candidate != root and root not in candidate.parents:
        # Absolutte stier fra en flyttet, legitim batch kan genfindes via
        # mappenavnet. Stier med traversal accepteres aldrig.
        if ".." in path.parts:
            raise BatchPreparationError(f"Ugyldig folder uden for batchmappen: {raw}")
        relocated = (root / path.name).resolve()
        if root not in relocated.parents:
            raise BatchPreparationError(f"Ugyldig folder uden for batchmappen: {raw}")
        candidate = relocated
    return candidate


def validate_batch_directory(
    batch_dir: str | Path,
    store: Any = None,
    *,
    as_of: date | datetime | str | None = None,
    max_age: int = DEFAULT_SOURCE_MAX_AGE_DAYS,
    require_approval: bool = False,
) -> dict[str, Any]:
    """Efterprøv en hel batch lokalt, inklusive snapshots og approval-hashes."""

    root = Path(batch_dir).expanduser().resolve()
    errors: list[dict[str, Any]] = []

    def error(code: str, message: str, *, fund_id: Any = None, path: Path | None = None) -> None:
        item: dict[str, Any] = {"code": code, "message": message}
        if fund_id is not None:
            item["fund_id"] = fund_id
        if path is not None:
            item["path"] = str(path)
        errors.append(item)

    if not root.is_dir():
        error("batch_directory_missing", "Batchmappen findes ikke", path=root)
        return {"valid": False, "errors": errors, "applications": []}
    manifest_path = root / "batch.json"
    project_path = root / "project.json"
    try:
        manifest = _read_json_file(manifest_path)
    except BatchPreparationError as exc:
        error("invalid_manifest", str(exc), path=manifest_path)
        return {"valid": False, "errors": errors, "applications": []}
    try:
        project_snapshot = _read_json_file(project_path)
    except BatchPreparationError as exc:
        error("invalid_project_snapshot", str(exc), path=project_path)
        return {"valid": False, "errors": errors, "applications": []}
    project = project_snapshot.get("normalized")
    if not isinstance(project, Mapping):
        error("invalid_project_snapshot", "project.json mangler et normaliseret projekt", path=project_path)
        return {"valid": False, "errors": errors, "applications": []}

    expected_project_id = str(project.get("project_id", "")).strip()
    if not expected_project_id or str(manifest.get("project_id", "")).strip() != expected_project_id:
        error(
            "batch_project_identity_mismatch",
            "project_id stemmer ikke mellem batch.json og project.json",
            path=manifest_path,
        )

    manifest_items = manifest.get("applications", [])
    if not isinstance(manifest_items, list) or not manifest_items:
        error("empty_manifest", "batch.json indeholder ingen ansøgninger", path=manifest_path)
        return {"valid": False, "errors": errors, "applications": []}
    if len(manifest_items) > MAX_BATCH_SIZE:
        error("batch_too_large", f"En batch må højst indeholde {MAX_BATCH_SIZE} ansøgninger")
    if manifest.get("count") != len(manifest_items):
        error("batch_count_mismatch", "batch.json count stemmer ikke med applications-listen")
    manifest_ids = [str(item.get("fund_id")) for item in manifest_items if isinstance(item, Mapping)]
    if len(set(manifest_ids)) != len(manifest_ids):
        error("duplicate_manifest_fund", "batch.json indeholder samme fund_id mere end én gang")

    results: list[dict[str, Any]] = []
    for manifest_item in manifest_items:
        if not isinstance(manifest_item, Mapping):
            error("invalid_manifest_item", "En ansøgningspost i manifestet er ikke et objekt")
            continue
        fund_id = manifest_item.get("fund_id")
        try:
            fund_dir = _manifest_folder(root, manifest_item)
        except BatchPreparationError as exc:
            error("invalid_fund_folder", str(exc), fund_id=fund_id)
            continue
        required_paths = {
            "fund": fund_dir / "fund.json",
            "match": fund_dir / "match.json",
            "requirements": fund_dir / "requirements.json",
            "application": fund_dir / "application.md",
            "approval": fund_dir / "approval.json",
        }
        linked = [path for path in required_paths.values() if path.is_symlink()]
        if linked:
            for path in linked:
                error("package_file_symlink", "Pakkefil må ikke være et symlink", fund_id=fund_id, path=path)
            continue
        missing = [path for path in required_paths.values() if not path.is_file()]
        if missing:
            for path in missing:
                error("package_file_missing", "Pakkefil mangler", fund_id=fund_id, path=path)
            continue
        try:
            fund_snapshot = _read_json_file(required_paths["fund"])
            match = _read_json_file(required_paths["match"])
            requirements = _read_json_file(required_paths["requirements"])
            approval = _read_json_file(required_paths["approval"])
            application = required_paths["application"].read_text(encoding="utf-8")
        except (BatchPreparationError, OSError) as exc:
            error("package_read_error", str(exc), fund_id=fund_id, path=fund_dir)
            continue

        expected_fund_id = str(fund_id)
        expected_fund_name = str(manifest_item.get("fund_name", "")).strip()

        def check_identity(
            payload: Mapping[str, Any],
            label: str,
            *,
            require_project: bool = False,
        ) -> None:
            payload_fund_id = str(_first(payload, "fund_id", "id", default=""))
            payload_fund_name = str(_first(payload, "fund_name", "name", default="")).strip()
            if payload_fund_id != expected_fund_id:
                error(
                    "package_fund_id_mismatch",
                    f"fund_id i {label} stemmer ikke med batch.json",
                    fund_id=fund_id,
                    path=fund_dir,
                )
            if payload_fund_name != expected_fund_name:
                error(
                    "package_fund_name_mismatch",
                    f"fund_name i {label} stemmer ikke med batch.json",
                    fund_id=fund_id,
                    path=fund_dir,
                )
            if require_project and str(payload.get("project_id", "")).strip() != expected_project_id:
                error(
                    "package_project_id_mismatch",
                    f"project_id i {label} stemmer ikke med project.json",
                    fund_id=fund_id,
                    path=fund_dir,
                )

        check_identity(fund_snapshot, "fund.json")
        check_identity(match, "match.json")
        check_identity(requirements, "requirements.json", require_project=True)
        check_identity(approval, "approval.json", require_project=True)
        submission_identity = approval.get("submission")
        if not isinstance(submission_identity, Mapping):
            error(
                "approval_submission_missing",
                "approval.json mangler det hashbundne submission-objekt",
                fund_id=fund_id,
                path=required_paths["approval"],
            )
        else:
            check_identity(submission_identity, "approval.json submission", require_project=True)

        requirements_amount = requirements.get("amount")
        requested_amount = (
            _number(_first(requirements_amount, "requested_dkk", "requested", default=None))
            if isinstance(requirements_amount, Mapping)
            else None
        )
        if isinstance(submission_identity, Mapping):
            submission_amount = _number(submission_identity.get("requested_amount_dkk"))
            if (
                requested_amount is None
                or submission_amount is None
                or abs(submission_amount - requested_amount) > 1
            ):
                error(
                    "submission_requested_amount_mismatch",
                    "Ansøgningsbeløbet i approval.json submission stemmer ikke med requirements.json",
                    fund_id=fund_id,
                    path=required_paths["approval"],
                )
            history_context = submission_identity.get("history_record_after_submission")
            if isinstance(history_context, Mapping):
                history_amount = _number(history_context.get("amount_requested"))
                if (
                    requested_amount is None
                    or history_amount is None
                    or abs(history_amount - requested_amount) > 1
                ):
                    error(
                        "history_requested_amount_mismatch",
                        "Ansøgningsbeløbet i indsendelseshistorikken stemmer ikke med requirements.json",
                        fund_id=fund_id,
                        path=required_paths["approval"],
                    )

        current_fund = fund_snapshot
        if store is not None:
            try:
                current_fund = get_fund_record(store, fund_id)
            except (KeyError, TypeError, ValueError) as exc:
                error("fund_missing_from_index", str(exc), fund_id=fund_id)
                current_fund = fund_snapshot
            else:
                old_url = _source_info(fund_snapshot)["url"]
                current_url = _source_info(current_fund)["url"]
                if old_url and current_url and old_url != current_url:
                    error(
                        "official_source_changed",
                        "Fondens officielle URL er ændret siden pakken blev forberedt",
                        fund_id=fund_id,
                    )
                expected_research = str(
                    approval.get("fund_research_fingerprint")
                    or manifest_item.get("fund_research_fingerprint")
                    or fund_research_fingerprint(fund_snapshot)
                )
                if fund_research_fingerprint(current_fund) != expected_research:
                    error(
                        "fund_requirements_changed",
                        "Fondens kravrelevante indeksdata er ændret siden pakken blev forberedt; regenerér og godkend igen",
                        fund_id=fund_id,
                    )
        package_validation = validate_application_package(
            project=project,
            fund=current_fund,
            match=match,
            requirements=requirements,
            application=application,
            as_of=as_of,
            source_max_age_days=max_age,
        )
        for package_error in package_validation["errors"]:
            error(
                str(package_error["code"]),
                str(package_error["message"]),
                fund_id=fund_id,
                path=fund_dir,
            )
        submission_context = approval.get("submission", {})
        expected_project_fingerprint = (
            submission_context.get("project_snapshot_fingerprint")
            if isinstance(submission_context, Mapping)
            else None
        )
        current_project_fingerprint = project_snapshot_fingerprint(
            {"raw": project_snapshot.get("raw", {}), "normalized": dict(project)}
        )
        if expected_project_fingerprint != current_project_fingerprint:
            error(
                "project_snapshot_changed",
                "Projektbrief/budget er ændret siden pakken blev forberedt; regenerér og godkend igen",
                fund_id=fund_id,
                path=project_path,
            )
        hash_valid = verify_approval_hash(requirements, application, approval)
        approval_is_final = approval.get("status") == "approved"
        if not hash_valid and approval_is_final:
            error(
                "approval_hash_mismatch",
                "Krav, ansøgning eller submission-data er ændret efter hashberegningen",
                fund_id=fund_id,
                path=required_paths["approval"],
            )
        if approval.get("approval_hash") != manifest_item.get("approval_hash") and approval_is_final:
            error(
                "manifest_hash_mismatch",
                "Manifestets approval_hash stemmer ikke med approval.json",
                fund_id=fund_id,
            )
        approved_by = str(approval.get("approved_by") or "").strip()
        approved_at = str(approval.get("approved_at") or "").strip()
        approval_timestamp_valid = False
        if approved_at:
            try:
                parsed_approval = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
                approval_timestamp_valid = parsed_approval.tzinfo is not None
            except ValueError:
                approval_timestamp_valid = False
        approved = approval_is_final and bool(approved_by) and approval_timestamp_valid
        if approval_is_final and not approved:
            error(
                "approval_metadata_invalid",
                "En godkendt ansøgning kræver approved_by og et timezone-aware ISO approved_at",
                fund_id=fund_id,
                path=required_paths["approval"],
            )
        if approval_is_final:
            if manifest_item.get("status") not in {"approved", "submitted"}:
                error(
                    "manifest_approval_status_mismatch",
                    "Manifestet er hverken markeret approved eller submitted",
                    fund_id=fund_id,
                )
            if str(manifest_item.get("approved_by") or "").strip() != approved_by:
                error("manifest_approver_mismatch", "approved_by stemmer ikke mellem manifest og approval", fund_id=fund_id)
            if str(manifest_item.get("approved_at") or "").strip() != approved_at:
                error("manifest_approval_time_mismatch", "approved_at stemmer ikke mellem manifest og approval", fund_id=fund_id)
        if require_approval and not approved:
            error("approval_required", "Ansøgningen mangler eksplicit intern godkendelse", fund_id=fund_id)
        results.append(
            {
                "fund_id": fund_id,
                "fund_name": manifest_item.get("fund_name"),
                "folder": str(fund_dir),
                "hash_valid": hash_valid,
                "pending_hash_refresh": not hash_valid and not approval_is_final,
                "approved": approved,
                "requested_amount_dkk": requested_amount,
            }
        )

    if len(manifest_items) > 1:
        manifest_strategy = manifest.get("multi_funding_strategy")
        raw_project = project_snapshot.get("raw")
        raw_strategy = (
            raw_project.get("multi_funding_strategy")
            if isinstance(raw_project, Mapping)
            else None
        )
        if not isinstance(manifest_strategy, Mapping):
            error(
                "multi_funding_strategy_missing",
                "Et batch med flere fonde mangler multi_funding_strategy i batch.json",
                path=manifest_path,
            )
            manifest_strategy = {}
        if not isinstance(raw_strategy, Mapping):
            error(
                "project_multi_funding_strategy_missing",
                "Projektbriefet mangler den dobbeltfinansieringsstrategi, som batchen skal følge",
                path=project_path,
            )
            raw_strategy = {}

        manifest_mode = str(manifest_strategy.get("mode", "")).casefold().strip()
        project_mode = str(raw_strategy.get("mode", "")).casefold().strip()
        manifest_cap = _number(manifest_strategy.get("max_total_grants_dkk"))
        project_cap = _number(raw_strategy.get("max_total_grants_dkk"))
        project_grant_need = _number(project.get("requested_amount"))
        manifest_allocation = str(manifest_strategy.get("allocation_note", "")).strip()
        project_allocation = str(raw_strategy.get("allocation_note", "")).strip()
        manifest_overaward = str(manifest_strategy.get("overaward_plan", "")).strip()
        project_overaward = str(raw_strategy.get("overaward_plan", "")).strip()

        if manifest_mode not in {"alternatives", "complementary", "mixed"}:
            error("multi_funding_mode_invalid", "Batchens multi_funding_strategy har ugyldig mode", path=manifest_path)
        if (
            manifest_cap is None
            or manifest_cap <= 0
            or project_grant_need is None
            or manifest_cap > project_grant_need + 1
        ):
            error(
                "multi_funding_cap_invalid",
                "Batchens tilskudsramme skal være positiv og højst projektets fondsfinansieringsbehov",
                path=manifest_path,
            )
        if not manifest_allocation:
            error(
                "funding_allocation_missing",
                "Batchens multi_funding_strategy mangler allocation_note",
                path=manifest_path,
            )
        if not manifest_overaward:
            error(
                "overaward_plan_missing",
                "Batchens multi_funding_strategy mangler overaward_plan",
                path=manifest_path,
            )

        strategy_matches_project = (
            manifest_mode == project_mode
            and manifest_cap is not None
            and project_cap is not None
            and abs(manifest_cap - project_cap) <= 1
            and manifest_allocation == project_allocation
            and manifest_overaward == project_overaward
        )
        if not strategy_matches_project:
            error(
                "multi_funding_strategy_mismatch",
                "Batchens dobbeltfinansieringsstrategi stemmer ikke med projektbriefet",
                path=manifest_path,
            )

        requested_entries = [
            (item.get("fund_id"), item.get("requested_amount_dkk"))
            for item in results
        ]
        valid_requested_entries: list[tuple[Any, float]] = []
        for fund_id, raw_requested in requested_entries:
            requested = _number(raw_requested)
            if requested is None or requested <= 0:
                error(
                    "multi_funding_requested_amount_invalid",
                    "Et fondsspecifikt ansøgningsbeløb mangler eller er ugyldigt",
                    fund_id=fund_id,
                )
                continue
            valid_requested_entries.append((fund_id, requested))
            if manifest_cap is not None and requested > manifest_cap + 1:
                error(
                    "multi_funding_request_exceeds_cap",
                    "Det fondsspecifikke ansøgningsbeløb overstiger batchens samlede tilskudsramme",
                    fund_id=fund_id,
                )

        if len(valid_requested_entries) == len(manifest_items):
            requested_total = sum(amount for _, amount in valid_requested_entries)
            recorded_total = _number(manifest_strategy.get("sum_requested_dkk"))
            if recorded_total is None or abs(recorded_total - requested_total) > 1:
                error(
                    "multi_funding_sum_mismatch",
                    "sum_requested_dkk i batch.json stemmer ikke med ansøgningspakkernes aktuelle beløb",
                    path=manifest_path,
                )
            if (
                manifest_mode == "complementary"
                and manifest_cap is not None
                and requested_total > manifest_cap + 1
            ):
                error(
                    "multi_funding_amount_exceeds_cap",
                    f"Komplementære ansøgninger søger samlet {requested_total:.0f} kr. "
                    f"mod en ramme på {manifest_cap:.0f} kr.",
                    path=manifest_path,
                )
    return {
        "valid": not errors,
        "errors": errors,
        "applications": results,
        "batch_id": manifest.get("batch_id"),
        "require_approval": require_approval,
        "network_action_performed": False,
    }


def _approval_timestamp(value: datetime | str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.replace(microsecond=0).isoformat()
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BatchPreparationError("approved_at skal være et ISO-datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.replace(microsecond=0).isoformat()


def approve_application(
    batch_dir: str | Path,
    fund_id: Any,
    approved_by: str,
    approved_at: datetime | str | None = None,
    *,
    store: Any = None,
    as_of: date | datetime | str | None = None,
    max_age: int = DEFAULT_SOURCE_MAX_AGE_DAYS,
) -> dict[str, Any]:
    """Godkend én uændret pakke internt; udfør ingen indsendelse."""

    approver = str(approved_by or "").strip()
    if not approver:
        raise BatchPreparationError("approved_by må ikke være tom")
    root = Path(batch_dir).expanduser().resolve()
    manifest_path = root / "batch.json"
    manifest = dict(_read_json_file(manifest_path))
    items = manifest.get("applications", [])
    target: dict[str, Any] | None = None
    if isinstance(items, list):
        for item in items:
            if isinstance(item, Mapping) and str(item.get("fund_id")) == str(fund_id):
                target = dict(item)
                break
    if target is None:
        raise BatchPreparationError(f"Fonden findes ikke i batchen: {fund_id}")

    validation = validate_batch_directory(
        root,
        store=store,
        as_of=as_of,
        max_age=max_age,
        require_approval=False,
    )
    target_errors = [
        error
        for error in validation["errors"]
        if error.get("fund_id") in (None, target.get("fund_id"))
        or str(error.get("fund_id")) == str(target.get("fund_id"))
    ]
    # A pending draft is expected to get a new hash after legitimate edits.
    # The explicit approval call binds the approver to the content as it exists
    # now; all substantive validation errors still block approval.
    target_errors = [
        error
        for error in target_errors
        if error.get("code") not in {"approval_hash_mismatch", "manifest_hash_mismatch"}
    ]
    if target_errors:
        raise BatchPreparationError(
            "Ansøgningen kan ikke godkendes, fordi valideringen fejlede",
            errors=target_errors,
        )
    fund_dir = _manifest_folder(root, target)
    requirements = _read_json_file(fund_dir / "requirements.json")
    application = (fund_dir / "application.md").read_text(encoding="utf-8")
    approval = dict(_read_json_file(fund_dir / "approval.json"))
    submission = approval.get("submission")
    if not isinstance(submission, Mapping):
        submission = None
    approval["approval_hash"] = calculate_approval_hash(requirements, application, submission)
    approval["status"] = "approved"
    approval["approved_by"] = approver
    approval["approved_at"] = _approval_timestamp(approved_at)
    approval["network_action_performed"] = False
    _write_text(fund_dir / "approval.json", _json_text(approval), overwrite=True)

    updated_items: list[Any] = []
    for item in items:
        if isinstance(item, Mapping) and str(item.get("fund_id")) == str(fund_id):
            updated = dict(item)
            updated["status"] = "approved"
            updated["approved_by"] = approver
            updated["approved_at"] = approval["approved_at"]
            updated["approval_hash"] = approval["approval_hash"]
            updated_items.append(updated)
        else:
            updated_items.append(item)
    manifest["applications"] = updated_items
    _write_text(manifest_path, _json_text(manifest), overwrite=True)
    return approval


def prepare_batch(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Kort alias for :func:`prepare_application_batch`."""

    return prepare_application_batch(*args, **kwargs)


__all__ = [
    "BatchPreparationError",
    "DEFAULT_SOURCE_MAX_AGE_DAYS",
    "MAX_BATCH_SIZE",
    "calculate_approval_hash",
    "contains_placeholders",
    "find_placeholders",
    "fund_research_fingerprint",
    "project_snapshot_fingerprint",
    "prepare_application_batch",
    "prepare_batch",
    "approve_application",
    "validate_application_package",
    "validate_batch_directory",
    "validate_official_source",
    "validate_requirement_research",
    "verify_approval_hash",
]
