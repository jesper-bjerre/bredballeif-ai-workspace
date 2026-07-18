"""Portable file-backed fund index and application history.

Each fund and history record is canonical JSON. Source observations use one
JSONL file per fund, while ``index.jsonl`` is a derived, rebuildable search
view. No database engine or non-standard dependency is required.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


SCHEMA_VERSION = 1
VERIFICATION_STATUSES = (
    "verified",
    "discovered_official",
    "directory_only",
    "candidate",
    "unverified",
    "needs_review",
    "temporary",
    "closed",
    "unknown",
)

_STATUS_RANK = {
    "unknown": 0,
    "candidate": 1,
    "unverified": 2,
    "directory_only": 2,
    "needs_review": 3,
    "discovered_official": 4,
    "temporary": 5,
    "closed": 5,
    "verified": 6,
}

_DANISH_TRANSLATION = str.maketrans(
    {"æ": "ae", "ø": "oe", "å": "aa", "Æ": "ae", "Ø": "oe", "Å": "aa"}
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def normalize_name(value: Any) -> str:
    """Return a stable comparison form for a fund or pool name."""

    text = _text(value).translate(_DANISH_TRANSLATION).casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("&", " og ")
    text = re.sub(r"[’'`]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def normalize_domain(value: Any) -> str:
    """Extract a lower-case host name from a URL or domain-like value."""

    raw = _text(value)
    if not raw:
        return ""
    match = re.search(r"https?://[^\s,;]+", raw, flags=re.IGNORECASE)
    candidate = match.group(0) if match else raw.split()[0]
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        host = urlsplit(candidate).hostname or ""
    except ValueError:
        return ""
    host = host.rstrip(".").casefold()
    if host.startswith("www."):
        host = host[4:]
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return host


def _reject_url_credentials(value: Any) -> None:
    raw = _text(value)
    if not raw:
        return
    for candidate in re.findall(r"https?://[^\s,;]+", raw, flags=re.IGNORECASE):
        try:
            parsed = urlsplit(candidate)
        except ValueError as exc:
            raise ValueError("URL-feltet indeholder en ugyldig URL") from exc
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("URL-felter må ikke indeholde brugernavn eller adgangskode")


def normalize_verification(value: Any) -> str:
    """Map Danish/English verification and lifecycle labels to canonical states."""

    if value is True:
        return "verified"
    if value is False:
        return "unverified"
    text = normalize_name(value)
    if not text:
        return "unknown"
    exact = {
        "verified": "verified",
        "discovered official": "discovered_official",
        "directory only": "directory_only",
        "candidate": "candidate",
        "unverified": "unverified",
        "needs review": "needs_review",
        "temporary": "temporary",
        "closed": "closed",
        "unknown": "unknown",
    }
    if text in exact:
        return exact[text]
    if any(token in text for token in ("lukket", "udloebet", "ophoert", "inaktiv", "closed")):
        return "closed"
    if any(token in text for token in ("midlertidig", "tidsbegraenset", "temporary")):
        return "temporary"
    if any(token in text for token in ("discovered official", "officiel kilde fundet")):
        return "discovered_official"
    if any(token in text for token in ("directory only", "kun register", "kun katalog")):
        return "directory_only"
    if text in {"kandidat", "candidate"}:
        return "candidate"
    if any(
        token in text
        for token in (
            "ikke verificeret",
            "ikke kontrolleret",
            "uverificeret",
            "unverified",
            "raadata",
            "raa data",
            "raw data",
        )
    ):
        return "unverified"
    if any(
        token in text
        for token in (
            "skal verificeres",
            "boer verificeres",
            "kontroller igen",
            "delvist verificeret",
            "foraeldet",
            "afventer",
        )
    ):
        return "needs_review"
    if any(token in text for token in ("verified", "verificeret", "kontrolleret", "godkendt", "bekraeftet")):
        return "verified"
    if text in {"nej", "no", "false", "0"}:
        return "unverified"
    if text in {"ja", "yes", "true", "1"}:
        return "verified"
    return "needs_review"


def canonical_fund_key(name: Any, url_or_domain: Any = "") -> str:
    normalized_name = normalize_name(name)
    if not normalized_name:
        raise ValueError("A fund name is required")
    return f"{normalized_name}|{normalize_domain(url_or_domain)}"


def _json_safe(value: Any, seen: set[int] | None = None) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat()
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if seen is None:
        seen = set()
    marker = id(value)
    if marker in seen:
        raise ValueError("Circular data cannot be serialized as JSON")
    if isinstance(value, Mapping):
        seen.add(marker)
        try:
            return {
                str(key): _json_safe(item, seen)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        finally:
            seen.remove(marker)
    if isinstance(value, (list, tuple)):
        seen.add(marker)
        try:
            return [_json_safe(item, seen) for item in value]
        finally:
            seen.remove(marker)
    if isinstance(value, (set, frozenset)):
        seen.add(marker)
        try:
            normalized = [_json_safe(item, seen) for item in value]
            return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
        finally:
            seen.remove(marker)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def safe_json_dumps(value: Any, *, pretty: bool = False) -> str:
    options: dict[str, Any] = {
        "ensure_ascii": False,
        "allow_nan": False,
        "sort_keys": True,
    }
    if pretty:
        options.update({"indent": 2})
    else:
        options.update({"separators": (",", ":")})
    return json.dumps(_json_safe(value), **options)


def safe_json_loads(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _pick(record: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in record and record[name] not in (None, ""):
            return record[name]
    return None


def _record_fingerprint(parts: Mapping[str, Any]) -> str:
    return hashlib.sha256(safe_json_dumps(parts).encode("utf-8")).hexdigest()


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _storage_value(value: Any) -> Any:
    if value is None:
        return ""
    return _json_safe(value)


def _merge_categorical(existing: Any, incoming: Any) -> Any:
    def items(value: Any) -> list[Any]:
        if value in (None, ""):
            return []
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return list(value)
        return [value]

    result: list[Any] = []
    seen: set[str] = set()
    for item in items(existing) + items(incoming):
        key = normalize_name(item) if isinstance(item, str) else safe_json_dumps(item)
        if key and key not in seen:
            seen.add(key)
            result.append(deepcopy(item))
    if not result:
        return ""
    return result[0] if len(result) == 1 else result


def _atomic_write_text(path: Path, content: str) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError(f"Afviser at overskrive et symlink: {path}")
    parent_existed = path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix" and not parent_existed:
        os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, path)
        if os.name == "posix":
            os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write_text(path, safe_json_dumps(payload, pretty=True) + "\n")


class JsonFundStore:
    """Canonical fund index backed only by JSON and JSONL files."""

    def __init__(self, root: str | Path):
        self.memory = str(root) == ":memory:"
        unresolved_root = None if self.memory else Path(root).expanduser()
        if unresolved_root is not None and unresolved_root.is_symlink():
            raise ValueError(f"JSON-lageret må ikke være et symlink: {unresolved_root}")
        self.root = None if unresolved_root is None else unresolved_root.resolve()
        self.funds_dir = None if self.memory else self.root / "funds"
        self.observations_dir = None if self.memory else self.root / "observations"
        self.history_dir = None if self.memory else self.root / "history"
        self.index_path = None if self.memory else self.root / "index.jsonl"
        self.meta_path = None if self.memory else self.root / "meta.json"
        self._funds: dict[int, dict[str, Any]] = {}
        self._observations: dict[int, list[dict[str, Any]]] = {}
        self._history: dict[int, dict[str, Any]] = {}
        self._observation_fingerprints: set[str] = set()
        self._history_fingerprints: dict[str, int] = {}
        self._next_fund_id = 1
        self._next_history_id = 1
        self._index_dirty = False
        self._meta_dirty = False
        self.initialize()

    def __enter__(self) -> "JsonFundStore":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def initialize(self) -> "JsonFundStore":
        if self.memory:
            return self
        assert self.root and self.funds_dir and self.observations_dir and self.history_dir
        if self.root.exists() and self.root.is_symlink():
            raise ValueError(f"JSON-lageret må ikke være et symlink: {self.root}")
        root_existed = self.root.exists()
        self.root.mkdir(parents=True, exist_ok=True)
        for directory in (self.funds_dir, self.observations_dir, self.history_dir):
            if directory.exists() and directory.is_symlink():
                raise ValueError(f"JSON-lagermappen må ikke være et symlink: {directory}")
            directory.mkdir(exist_ok=True)
        if os.name == "posix":
            if not root_existed:
                os.chmod(self.root, 0o700)
            for directory in (self.funds_dir, self.observations_dir, self.history_dir):
                os.chmod(directory, 0o700)
        self._load_files()
        if self.meta_path is not None and not self.meta_path.exists():
            self._meta_dirty = True
            self._write_meta()
        if self.index_path is not None and not self.index_path.exists():
            self.rebuild_index()
        return self

    def close(self) -> None:
        if not self.memory:
            if self._index_dirty:
                self.rebuild_index()
            if self._meta_dirty:
                self._write_meta()

    def _load_json_object(self, path: Path) -> dict[str, Any]:
        if path.is_symlink():
            raise ValueError(f"Afviser at læse JSON gennem et symlink: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Ugyldig JSON-fil i fondslageret: {path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"JSON-roden skal være et objekt: {path}")
        return payload

    def _load_files(self) -> None:
        assert self.funds_dir and self.observations_dir and self.history_dir
        keys: set[str] = set()
        for path in sorted(self.funds_dir.glob("*.json")):
            fund = self._load_json_object(path)
            if fund.get("schema_version") != SCHEMA_VERSION:
                raise ValueError(f"Ukendt fund-schema i {path}")
            fund_id = int(fund.get("fund_id"))
            key = str(fund.get("canonical_key", ""))
            if fund_id in self._funds or not key or key in keys:
                raise ValueError(f"Dubleret eller ugyldig fondsidentitet i {path}")
            self._funds[fund_id] = fund
            keys.add(key)
        for path in sorted(self.observations_dir.glob("*.jsonl")):
            if path.is_symlink():
                raise ValueError(f"Afviser at læse JSONL gennem et symlink: {path}")
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    observation = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Ugyldig JSONL i {path}:{line_number}") from exc
                if not isinstance(observation, dict):
                    raise ValueError(f"Observationen skal være et objekt i {path}:{line_number}")
                fund_id = int(observation.get("fund_id"))
                if fund_id not in self._funds:
                    raise ValueError(f"Observation peger på ukendt fund_id i {path}:{line_number}")
                fingerprint = str(observation.get("fingerprint", ""))
                if not fingerprint or fingerprint in self._observation_fingerprints:
                    raise ValueError(f"Dubleret eller ugyldig observation i {path}:{line_number}")
                self._observations.setdefault(fund_id, []).append(observation)
                self._observation_fingerprints.add(fingerprint)
        for path in sorted(self.history_dir.glob("*.json")):
            item = self._load_json_object(path)
            if item.get("schema_version") != SCHEMA_VERSION:
                raise ValueError(f"Ukendt historik-schema i {path}")
            history_id = int(item.get("history_id"))
            fingerprint = str(item.get("fingerprint", ""))
            if history_id in self._history or not fingerprint or fingerprint in self._history_fingerprints:
                raise ValueError(f"Dubleret eller ugyldig historikidentitet i {path}")
            self._history[history_id] = item
            self._history_fingerprints[fingerprint] = history_id
        self._next_fund_id = max(self._funds, default=0) + 1
        self._next_history_id = max(self._history, default=0) + 1

    def _write_meta(self) -> None:
        if self.memory:
            return
        assert self.meta_path
        _atomic_write_json(
            self.meta_path,
            {
                "schema_version": SCHEMA_VERSION,
                "storage": "json-files",
                "next_fund_id": self._next_fund_id,
                "next_history_id": self._next_history_id,
                "updated_at": _utc_now(),
            },
        )
        self._meta_dirty = False

    def _fund_path(self, fund_id: int) -> Path:
        assert self.funds_dir
        return self.funds_dir / f"{int(fund_id):06d}.json"

    def _observation_path(self, fund_id: int) -> Path:
        assert self.observations_dir
        return self.observations_dir / f"{int(fund_id):06d}.jsonl"

    def _history_path(self, history_id: int) -> Path:
        assert self.history_dir
        return self.history_dir / f"{int(history_id):06d}.json"

    def _persist_fund(self, fund: Mapping[str, Any]) -> None:
        if not self.memory:
            _atomic_write_json(self._fund_path(int(fund["fund_id"])), fund)
        self._index_dirty = True

    def _persist_observations(self, fund_id: int) -> None:
        if self.memory:
            return
        content = "".join(safe_json_dumps(item) + "\n" for item in self._observations.get(fund_id, []))
        _atomic_write_text(self._observation_path(fund_id), content)

    def _persist_history(self, item: Mapping[str, Any]) -> None:
        if not self.memory:
            _atomic_write_json(self._history_path(int(item["history_id"])), item)

    @staticmethod
    def _canonical_record(record: Mapping[str, Any]) -> dict[str, Any]:
        name = _text(_pick(record, "name", "fund_name", "fond", "fond_name", "pool_name"))
        if not name:
            raise ValueError("Fund record is missing a name")
        url = _text(_pick(record, "url", "official_url", "website"))
        _reject_url_credentials(url)
        domain = normalize_domain(_pick(record, "domain") or url)
        normalized_name = normalize_name(name)
        extra = _pick(record, "extra", "metadata")
        if extra in (None, ""):
            extra = {}
        elif not isinstance(extra, Mapping):
            extra = {"value": extra}
        else:
            extra = dict(extra)
        for key in (
            "provider",
            "directory_url",
            "last_seen_at",
            "target_groups",
            "beneficiaries",
            "eligible_geography",
            "grant_amount",
            "application_deadline",
            "allow_repeat_application",
            "is_specific_program",
            "program_id",
            "official_source",
        ):
            if key in record and record[key] not in (None, "") and key not in extra:
                extra[key] = record[key]
        return {
            "canonical_key": f"{normalized_name}|{domain}",
            "normalized_name": normalized_name,
            "name": name,
            "domain": domain,
            "url": url,
            "official_url": url,
            "type": _text(_pick(record, "type", "fund_type", "category")),
            "geography": _storage_value(_pick(record, "geography", "geografi")),
            "area": _storage_value(_pick(record, "area", "municipality", "kommune")),
            "applicant_types": _storage_value(_pick(record, "applicant_types", "applicants", "who_can_apply")),
            "purposes": _storage_value(_pick(record, "purposes", "purpose", "typical_purpose")),
            "description": _text(_pick(record, "description", "short_description")),
            "amount": _storage_value(_pick(record, "amount", "amount_range", "funding_amount")),
            "deadline": _storage_value(_pick(record, "deadline", "deadline_frequency")),
            "requirements": _storage_value(_pick(record, "requirements", "important_requirements")),
            "exclusions": _storage_value(_pick(record, "exclusions", "important_exclusions")),
            "verification_status": normalize_verification(_pick(record, "verification_status", "verification", "status")),
            "last_checked": _text(_pick(record, "last_checked", "last_verified_at", "checked_at")),
            "last_verified_at": _text(_pick(record, "last_checked", "last_verified_at", "checked_at")),
            "status": normalize_verification(_pick(record, "verification_status", "verification", "status")),
            "relevance": _text(_pick(record, "relevance", "bif_relevance")),
            "notes": _text(_pick(record, "notes", "note")),
            "extra": _json_safe(extra),
        }

    def _find_existing(self, canonical: Mapping[str, Any]) -> dict[str, Any] | None:
        exact = next((fund for fund in self._funds.values() if fund["canonical_key"] == canonical["canonical_key"]), None)
        if exact is not None:
            return exact
        matches = [fund for fund in self._funds.values() if fund["normalized_name"] == canonical["normalized_name"]]
        if len(matches) == 1 and (not canonical["domain"] or not matches[0]["domain"]):
            return matches[0]
        return None

    @staticmethod
    def _merge_record(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> dict[str, Any]:
        merged = deepcopy(dict(existing))
        current_status = str(existing["verification_status"])
        incoming_status = str(incoming["verification_status"])
        current_rank = _STATUS_RANK[current_status]
        incoming_rank = _STATUS_RANK[incoming_status]
        incoming_date = str(incoming.get("last_checked", ""))
        current_date = str(existing.get("last_checked", ""))
        if incoming_status == "closed":
            closure_is_current = bool(incoming_date) and (not current_date or incoming_date >= current_date)
            chosen_status = "closed" if closure_is_current else current_status
        elif current_status == "closed":
            can_reopen = incoming_status == "verified" and bool(incoming_date) and (
                not current_date or incoming_date >= current_date
            )
            chosen_status = "verified" if can_reopen else "closed"
        else:
            chosen_status = incoming_status if incoming_rank > current_rank else current_status
        effective_incoming_rank = incoming_rank
        if current_status == "closed" and chosen_status == "closed":
            effective_incoming_rank = current_rank
        if incoming_status == "closed" and chosen_status != "closed":
            effective_incoming_rank = current_rank
        rejected_stale_closure = incoming_status == "closed" and chosen_status != "closed"
        same_status_refresh = (
            incoming_status == chosen_status
            and incoming_rank == current_rank
            and bool(incoming_date)
            and (not current_date or incoming_date >= current_date)
        )
        for field in (
            "name",
            "url",
            "official_url",
            "type",
            "geography",
            "area",
            "applicant_types",
            "purposes",
            "description",
            "amount",
            "deadline",
            "requirements",
            "exclusions",
            "relevance",
            "notes",
        ):
            candidate = incoming.get(field)
            if _present(candidate) and not rejected_stale_closure and (
                not _present(existing.get(field))
                or effective_incoming_rank > current_rank
                or same_status_refresh
            ):
                merged[field] = deepcopy(candidate)
            elif (
                _present(candidate)
                and field in {"geography", "area", "applicant_types", "purposes"}
                and incoming_status == current_status
                and incoming_rank == current_rank
            ):
                merged[field] = _merge_categorical(existing.get(field), candidate)
        merged["domain"] = existing.get("domain") or incoming.get("domain") or ""
        merged["normalized_name"] = existing["normalized_name"]
        merged["canonical_key"] = f"{merged['normalized_name']}|{merged['domain']}"
        merged["verification_status"] = chosen_status
        merged["status"] = chosen_status
        if incoming_status == chosen_status and incoming_date and (not current_date or incoming_date > current_date):
            merged["last_checked"] = incoming_date
            merged["last_verified_at"] = incoming_date
        existing_extra = existing.get("extra") if isinstance(existing.get("extra"), Mapping) else {}
        incoming_extra = incoming.get("extra") if isinstance(incoming.get("extra"), Mapping) else {}
        merged_extra = deepcopy(dict(existing_extra))
        if not rejected_stale_closure:
            merged_extra.update(deepcopy(dict(incoming_extra)))
        merged["extra"] = merged_extra
        return merged

    def upsert_fund(
        self,
        record: Mapping[str, Any],
        *,
        target_fund_id: int | None = None,
        source_name: str | None = None,
        source_record_id: Any = None,
        source_url: str | None = None,
        source_kind: str | None = None,
        raw: Mapping[str, Any] | None = None,
        observed_at: str | None = None,
        source_type: str | None = None,
        source_ref: str | None = None,
    ) -> int:
        canonical = self._canonical_record(record)
        now = _utc_now()
        if target_fund_id is None:
            existing = self._find_existing(canonical)
        else:
            existing = self._funds.get(int(target_fund_id))
            if existing is None:
                raise KeyError(f"Unknown fund_id: {target_fund_id}")
            conflict = next(
                (
                    fund
                    for fund_id, fund in self._funds.items()
                    if fund_id != int(target_fund_id) and fund["canonical_key"] == canonical["canonical_key"]
                ),
                None,
            )
            if conflict is not None:
                raise ValueError("The updated canonical fund identity conflicts with another fund record")
        if existing is None:
            fund_id = self._next_fund_id
            self._next_fund_id += 1
            self._meta_dirty = True
            fund = {
                "schema_version": SCHEMA_VERSION,
                "fund_id": fund_id,
                **canonical,
                "created_at": now,
                "updated_at": now,
            }
        else:
            fund_id = int(existing["fund_id"])
            fund = self._merge_record(existing, canonical)
            if target_fund_id is not None:
                fund["normalized_name"] = canonical["normalized_name"]
                fund["domain"] = canonical["domain"] or existing.get("domain", "")
                fund["canonical_key"] = f"{fund['normalized_name']}|{fund['domain']}"
            fund["schema_version"] = SCHEMA_VERSION
            fund["fund_id"] = fund_id
            fund["updated_at"] = now
        self._funds[fund_id] = fund
        self._persist_fund(fund)

        effective_source_kind = _text(source_kind or source_type or _pick(record, "source_kind", "source_type"))
        effective_source_name = _text(source_name or source_ref or _pick(record, "source_name", "source_ref"))
        effective_source_url = _text(source_url or _pick(record, "source_url"))
        _reject_url_credentials(effective_source_url)
        effective_source_record_id = _text(
            source_record_id if source_record_id not in (None, "") else _pick(record, "source_record_id", "external_id")
        )
        effective_observed_at = _text(observed_at or _pick(record, "observed_at", "last_seen_at"))
        if effective_source_kind or effective_source_name or effective_source_url or effective_source_record_id or raw is not None:
            payload = raw if raw is not None else record
            identity = {
                "canonical_key": canonical["canonical_key"],
                "source_kind": effective_source_kind,
                "source_name": effective_source_name,
                "source_url": effective_source_url,
                "source_record_id": effective_source_record_id,
                "payload": payload,
            }
            fingerprint = _record_fingerprint(identity)
            if fingerprint not in self._observation_fingerprints:
                observation = {
                    "schema_version": SCHEMA_VERSION,
                    "observation_id": fingerprint[:16],
                    "fund_id": fund_id,
                    "source_kind": effective_source_kind,
                    "source_name": effective_source_name,
                    "source_url": effective_source_url,
                    "source_record_id": effective_source_record_id,
                    "observed_at": effective_observed_at or now,
                    "raw_name": canonical["name"],
                    "raw_url": canonical["url"],
                    "payload": _json_safe(payload),
                    "fingerprint": fingerprint,
                }
                self._observations.setdefault(fund_id, []).append(observation)
                self._observation_fingerprints.add(fingerprint)
                self._persist_observations(fund_id)
        return fund_id

    def upsert_funds(self, records: Iterable[Mapping[str, Any]], **source: Any) -> list[int]:
        return [self.upsert_fund(record, **source) for record in records]

    def get_fund(self, fund_id: int) -> dict[str, Any] | None:
        fund = self._funds.get(int(fund_id))
        return None if fund is None else deepcopy(fund)

    def get_fund_by_key(self, canonical_key: str) -> dict[str, Any] | None:
        fund = next((item for item in self._funds.values() if item["canonical_key"] == canonical_key), None)
        return None if fund is None else deepcopy(fund)

    def find_fund(self, name: Any, url_or_domain: Any = "") -> dict[str, Any] | None:
        fund = self.get_fund_by_key(canonical_fund_key(name, url_or_domain))
        if fund is not None:
            return fund
        matches = [item for item in self._funds.values() if item["normalized_name"] == normalize_name(name)]
        return deepcopy(matches[0]) if len(matches) == 1 else None

    def list_funds(
        self,
        limit: int | None = None,
        verification_status: str | Sequence[str] | None = None,
        *,
        search: str | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        statuses: set[str] | None = None
        if verification_status:
            raw_statuses = [verification_status] if isinstance(verification_status, str) else list(verification_status)
            statuses = {normalize_verification(item) for item in raw_statuses}
        needle = normalize_name(search) if search else ""
        rows: list[dict[str, Any]] = []
        for fund in self._funds.values():
            if statuses is not None and fund["verification_status"] not in statuses:
                continue
            if needle:
                haystack = normalize_name(
                    " ".join(
                        _text(fund.get(field))
                        for field in ("normalized_name", "name", "purposes", "description", "geography", "area")
                    )
                )
                if needle not in haystack:
                    continue
            rows.append(deepcopy(fund))
        rows.sort(key=lambda item: (normalize_name(item["name"]), int(item["fund_id"])))
        start = max(0, int(offset))
        return rows[start:] if limit is None else rows[start : start + limit]

    def list_observations(self, fund_id: int | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        if fund_id is None:
            rows = [item for items in self._observations.values() for item in items]
        else:
            rows = list(self._observations.get(int(fund_id), []))
        rows.sort(key=lambda item: (str(item.get("observed_at", "")), str(item.get("observation_id", ""))))
        if limit is not None:
            rows = rows[:limit]
        return deepcopy(rows)

    def add_history(self, record: Mapping[str, Any]) -> int:
        fund_name = _text(_pick(record, "fund_name", "name", "fond", "pool_name"))
        fund_url = _text(_pick(record, "fund_url", "url", "official_url"))
        _reject_url_credentials(fund_url)
        domain = normalize_domain(_pick(record, "domain") or fund_url)
        if not fund_name:
            if domain:
                fund_name = domain
            else:
                raise ValueError("History record is missing fund name and URL")
        normalized_name = normalize_name(fund_name)
        canonical_key = f"{normalized_name}|{domain}"
        fund_id_value = _pick(record, "fund_id")
        fund_id = int(fund_id_value) if fund_id_value not in (None, "") else None
        if fund_id is None:
            fund = self.find_fund(fund_name, fund_url or domain)
            fund_id = None if fund is None else int(fund["fund_id"])
        source_kind = _text(_pick(record, "source_kind", "source_type"))
        source_name = _text(_pick(record, "source_name", "source_ref"))
        source_url = _text(_pick(record, "source_url"))
        _reject_url_credentials(source_url)
        external_id = _text(_pick(record, "external_id", "application_id", "source_record_id", "id"))
        values = {
            "fund_id": fund_id,
            "canonical_key": canonical_key,
            "normalized_fund_name": normalized_name,
            "fund_name": fund_name,
            "domain": domain,
            "fund_url": fund_url,
            "project_id": _text(_pick(record, "project_id")),
            "project_name": _text(_pick(record, "project_name", "project", "application_name", "title")),
            "submitted_at": _text(_pick(record, "submitted_at", "application_date", "date", "sent_at")),
            "status": _text(_pick(record, "status", "result", "decision")),
            "amount_requested": _text(_pick(record, "amount_requested", "requested_amount", "amount")),
            "external_id": external_id,
            "notes": _text(_pick(record, "notes", "note")),
            "source_kind": source_kind,
            "source_name": source_name,
            "source_url": source_url,
            "extra": _json_safe(_pick(record, "extra") or {}),
        }
        if external_id and (source_name or source_url):
            fingerprint_parts = {
                "source_kind": source_kind,
                "source_name": source_name,
                "source_url": source_url,
                "external_id": external_id,
            }
        else:
            fingerprint_parts = {
                key: values[key]
                for key in ("canonical_key", "project_id", "project_name", "submitted_at")
            }
            if not any(fingerprint_parts[key] for key in ("project_id", "project_name", "submitted_at")):
                fingerprint_parts["source_name"] = source_name
        fingerprint = _record_fingerprint(fingerprint_parts)
        history_id = self._history_fingerprints.get(fingerprint)
        if history_id is None:
            history_id = self._next_history_id
            self._next_history_id += 1
            self._meta_dirty = True
            item = {
                "schema_version": SCHEMA_VERSION,
                "history_id": history_id,
                **values,
                "fingerprint": fingerprint,
                "created_at": _utc_now(),
            }
            self._history[history_id] = item
            self._history_fingerprints[fingerprint] = history_id
        else:
            item = self._history[history_id]
            for field, candidate in values.items():
                if field == "extra":
                    existing_extra = item.get("extra") if isinstance(item.get("extra"), Mapping) else {}
                    incoming_extra = candidate if isinstance(candidate, Mapping) else {}
                    item["extra"] = {**existing_extra, **incoming_extra}
                elif candidate not in (None, "") and candidate != item.get(field):
                    item[field] = candidate
        self._persist_history(item)
        return history_id

    def record_sent_application(self, record: Mapping[str, Any]) -> int:
        return self.add_history(record)

    def update_history_result(
        self,
        history_id: int,
        *,
        status: str,
        notes: str | None = None,
        decision_at: str | None = None,
        awarded_amount: Any = None,
    ) -> dict[str, Any]:
        item = self._history.get(int(history_id))
        if item is None:
            raise KeyError(f"Unknown history_id: {history_id}")
        clean_status = _text(status)
        if not clean_status:
            raise ValueError("status is required")
        item["status"] = clean_status
        extra = item.get("extra") if isinstance(item.get("extra"), Mapping) else {}
        extra = dict(extra)
        if decision_at not in (None, ""):
            extra["decision_at"] = _text(decision_at)
        if awarded_amount not in (None, ""):
            extra["awarded_amount"] = _text(awarded_amount)
        item["extra"] = extra
        if notes is not None:
            item["notes"] = _text(notes)
        self._persist_history(item)
        return deepcopy(item)

    def list_history(
        self,
        limit: int | None = None,
        *,
        fund_id: int | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        rows = [
            deepcopy(item)
            for item in self._history.values()
            if (fund_id is None or item.get("fund_id") == int(fund_id))
            and (project_id is None or item.get("project_id") == _text(project_id))
        ]
        rows.sort(key=lambda item: int(item["history_id"]))
        return rows if limit is None else rows[:limit]

    def list_sent_applications(
        self,
        limit: int | None = None,
        *,
        fund_id: int | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.list_history(limit=limit, fund_id=fund_id, project_id=project_id)

    def has_prior_application(
        self,
        name: Any = None,
        url_or_domain: Any = "",
        *,
        fund_id: int | None = None,
        project_id: str | None = None,
    ) -> bool:
        if fund_id is None and name in (None, ""):
            raise ValueError("Specify either fund_id or a fund name")
        key = canonical_fund_key(name, url_or_domain) if fund_id is None else ""
        normalized = normalize_name(name) if fund_id is None else ""
        return any(
            (fund_id is not None and item.get("fund_id") == int(fund_id)
             or fund_id is None and (item.get("canonical_key") == key or item.get("normalized_fund_name") == normalized))
            and (project_id is None or item.get("project_id") == _text(project_id))
            for item in self._history.values()
        )

    def rebuild_index(self) -> dict[str, Any]:
        fields = (
            "fund_id",
            "name",
            "type",
            "domain",
            "official_url",
            "geography",
            "applicant_types",
            "purposes",
            "description",
            "amount",
            "deadline",
            "verification_status",
            "last_checked",
        )
        records = [
            {"schema_version": SCHEMA_VERSION, **{field: deepcopy(fund.get(field, "")) for field in fields}}
            for fund in sorted(self._funds.values(), key=lambda item: (normalize_name(item["name"]), int(item["fund_id"])))
        ]
        if not self.memory:
            assert self.index_path
            _atomic_write_text(self.index_path, "".join(safe_json_dumps(item) + "\n" for item in records))
        self._index_dirty = False
        return {"records": len(records), "index": None if self.index_path is None else str(self.index_path)}

    def integrity_check(self) -> dict[str, Any]:
        errors: list[str] = []
        keys: set[str] = set()
        for fund_id, fund in self._funds.items():
            if int(fund.get("fund_id", -1)) != fund_id:
                errors.append(f"fund_id mismatch: {fund_id}")
            expected_name = normalize_name(fund.get("name"))
            expected_key = f"{expected_name}|{normalize_domain(fund.get('domain') or fund.get('url'))}"
            if fund.get("normalized_name") != expected_name or fund.get("canonical_key") != expected_key:
                errors.append(f"canonical identity mismatch: {fund_id}")
            key = str(fund.get("canonical_key", ""))
            if not key or key in keys:
                errors.append(f"duplicate/empty canonical key: {fund_id}")
            keys.add(key)
        for fund_id, observations in self._observations.items():
            if fund_id not in self._funds:
                errors.append(f"orphan observations: {fund_id}")
            for item in observations:
                if int(item.get("fund_id", -1)) != fund_id:
                    errors.append(f"observation fund mismatch: {fund_id}")
        for history_id, item in self._history.items():
            linked = item.get("fund_id")
            if linked is not None and int(linked) not in self._funds:
                errors.append(f"history links unknown fund: {history_id}")
        return {"valid": not errors, "errors": errors}

    def stats(self) -> dict[str, Any]:
        statuses = {status: 0 for status in VERIFICATION_STATUSES}
        for fund in self._funds.values():
            statuses[str(fund["verification_status"])] += 1
        return {
            "funds": len(self._funds),
            "observations": sum(len(items) for items in self._observations.values()),
            "history": len(self._history),
            "verification_status": statuses,
        }


__all__ = [
    "JsonFundStore",
    "SCHEMA_VERSION",
    "VERIFICATION_STATUSES",
    "canonical_fund_key",
    "normalize_domain",
    "normalize_name",
    "normalize_verification",
    "safe_json_dumps",
    "safe_json_loads",
]
