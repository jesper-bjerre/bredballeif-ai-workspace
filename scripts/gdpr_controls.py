"""Fail-closed GDPR controls shared by Bredballe IF skills.

The module has no network access and no third-party dependencies.  It is a
policy building block for skills and the OpenClaw gateway; it does not make a
provider or deployment compliant on its own.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_MAX_RECORDS = 10
MAX_APPROVAL_AGE = timedelta(minutes=15)
REDACTED = "[REDACTED]"


class PolicyViolation(RuntimeError):
    """Raised when an operation violates a fail-closed policy."""


class DataClassification(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    PERSONAL = "PERSONAL"
    SENSITIVE = "SENSITIVE"
    SECRET = "SECRET"


@dataclass(frozen=True)
class Provider:
    """A provider registration verified outside this repository."""

    name: str
    region: str
    approved: bool = False
    zero_retention_verified: bool = False
    dpa_verified: bool = False

    @property
    def is_eu(self) -> bool:
        normalized = self.region.strip().upper().replace("_", "-")
        return normalized in {"EU", "EEA", "EU/EEA", "EU-EØS", "EØS"} or normalized.startswith("EU-")


@dataclass(frozen=True)
class SkillPolicy:
    """Policy for den aktuelle tool-invocation og dens faktiske payload.

    ``data_classifications`` må ikke være unionen af alt, en skill potentielt kan
    behandle; gatewayen skal klassificere den konkrete invocation fail-closed.
    """

    name: str
    data_classifications: tuple[DataClassification, ...]
    allowed_regions: tuple[str, ...] = ("EU",)
    allow_non_eu_fallback: bool = False
    max_records: int = DEFAULT_MAX_RECORDS
    requires_human_approval_for_writes: bool = True
    allowed_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_records < 1:
            raise ValueError("max_records must be at least 1")


def validate_provider_route(
    policy: SkillPolicy,
    primary: str,
    fallbacks: Sequence[str],
    registry: Mapping[str, Provider],
) -> tuple[Provider, ...]:
    """Validate the entire provider route before any model call.

    Unknown providers and every disallowed fallback are rejected up front.  A
    PERSONAL route requires an approved EU/EEA provider with verified DPA and
    zero-retention settings.  SECRET is never accepted, and SENSITIVE is local
    only in the current architecture.
    """

    classes = set(policy.data_classifications)
    if DataClassification.SECRET in classes:
        raise PolicyViolation("SECRET-data må aldrig sendes til en LLM.")
    if DataClassification.SENSITIVE in classes:
        raise PolicyViolation("SENSITIVE-data er blokeret for eksterne LLM-kald.")

    route_names = [primary, *fallbacks]
    if not primary.strip():
        raise PolicyViolation("Primær provider mangler; der fejles lukket.")

    allowed_regions = {
        region.strip().upper().replace("_", "-")
        for region in policy.allowed_regions
        if region.strip()
    }
    if not allowed_regions:
        raise PolicyViolation("Policy mangler allowed_regions; der fejles lukket.")

    route: list[Provider] = []
    for index, name in enumerate(route_names):
        provider = registry.get(name)
        if provider is None:
            raise PolicyViolation(f"Ukendt provider i route: {name!r}.")
        if not provider.approved:
            raise PolicyViolation(f"Provider er ikke organisatorisk godkendt: {name!r}.")

        provider_region = provider.region.strip().upper().replace("_", "-")
        eu_family_allowed = provider.is_eu and bool(
            allowed_regions & {"EU", "EEA", "EU/EEA", "EU-EØS", "EØS"}
        )
        if provider_region not in allowed_regions and not eu_family_allowed:
            raise PolicyViolation(
                f"Providerregion er ikke tilladt for denne invocation: {provider_region!r}."
            )

        if DataClassification.PERSONAL in classes:
            if not provider.is_eu:
                raise PolicyViolation(f"PERSONAL-data kræver EU/EØS-provider: {name!r}.")
            if not provider.dpa_verified or not provider.zero_retention_verified:
                raise PolicyViolation(
                    f"PERSONAL-provider mangler verificeret DPA eller zero-retention: {name!r}."
                )
        elif index > 0 and not policy.allow_non_eu_fallback and not provider.is_eu:
            raise PolicyViolation(f"Ikke-EU-fallback er deaktiveret: {name!r}.")

        route.append(provider)
    return tuple(route)


_SECRET_KEYS = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|client[_-]?secret|cookie|password|private[_-]?key|refresh[_-]?token|secret|session|token|webhook[_-]?secret)"
)
_PERSONAL_KEYS = re.compile(
    r"(?i)^(adresse|address|birth|by|city|cpr|email|foedselsdato|fødselsdato|member|medlem|mobil|name|navn|phone|postnr|telefon)$"
)
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_AUTHORIZATION = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
_CPR = re.compile(r"(?<!\d)\d{6}[- ]?\d{4}(?!\d)")
_PHONE = re.compile(r"(?<!\d)(?:\+45[ -]?)?(?:\d[ -]?){8}(?!\d)")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|client[_-]?secret|password|refresh[_-]?token|secret|token)\s*[:=]\s*([^\s,;]+)"
)


def redact_text(value: str) -> str:
    """Redact common secrets and direct identifiers from free text."""

    result = _AUTHORIZATION.sub(lambda m: f"{m.group(1)} {REDACTED}", value)
    result = _SECRET_ASSIGNMENT.sub(lambda m: f"{m.group(1)}={REDACTED}", result)
    result = _EMAIL.sub("[REDACTED_EMAIL]", result)
    result = _CPR.sub("[REDACTED_CPR]", result)
    result = _PHONE.sub("[REDACTED_PHONE]", result)
    return result


def redact_sensitive_data(value: Any, *, redact_personal: bool = True) -> Any:
    """Return a recursively redacted copy suitable for operational logs."""

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _SECRET_KEYS.search(key_text):
                result[key_text] = REDACTED
            elif redact_personal and _PERSONAL_KEYS.search(key_text):
                result[key_text] = "[REDACTED_PERSONAL]"
            else:
                result[key_text] = redact_sensitive_data(item, redact_personal=redact_personal)
        return result
    if isinstance(value, (list, tuple, set)):
        return [redact_sensitive_data(item, redact_personal=redact_personal) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


_MEMBER_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "member_id": ("member_id", "id", "medlemsnr"),
    "first_name": ("first_name", "fornavn"),
    "membership_status": ("membership_status", "medlemsstatus", "status"),
    "department": ("department", "afdeling"),
    "groups": ("groups", "grupper"),
}


def minimize_member(member: Mapping[str, Any], allowed_fields: Iterable[str]) -> dict[str, Any]:
    """Project a member object onto an explicit semantic allowlist."""

    result: dict[str, Any] = {}
    for field_name in allowed_fields:
        aliases = _MEMBER_FIELD_ALIASES.get(field_name)
        if aliases is None:
            raise PolicyViolation(f"Ukendt medlem-field i allowlist: {field_name!r}.")
        for alias in aliases:
            if alias in member:
                result[field_name] = member[alias]
                break
    return result


def enforce_record_limit(
    records: Sequence[Any],
    *,
    limit: int = DEFAULT_MAX_RECORDS,
    bulk_approved: bool = False,
) -> list[Any]:
    """Reject broad result sets unless a separate bulk approval is present."""

    if limit < 1:
        raise PolicyViolation("Resultatgrænsen skal være mindst 1.")
    if limit > DEFAULT_MAX_RECORDS and not bulk_approved:
        raise PolicyViolation(
            f"En resultatgrænse over {DEFAULT_MAX_RECORDS} kræver særskilt massegodkendelse."
        )
    if len(records) > limit and not bulk_approved:
        raise PolicyViolation(
            f"Forespørgslen gav {len(records)} poster; maksimum er {limit} uden særskilt massegodkendelse."
        )
    return list(records[:limit])


def reject_broad_query(query: str, *, minimum_length: int = 3) -> str:
    normalized = " ".join(query.split())
    if len(normalized) < minimum_length or normalized in {"*", "%", "alle", "all"}:
        raise PolicyViolation("Tom eller for bred søgning er afvist.")
    return normalized


def assert_model_payload_allowed(classification: DataClassification, payload: Any) -> None:
    """Block classes and secret-shaped keys before an external model call."""

    if classification is DataClassification.SECRET:
        raise PolicyViolation("SECRET-data må aldrig sendes til en LLM.")
    if classification is DataClassification.SENSITIVE:
        raise PolicyViolation("SENSITIVE-data er blokeret for eksterne LLM-kald.")

    def walk(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if _SECRET_KEYS.search(str(key)):
                    raise PolicyViolation(f"Payload indeholder et SECRET-felt: {key!r}.")
                walk(child)
        elif isinstance(item, (list, tuple, set)):
            for child in item:
                walk(child)
        elif isinstance(item, str) and (_AUTHORIZATION.search(item) or _SECRET_ASSIGNMENT.search(item)):
            raise PolicyViolation("Payload indeholder et muligt secret i fritekst.")

    walk(payload)


@dataclass(frozen=True)
class ApprovalContext:
    actions: frozenset[str]
    actor_role: str
    correlation_id: str
    expires_at: datetime
    approved: bool

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> "ApprovalContext":
        source = os.environ if env is None else env
        actions = frozenset(a.strip() for a in source.get("BIF_APPROVAL_ACTIONS", "").split(",") if a.strip())
        actor_role = source.get("BIF_APPROVAL_ACTOR_ROLE", "").strip()
        correlation_id = source.get("BIF_APPROVAL_CORRELATION_ID", "").strip()
        raw_expiry = source.get("BIF_APPROVAL_EXPIRES_AT", "").strip()
        approved = hmac.compare_digest(source.get("BIF_APPROVAL_GRANTED", "").strip().lower(), "true")
        try:
            expires_at = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        except ValueError:
            expires_at = datetime.fromtimestamp(0, tz=timezone.utc)
        return cls(actions, actor_role, correlation_id, expires_at, approved)

    def require(self, action: str, *, now: datetime | None = None) -> None:
        checked_at = now or datetime.now(timezone.utc)
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        remaining = self.expires_at.astimezone(timezone.utc) - checked_at.astimezone(timezone.utc)
        if not self.approved:
            raise PolicyViolation("Write-operationen mangler eksplicit menneskelig godkendelse.")
        if action not in self.actions:
            raise PolicyViolation(f"Godkendelsen omfatter ikke handlingen {action!r}.")
        if not self.actor_role or not self.correlation_id:
            raise PolicyViolation("Godkendelsen mangler actor role eller correlation ID.")
        if remaining <= timedelta(0) or remaining > MAX_APPROVAL_AGE:
            raise PolicyViolation("Godkendelsen er udløbet eller har for lang gyldighed.")


def require_write_approval(action: str, env: Mapping[str, str] | None = None) -> ApprovalContext:
    context = ApprovalContext.from_environment(env)
    context.require(action)
    return context


def audit_event(
    event: str,
    status: str,
    *,
    record_count: int = 0,
    actor_role: str = "unknown",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Build a structured audit event that deliberately excludes payload data."""

    return {
        "event": event,
        "status": status,
        "recordCount": max(0, int(record_count)),
        "actorRole": actor_role or "unknown",
        "correlationId": correlation_id or str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def emit_audit_event(event: Mapping[str, Any]) -> None:
    print(json.dumps(redact_sensitive_data(dict(event)), ensure_ascii=False, sort_keys=True), file=sys.stderr)


@dataclass(frozen=True)
class TestScope:
    allowed_member_ids: frozenset[str] = field(default_factory=frozenset)
    allowed_departments: frozenset[str] = field(default_factory=frozenset)

    def require_member(self, member_id: str) -> None:
        if member_id not in self.allowed_member_ids:
            raise PolicyViolation("Testopslag er uden for allowed_member_ids.")

    def require_department(self, department: str) -> None:
        if department not in self.allowed_departments:
            raise PolicyViolation("Testopslag er uden for allowed_departments.")


__all__ = [
    "ApprovalContext",
    "DEFAULT_MAX_RECORDS",
    "DataClassification",
    "PolicyViolation",
    "Provider",
    "SkillPolicy",
    "TestScope",
    "assert_model_payload_allowed",
    "audit_event",
    "emit_audit_event",
    "enforce_record_limit",
    "minimize_member",
    "redact_sensitive_data",
    "redact_text",
    "reject_broad_query",
    "require_write_approval",
    "validate_provider_route",
]
