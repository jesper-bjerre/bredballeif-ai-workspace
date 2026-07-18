"""Deterministisk validering og matchning af projekter mod fondsposter.

Modulet er bevidst uden netværkskode.  Det arbejder på almindelige mappings og
et duck-typed ``IndexStore``; dermed kan samme logik bruges af CLI'en, tests og
andre agenter uden at koble matchresultatet til en bestemt database.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timezone
import inspect
import math
import re
import unicodedata
from typing import Any


MATCH_WEIGHTS: dict[str, int] = {
    "geography": 20,
    "purpose": 25,
    "target_groups": 15,
    "expenses": 15,
    "amount": 10,
    "deadline": 10,
    "documentation": 5,
}

if sum(MATCH_WEIGHTS.values()) != 100:  # pragma: no cover - udvikler-værn
    raise RuntimeError("Matchvægtene skal summere til 100")


class ProjectValidationError(ValueError):
    """Rejses, når et projektbrief ikke opfylder den valgte fase."""

    def __init__(self, errors: Sequence[Mapping[str, Any]]) -> None:
        self.errors = [dict(error) for error in errors]
        message = "; ".join(str(error.get("message", error)) for error in errors)
        super().__init__(message or "Projektbriefet er ugyldigt")


_STOP_WORDS = {
    "af",
    "alle",
    "at",
    "de",
    "den",
    "der",
    "det",
    "en",
    "er",
    "et",
    "for",
    "fra",
    "i",
    "med",
    "og",
    "om",
    "pa",
    "som",
    "til",
    "ved",
}
_NATIONAL_TERMS = {
    "danmark",
    "hele danmark",
    "hele landet",
    "landsdaekkende",
    "national",
    "nationalt",
    "rigsdaekkende",
}
_ROLLING_TERMS = {
    "aaben",
    "aabent",
    "ingen frist",
    "lobende",
    "rolling",
    "sog lobende",
}
_CLOSED_TERMS = {"closed", "inactive", "lukket", "nedlagt", "pa pause", "udlobet"}
_DANISH_TRANSLATION = str.maketrans(
    {"æ": "ae", "ø": "oe", "å": "aa", "Æ": "ae", "Ø": "oe", "Å": "aa"}
)


def _ascii_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").translate(_DANISH_TRANSLATION))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _flatten(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        preferred_keys = (
            "eligible",
            "included",
            "values",
            "items",
            "names",
            "areas",
            "purposes",
            "target_groups",
            "expenses",
        )
        selected = [value[key] for key in preferred_keys if key in value]
        if selected:
            result: list[Any] = []
            for item in selected:
                result.extend(_flatten(item))
            return result
        return [item for item in value.values() if not isinstance(item, (Mapping, list, tuple, set))]
    if isinstance(value, (list, tuple, set, frozenset)):
        result = []
        for item in value:
            result.extend(_flatten(item))
        return result
    if isinstance(value, str):
        # Komma/semikolon er sikre listeadskillere. Bindestreg er ikke.
        return [part.strip() for part in re.split(r"[;,|]", value) if part.strip()]
    return [value]


def _text_list(value: Any) -> list[str]:
    values = [str(item).strip() for item in _flatten(value) if str(item).strip()]
    # Stabil deduplikering uden at ændre brugerens tekst.
    seen: set[str] = set()
    result: list[str] = []
    for value_text in values:
        key = _ascii_text(value_text)
        if key and key not in seen:
            seen.add(key)
            result.append(value_text)
    return result


def _tokens(value: Any) -> set[str]:
    tokens: set[str] = set()
    for text in _text_list(value):
        tokens.update(
            token
            for token in _ascii_text(text).split()
            if len(token) > 1 and token not in _STOP_WORDS
        )
    return tokens


def _first(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, "", [], {}):
            return mapping[key]
    return default


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, Mapping):
        value = _first(value, "date", "deadline", "next", "value", "at")
        if value is None:
            return None
    text = str(value).strip()
    if not text:
        return None
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


def _as_of_date(value: date | datetime | str | None) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    parsed = _parse_date(value)
    if parsed is None:
        raise ValueError("as_of skal være en ISO-dato eller date/datetime")
    return parsed


def _money(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, Mapping):
        value = _first(value, "requested", "value", "amount", "dkk", "max", "maximum")
        if value is None:
            return None
    text = str(value).strip().casefold()
    if not text:
        return None
    multiplier = 1.0
    if re.search(r"\b(mio|million)\b", text):
        multiplier = 1_000_000.0
    elif re.search(r"\b(tusind|tkr)\b", text):
        multiplier = 1_000.0
    cleaned = re.sub(r"[^0-9,.-]", "", text)
    if not cleaned:
        return None
    # Dansk tusindtalsseparator og decimalkomma.
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        tail = cleaned.rsplit(",", 1)[1]
        cleaned = cleaned.replace(",", "." if len(tail) <= 2 else "")
    elif cleaned.count(".") > 1 or (
        "." in cleaned and len(cleaned.rsplit(".", 1)[1]) == 3
    ):
        cleaned = cleaned.replace(".", "")
    try:
        number = float(cleaned) * multiplier
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _normalise_expenses(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return _text_list(list(value.keys()))
    result: list[str] = []
    for item in value if isinstance(value, (list, tuple, set)) else _flatten(value):
        if isinstance(item, Mapping):
            name = _first(item, "category", "name", "description", "type")
            if name:
                result.append(str(name).strip())
        elif str(item).strip():
            result.append(str(item).strip())
    return _text_list(result)


def _normalise_applicant(project: Mapping[str, Any]) -> dict[str, Any]:
    raw = _first(project, "applicant", "organisation", "organization", default={})
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, Mapping):
        raw = {}
    contact = _first(raw, "contact", default=_first(project, "contact", default={}))
    if isinstance(contact, str):
        contact = {"name": contact}
    if not isinstance(contact, Mapping):
        contact = {}
    return {
        "name": str(_first(raw, "name", default=_first(project, "applicant_name", default=""))).strip(),
        "type": str(
            _first(
                raw,
                "type",
                "applicant_type",
                "legal_form",
                default=_first(project, "applicant_type", default=""),
            )
        ).strip(),
        "cvr": str(_first(raw, "cvr", "cvr_number", default=_first(project, "cvr", default=""))).strip(),
        "contact": {
            "name": str(_first(contact, "name", default="")).strip(),
            "email": str(_first(contact, "email", default="")).strip(),
            "phone": str(_first(contact, "phone", "telephone", default="")).strip(),
        },
    }


def _sum_budget_items(value: Any) -> tuple[float | None, int, int, int]:
    if isinstance(value, Mapping):
        entries = list(value.values())
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        entries = list(value)
    else:
        return None, 0, 0, 0
    amounts: list[float] = []
    invalid = 0
    negative = 0
    for entry in entries:
        raw = (
            _first(entry, "amount_dkk", "total_dkk", "amount", "total", "cost", default=None)
            if isinstance(entry, Mapping)
            else entry
        )
        amount = None if isinstance(raw, bool) else _money(raw)
        if amount is None:
            invalid += 1
            continue
        if amount < 0:
            negative += 1
        amounts.append(amount)
    return (sum(amounts) if amounts else None, len(entries), invalid, negative)


def validate_project(
    project: Mapping[str, Any],
    *,
    stage: str = "matching",
    as_of: date | datetime | str | None = None,
    raise_on_error: bool = False,
) -> dict[str, Any]:
    """Valider og normaliser et projektbrief.

    ``stage='matching'`` kræver kun de oplysninger, der indgår i score og
    hårde stop. ``stage='application'`` kræver desuden et indsendelsesklart
    projekt med tidsplan, aktiviteter, ansøger og kontaktperson.
    """

    if stage not in {"matching", "application"}:
        raise ValueError("stage skal være 'matching' eller 'application'")
    if not isinstance(project, Mapping):
        error = {"code": "invalid_type", "field": "$", "message": "Projektet skal være et objekt"}
        if raise_on_error:
            raise ProjectValidationError([error])
        return {"valid": False, "stage": stage, "errors": [error], "warnings": [], "project": {}}

    applicant = _normalise_applicant(project)
    raw_budget = _first(project, "budget", default={})
    if not isinstance(raw_budget, Mapping):
        raw_budget = {}
    raw_timeline = _first(project, "timeline", default={})
    if not isinstance(raw_timeline, Mapping):
        raw_timeline = {}
    (
        budget_items_total,
        budget_items_count,
        budget_items_invalid_count,
        budget_items_negative_count,
    ) = _sum_budget_items(raw_budget.get("items", []))
    normalised: dict[str, Any] = {
        "project_id": str(_first(project, "project_id", "id", "slug", default="")).strip(),
        "title": str(_first(project, "title", "name", "project_name", default="")).strip(),
        "summary": str(_first(project, "summary", "description", "need", default="")).strip(),
        "purposes": _text_list(_first(project, "purposes", "purpose", "objectives", default=[])),
        "target_groups": _text_list(_first(project, "target_groups", "target_group", default=[])),
        "geography": _text_list(_first(project, "geography", "location", "municipality", default=[])),
        "activities": _text_list(_first(project, "activities", "work_packages", default=[])),
        "expenses": _normalise_expenses(
            _first(
                project,
                "expenses",
                "eligible_expenses",
                "budget_items",
                default=_first(raw_budget, "items", default=[]),
            )
        ),
        "requested_amount": _money(
            _first(
                project,
                "requested_amount",
                "amount_requested",
                "ask",
                default=_first(raw_budget, "requested_dkk", "requested", default=None),
            )
        ),
        "total_budget": _money(
            _first(
                project,
                "total_budget",
                default=_first(raw_budget, "total_dkk", "total", default=None),
            )
        ),
        "own_financing": _money(
            _first(
                project,
                "own_financing",
                "co_financing",
                default=_first(raw_budget, "own_financing_dkk", default=0),
            )
        )
        or 0.0,
        "other_confirmed_financing": _money(
            _first(raw_budget, "other_confirmed_dkk", "other_confirmed", default=0)
        )
        or 0.0,
        "other_pending_financing": _money(
            _first(raw_budget, "other_pending_dkk", "other_pending", default=0)
        )
        or 0.0,
        "budget_items_total": budget_items_total,
        "budget_items_count": budget_items_count,
        "budget_items_invalid_count": budget_items_invalid_count,
        "budget_items_negative_count": budget_items_negative_count,
        "start_date": _parse_date(
            _first(project, "start_date", "project_start", default=_first(raw_timeline, "start", default=None))
        ),
        "end_date": _parse_date(
            _first(project, "end_date", "project_end", default=_first(raw_timeline, "end", default=None))
        ),
        "documentation": _text_list(
            _first(
                project,
                "documentation",
                "documentation_available",
                "attachments",
                "documents",
                default=[],
            )
        ),
        "outputs": _text_list(_first(project, "outputs", default=[])),
        "outcomes": _text_list(_first(project, "outcomes", default=[])),
        "measurement": str(_first(project, "measurement", default="")).strip(),
        "continued_operation": str(_first(project, "continued_operation", default="")).strip(),
        "applicant": applicant,
    }

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    def missing(field: str, message: str) -> None:
        errors.append({"code": "missing_field", "field": field, "message": message})

    for field, label in (
        ("project_id", "projekt-id"),
        ("title", "projekttitel"),
        ("summary", "projektresumé"),
        ("purposes", "formål"),
        ("target_groups", "målgruppe"),
        ("geography", "geografi"),
        ("expenses", "udgiftskategorier"),
    ):
        if not normalised[field]:
            missing(field, f"Projektbriefet mangler {label}")

    requested = normalised["requested_amount"]
    total = normalised["total_budget"]
    if requested is None or requested <= 0:
        errors.append(
            {"code": "invalid_amount", "field": "requested_amount", "message": "Ansøgt beløb skal være større end 0"}
        )
    if total is None or total <= 0:
        errors.append(
            {"code": "invalid_amount", "field": "total_budget", "message": "Samlet budget skal være større end 0"}
        )
    if requested and total and requested > total:
        errors.append(
            {
                "code": "amount_exceeds_budget",
                "field": "requested_amount",
                "message": "Ansøgt beløb kan ikke overstige det samlede budget",
            }
        )

    if stage == "application":
        for field, label in (("activities", "aktiviteter"), ("start_date", "startdato"), ("end_date", "slutdato")):
            if not normalised[field]:
                missing(field, f"Et ansøgningsklart projekt mangler {label}")
        for field, label in (("name", "ansøgernavn"), ("type", "ansøgertype"), ("cvr", "CVR-nummer")):
            if not applicant[field]:
                missing(f"applicant.{field}", f"Et ansøgningsklart projekt mangler {label}")
        for field, label in (("name", "kontaktperson"), ("email", "kontaktmail")):
            if not applicant["contact"][field]:
                missing(f"applicant.contact.{field}", f"Et ansøgningsklart projekt mangler {label}")
        cvr_digits = re.sub(r"[\s-]", "", applicant["cvr"])
        if applicant["cvr"] and not re.fullmatch(r"\d{8}", cvr_digits):
            errors.append(
                {"code": "invalid_cvr", "field": "applicant.cvr", "message": "CVR-nummer skal bestå af 8 cifre"}
            )
        email = applicant["contact"]["email"]
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            errors.append(
                {"code": "invalid_email", "field": "applicant.contact.email", "message": "Kontaktmail har ugyldigt format"}
            )
        for field, label in (
            ("outputs", "konkrete output"),
            ("outcomes", "forventede effekter"),
            ("measurement", "målemetode"),
            ("continued_operation", "plan for fortsat drift"),
        ):
            if not normalised[field]:
                missing(field, f"Et ansøgningsklart projekt mangler {label}")
        if normalised["budget_items_count"] == 0:
            missing("budget.items", "Et ansøgningsklart projekt mangler beløbssatte budgetposter")
        elif normalised["budget_items_invalid_count"]:
            errors.append(
                {
                    "code": "budget_item_invalid_amount",
                    "field": "budget.items",
                    "message": "Alle budgetposter skal have et gyldigt numerisk beløb",
                }
            )
        elif normalised["budget_items_negative_count"]:
            errors.append(
                {
                    "code": "budget_item_negative_amount",
                    "field": "budget.items",
                    "message": "Budgetposter må ikke have negative beløb",
                }
            )
        elif total is not None and normalised["budget_items_total"] is not None and abs(
            normalised["budget_items_total"] - total
        ) > 1:
            errors.append(
                {
                    "code": "budget_items_mismatch",
                    "field": "budget.items",
                    "message": "Summen af budgetposterne stemmer ikke med det samlede budget",
                }
            )
        if requested is not None and total is not None:
            financing_total = (
                requested
                + normalised["own_financing"]
                + normalised["other_confirmed_financing"]
                + normalised["other_pending_financing"]
            )
            if abs(financing_total - total) > 1:
                errors.append(
                    {
                        "code": "financing_plan_mismatch",
                        "field": "budget",
                        "message": "Ansøgt beløb og øvrig finansiering stemmer ikke med totalbudgettet",
                    }
                )

    start = normalised["start_date"]
    end = normalised["end_date"]
    if start and end and end < start:
        errors.append(
            {"code": "invalid_date_range", "field": "end_date", "message": "Slutdato ligger før startdato"}
        )
    reference_date = _as_of_date(as_of)
    if stage == "application" and end and end < reference_date:
        errors.append(
            {"code": "project_ended", "field": "end_date", "message": "Projektets slutdato er passeret"}
        )

    if not normalised["documentation"]:
        warnings.append(
            {
                "code": "no_documentation_list",
                "field": "documentation",
                "message": "Der er endnu ikke angivet en bilagsliste",
            }
        )

    report = {
        "valid": not errors,
        "stage": stage,
        "errors": errors,
        "warnings": warnings,
        "project": normalised,
    }
    if errors and raise_on_error:
        raise ProjectValidationError(errors)
    return report


def _similarity(left: Any, right: Any) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    if not intersection:
        return 0.0
    return min(1.0, 2.0 * intersection / (len(left_tokens) + len(right_tokens)))


def _overlaps(left: Any, right: Any) -> bool:
    left_texts = {_ascii_text(item) for item in _text_list(left)}
    right_texts = {_ascii_text(item) for item in _text_list(right)}
    if not left_texts or not right_texts:
        return False
    if any(a == b or (len(a) >= 4 and a in b) or (len(b) >= 4 and b in a) for a in left_texts for b in right_texts):
        return True
    return bool(_tokens(left) & _tokens(right))


def _fund_extra(fund: Mapping[str, Any]) -> Mapping[str, Any]:
    extra = fund.get("extra", {})
    return extra if isinstance(extra, Mapping) else {}


def _fund_field(fund: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    value = _first(fund, *keys, default=None)
    if value is not None:
        return value
    return _first(_fund_extra(fund), *keys, default=default)


def _requirement_field(fund: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    requirements = fund.get("requirements", {})
    if isinstance(requirements, Mapping):
        value = _first(requirements, *keys, default=None)
        if value is not None:
            return value
    extra = _fund_extra(fund)
    for container_key in ("requirements_data", "requirements"):
        detailed = extra.get(container_key, {})
        if isinstance(detailed, Mapping):
            value = _first(detailed, *keys, default=None)
            if value is not None:
                return value
    return _fund_field(fund, *keys, default=default)


def _amount_range(fund: Mapping[str, Any]) -> tuple[float | None, float | None]:
    raw = _fund_field(fund, "amount", "grant_amount", default={})
    if isinstance(raw, Mapping):
        minimum = _money(_first(raw, "min", "minimum", "from", "lower", default=None))
        maximum = _money(_first(raw, "max", "maximum", "to", "upper", default=None))
        if minimum is None and maximum is None:
            maximum = _money(raw)
        return minimum, maximum
    if isinstance(raw, str):
        number_matches = list(re.finditer(r"\d[\d., ]*", raw))
        unit_matches = list(re.finditer(r"\b(mio|million(?:er)?|tkr|tusind)\.?\b", raw, re.IGNORECASE))
        global_unit = unit_matches[0].group(1) if len(unit_matches) == 1 else ""
        numbers: list[float | None] = []
        for index, number_match in enumerate(number_matches):
            next_number_start = (
                number_matches[index + 1].start() if index + 1 < len(number_matches) else len(raw)
            )
            local_unit = next(
                (
                    unit.group(1)
                    for unit in unit_matches
                    if number_match.end() <= unit.start() < next_number_start
                ),
                global_unit,
            )
            numbers.append(_money(number_match.group(0) + (f" {local_unit}" if local_unit else "")))
        numbers = [number for number in numbers if number is not None]
        if len(numbers) >= 2:
            return min(numbers), max(numbers)
        if numbers:
            lower_text = _ascii_text(raw)
            if any(term in lower_text for term in ("op til", "maks", "max")):
                return None, numbers[0]
            if any(term in lower_text for term in ("fra", "mindst", "min")):
                return numbers[0], None
            return None, numbers[0]
    amount = _money(raw)
    return (None, amount) if amount is not None else (None, None)


def _deadline_info(fund: Mapping[str, Any]) -> tuple[str, date | None]:
    raw = _fund_field(fund, "deadline", "application_deadline", default=None)
    if isinstance(raw, Mapping):
        status = _ascii_text(_first(raw, "status", "type", default=""))
        if status in _ROLLING_TERMS or any(term in status for term in _ROLLING_TERMS):
            return "rolling", None
        if status in _CLOSED_TERMS or any(term in status for term in _CLOSED_TERMS):
            return "closed", _parse_date(raw)
    text = _ascii_text(raw)
    if text and any(term in text for term in _ROLLING_TERMS):
        return "rolling", None
    if text and any(term in text for term in _CLOSED_TERMS):
        return "closed", _parse_date(raw)
    parsed = _parse_date(raw)
    return ("dated", parsed) if parsed else ("unknown", None)


def _documentation_score(fund: Mapping[str, Any], as_of: date) -> tuple[int, str]:
    checks = 0
    status = _ascii_text(_fund_field(fund, "verification_status", default=""))
    if status == "verified":
        checks += 1
    url = _fund_field(fund, "official_url", "url", "website", default="")
    if re.match(r"^https?://", str(url).strip(), re.IGNORECASE):
        checks += 1
    checked = _parse_date(_fund_field(fund, "last_checked", "last_verified_at", "checked_at", default=None))
    if checked and 0 <= (as_of - checked).days <= 365:
        checks += 1
    requirements = _fund_field(fund, "requirements", default=None)
    if requirements:
        checks += 1
    earned = round(MATCH_WEIGHTS["documentation"] * checks / 4)
    return earned, f"{checks} af 4 dokumentationskriterier er opfyldt"


def _history_is_prior(history: Any) -> bool:
    if isinstance(history, bool):
        return history
    if history in (None, "", [], {}):
        return False
    if isinstance(history, Mapping):
        if "has_prior_application" in history:
            return bool(history["has_prior_application"])
        status = _ascii_text(_first(history, "status", "submission_status", default=""))
        return status not in {"", "draft", "cancelled", "annulleret"}
    if isinstance(history, Sequence) and not isinstance(history, (str, bytes)):
        return any(_history_is_prior(item) for item in history)
    return bool(history)


def _history_context(history: Any) -> dict[str, Any]:
    if isinstance(history, Mapping):
        has_explicit_flags = any(
            key in history
            for key in ("has_prior_application", "has_any_prior_application", "has_unknown_project_history")
        )
        fallback_prior = _history_is_prior(history) if not has_explicit_flags else False
        return {
            "same_project": bool(history.get("has_prior_application")) or fallback_prior,
            "any_project": bool(
                history.get("has_any_prior_application")
                or history.get("has_prior_application")
            ) or fallback_prior,
            "unknown_project": bool(history.get("has_unknown_project_history")),
            "count": int(history.get("count", 0) or 0),
        }
    prior = _history_is_prior(history)
    return {"same_project": prior, "any_project": prior, "unknown_project": False, "count": int(prior)}


def score_fund(
    project: Mapping[str, Any],
    fund: Mapping[str, Any],
    *,
    as_of: date | datetime | str | None = None,
    history: Any = None,
) -> dict[str, Any]:
    """Beregn reproducerbar 0–100-score og separate hårde stopkriterier."""

    project_report = validate_project(project, stage="matching", as_of=as_of, raise_on_error=True)
    normalised = project_report["project"]
    if not isinstance(fund, Mapping):
        raise TypeError("fund skal være et objekt")
    reference_date = _as_of_date(as_of)
    blockers: list[str] = []
    blocker_details: list[dict[str, str]] = []

    def block(code: str, message: str) -> None:
        if code not in blockers:
            blockers.append(code)
            blocker_details.append({"code": code, "message": message})

    status = " ".join(
        filter(
            None,
            (
                _ascii_text(_fund_field(fund, "status", default="")),
                _ascii_text(_fund_field(fund, "verification_status", default="")),
            ),
        )
    )
    if status and any(term in status for term in _CLOSED_TERMS):
        block("fund_closed", "Fonden eller puljen er markeret som lukket/inaktiv")
    researched_decision = _ascii_text(_requirement_field(fund, "go_no_go", default=""))
    if researched_decision in {"no go", "no_go", "nogo"}:
        block("official_no_go", "Den seneste officielle kravresearch konkluderer no-go")

    fund_type = _ascii_text(_fund_field(fund, "type", "fund_type", default=""))
    is_directory_record = any(
        term in fund_type
        for term in ("directory", "database", "katalog", "portal", "register", "oversigt")
    )
    represents_program = bool(
        _fund_field(
            fund,
            "is_specific_program",
            "specific_program",
            "represents_program",
            "program_id",
            default=False,
        )
    )
    if is_directory_record and not represents_program:
        block(
            "directory_not_program",
            "Posten er et katalog/en portal og ikke en konkret støtteordning",
        )

    applicant_types = _fund_field(fund, "applicant_types", "eligible_applicants", default=[])
    applicant_type = normalised["applicant"]["type"]
    if applicant_types and applicant_type and not _overlaps([applicant_type], applicant_types):
        block("applicant_type_mismatch", "Ansøgertypen er ikke blandt de støtteberettigede")

    fund_geography = _fund_field(fund, "geography", "area", "eligible_geography", default=[])
    geography_text = {_ascii_text(item) for item in _text_list(fund_geography)}
    is_national = any(
        term == item or term in item for item in geography_text for term in _NATIONAL_TERMS
    )
    if is_national:
        geography_ratio = 1.0
        geography_reason = "Landsdækkende mulighed"
    elif not geography_text:
        geography_ratio = 0.0
        geography_reason = "Geografisk afgrænsning er ikke registreret"
    elif _overlaps(normalised["geography"], fund_geography):
        geography_ratio = 1.0
        geography_reason = "Projektets geografi matcher fondens område"
    else:
        geography_ratio = 0.0
        geography_reason = "Projektets geografi ligger uden for fondens registrerede område"
        block("geography_mismatch", geography_reason)

    fund_purposes = _fund_field(fund, "purposes", "purpose", default=[])
    purpose_ratio = _similarity(normalised["purposes"], fund_purposes)
    fund_targets = _fund_field(fund, "target_groups", "beneficiaries", default=[])
    target_ratio = _similarity(normalised["target_groups"], fund_targets)

    eligible_expenses = _requirement_field(
        fund, "eligible_expenses", "supported_expenses", "costs", default=[]
    )
    excluded_expenses = _requirement_field(
        fund, "ineligible_expenses", "excluded_expenses", default=[]
    )
    expense_ratio = _similarity(normalised["expenses"], eligible_expenses)
    if _overlaps(normalised["expenses"], excluded_expenses):
        block("ineligible_expense", "Projektbudgettet indeholder en udtrykkeligt ikke-støtteberettiget udgift")
    if eligible_expenses and not _overlaps(normalised["expenses"], eligible_expenses):
        block("expense_mismatch", "Ingen projektudgift matcher fondens støtteberettigede udgifter")

    exclusions = _fund_field(fund, "exclusions", default=[])
    project_topics = (
        normalised["purposes"]
        + normalised["target_groups"]
        + normalised["activities"]
        + normalised["expenses"]
    )
    if exclusions and _overlaps(project_topics, exclusions):
        block("excluded_project", "Projektet rammer en registreret udelukkelsesregel")

    requested = float(normalised["requested_amount"])
    minimum, maximum = _amount_range(fund)
    if minimum is None and maximum is None:
        amount_ratio = 0.0
        amount_reason = "Beløbsgrænser er ikke registreret"
    elif minimum is not None and requested < minimum:
        amount_ratio = 0.0
        amount_reason = f"Ansøgt beløb er under minimum på {minimum:g} DKK"
        block("amount_below_minimum", amount_reason)
    elif maximum is not None and requested > maximum:
        amount_ratio = 0.0
        amount_reason = f"Ansøgt beløb overstiger maksimum på {maximum:g} DKK"
        block("amount_above_maximum", amount_reason)
    else:
        amount_ratio = 1.0
        amount_reason = "Ansøgt beløb ligger inden for fondens grænser"

    deadline_status, deadline = _deadline_info(fund)
    if deadline_status == "closed":
        deadline_ratio = 0.0
        deadline_reason = "Ansøgningsrunden er lukket"
        block("deadline_closed", deadline_reason)
    elif deadline_status == "rolling":
        deadline_ratio = 1.0
        deadline_reason = "Løbende ansøgningsfrist"
    elif deadline is None:
        deadline_ratio = 0.0
        deadline_reason = "Ansøgningsfrist er ikke verificeret"
    else:
        days = (deadline - reference_date).days
        if days < 0:
            deadline_ratio = 0.0
            deadline_reason = f"Ansøgningsfristen {deadline.isoformat()} er passeret"
            block("deadline_passed", deadline_reason)
        elif days >= 30:
            deadline_ratio = 1.0
            deadline_reason = f"{days} dage til fristen"
        elif days >= 14:
            deadline_ratio = 0.8
            deadline_reason = f"{days} dage til fristen"
        elif days >= 7:
            deadline_ratio = 0.5
            deadline_reason = f"Kun {days} dage til fristen"
        elif days >= 1:
            deadline_ratio = 0.2
            deadline_reason = f"Kun {days} dage til fristen"
        else:
            deadline_ratio = 0.1
            deadline_reason = "Fristen er i dag"

    history_context = _history_context(history)
    if history_context["same_project"]:
        allow_repeat = bool(_fund_field(fund, "allow_repeat_application", default=False))
        if not allow_repeat:
            block("prior_application", "Der er allerede registreret en ansøgning til fonden for projektet")

    documentation_earned, documentation_reason = _documentation_score(fund, reference_date)
    ratios_and_reasons = {
        "geography": (geography_ratio, geography_reason),
        "purpose": (purpose_ratio, "Leksikalsk overlap mellem projekt- og fondsformål"),
        "target_groups": (target_ratio, "Leksikalsk overlap mellem målgrupper"),
        "expenses": (expense_ratio, "Leksikalsk overlap mellem udgiftskategorier"),
        "amount": (amount_ratio, amount_reason),
        "deadline": (deadline_ratio, deadline_reason),
    }
    breakdown: dict[str, dict[str, Any]] = {}
    total = 0
    for category, (ratio, reason) in ratios_and_reasons.items():
        maximum_score = MATCH_WEIGHTS[category]
        earned = round(maximum_score * max(0.0, min(1.0, ratio)))
        breakdown[category] = {"earned": earned, "maximum": maximum_score, "reason": reason}
        total += earned
    breakdown["documentation"] = {
        "earned": documentation_earned,
        "maximum": MATCH_WEIGHTS["documentation"],
        "reason": documentation_reason,
    }
    total += documentation_earned
    total = max(0, min(100, int(total)))

    fund_id = _first(fund, "fund_id", "id", "canonical_key", default=None)
    fund_name = str(_first(fund, "name", "fund_name", default=fund_id or "Ukendt fond"))
    decision = "no_go" if blockers else "go"
    return {
        "fund_id": fund_id,
        "fund_name": fund_name,
        "score": total,
        "weights": dict(MATCH_WEIGHTS),
        "breakdown": breakdown,
        "hard_blockers": blockers,
        "blocker_details": blocker_details,
        "eligible": not blockers,
        "go_no_go": decision,
        "history_context": history_context,
        "history_warning": (
            "Fonden er tidligere søgt for et andet eller ukendt projekt; kontrollér genansøgningsregler og historik."
            if history_context["any_project"] and not history_context["same_project"]
            else ""
        ),
        "evaluated_at": reference_date.isoformat(),
    }


def calculate_match_score(
    project: Mapping[str, Any],
    fund: Mapping[str, Any],
    *,
    as_of: date | datetime | str | None = None,
    history: Any = None,
) -> dict[str, Any]:
    """Bagud-/CLI-venligt alias for :func:`score_fund`."""

    return score_fund(project, fund, as_of=as_of, history=history)


def _call_list_funds(store: Any) -> list[Mapping[str, Any]]:
    method = getattr(store, "list_funds", None)
    if not callable(method):
        raise TypeError("IndexStore skal have en list_funds()-metode")
    try:
        result = method()
    except TypeError:
        # Nogle stores har et obligatorisk limit-argument. Et stort, eksplicit
        # loft bevarer den deterministiske sortering uden at kende databasen.
        result = method(limit=100_000)
    return [fund for fund in (result or []) if isinstance(fund, Mapping)]


def _call_get_fund(store: Any, fund_id: Any) -> Mapping[str, Any] | None:
    method = getattr(store, "get_fund", None)
    if not callable(method):
        raise TypeError("IndexStore skal have en get_fund(id)-metode")
    result = method(fund_id)
    return result if isinstance(result, Mapping) else None


def lookup_history(store: Any, project_id: str, fund: Mapping[str, Any]) -> Any:
    """Slå tidligere ansøgninger op på tværs af små IndexStore-varianter."""

    fund_id = _first(fund, "fund_id", "id", "canonical_key", default=None)
    for method_name in ("list_sent_applications", "list_history"):
        method = getattr(store, method_name, None)
        if not callable(method):
            continue
        try:
            records = method(fund_id=fund_id) or []
        except TypeError:
            continue
        exact = [
            record
            for record in records
            if isinstance(record, Mapping) and str(record.get("project_id", "")) == str(project_id)
        ]
        unknown = [
            record
            for record in records
            if isinstance(record, Mapping) and not str(record.get("project_id", "")).strip()
        ]
        return {
            "has_prior_application": bool(exact),
            "has_any_prior_application": bool(records),
            "has_unknown_project_history": bool(unknown),
            "count": len(records),
            "records": records,
        }
    for method_name in ("has_prior_application", "get_history", "history"):
        method = getattr(store, method_name, None)
        if not callable(method):
            continue
        if method_name == "has_prior_application":
            try:
                parameter_names = [
                    parameter.name
                    for parameter in inspect.signature(method).parameters.values()
                    if parameter.name not in {"self", "cls"}
                ]
            except (TypeError, ValueError):
                parameter_names = []
            if {"fund_id", "project_id"}.issubset(parameter_names):
                return method(fund_id=fund_id, project_id=project_id)
            if parameter_names and parameter_names[0] in {
                "name",
                "fund_name",
                "fond",
                "url_or_domain",
            }:
                return method(
                    _first(fund, "name", "fund_name", default=fund_id),
                    _first(fund, "official_url", "url", "domain", default=""),
                )
        attempts = (
            lambda: method(project_id=project_id, fund_id=fund_id),
            lambda: method(fund_id=fund_id, project_id=project_id),
            lambda: method(project_id, fund_id),
            lambda: method(fund_id, project_id),
        )
        for attempt in attempts:
            try:
                return attempt()
            except TypeError:
                continue
    return None


def match_funds(
    store: Any,
    project: Mapping[str, Any],
    *,
    fund_ids: Sequence[Any] | None = None,
    limit: int | None = None,
    as_of: date | datetime | str | None = None,
    include_blocked: bool = True,
) -> list[dict[str, Any]]:
    """Match et projekt mod et duck-typed IndexStore og sorter stabilt."""

    report = validate_project(project, stage="matching", as_of=as_of, raise_on_error=True)
    normalised = report["project"]
    if limit is not None and (isinstance(limit, bool) or limit < 1):
        raise ValueError("limit skal være et positivt heltal")
    if fund_ids is None:
        funds = _call_list_funds(store)
    else:
        funds = []
        for fund_id in fund_ids:
            fund = _call_get_fund(store, fund_id)
            if fund is None:
                raise KeyError(f"Fonden findes ikke i indekset: {fund_id}")
            funds.append(fund)

    results: list[dict[str, Any]] = []
    for fund in funds:
        history = lookup_history(store, normalised["project_id"], fund)
        result = score_fund(normalised, fund, as_of=as_of, history=history)
        if include_blocked or result["eligible"]:
            results.append(result)
    results.sort(
        key=lambda result: (
            not bool(result["eligible"]),
            -int(result["score"]),
            _ascii_text(result["fund_name"]),
            str(result.get("fund_id") or ""),
        )
    )
    return results[:limit] if limit is not None else results


def get_fund_record(store: Any, fund_id: Any) -> Mapping[str, Any]:
    """Offentlig, lille adapter som batch-workflowet kan genbruge."""

    fund = _call_get_fund(store, fund_id)
    if fund is None:
        raise KeyError(f"Fonden findes ikke i indekset: {fund_id}")
    return fund


__all__ = [
    "MATCH_WEIGHTS",
    "ProjectValidationError",
    "calculate_match_score",
    "get_fund_record",
    "lookup_history",
    "match_funds",
    "score_fund",
    "validate_project",
]
