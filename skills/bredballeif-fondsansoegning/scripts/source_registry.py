"""Committed source registry and private runtime coverage log."""

from __future__ import annotations

import json
import ipaddress
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo("Europe/Copenhagen")


def load_registry(path: str | Path) -> dict[str, Any]:
    registry_path = Path(path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("sources"), list):
        raise ValueError(f"Ugyldigt kilderegister: {registry_path}")
    ids: set[str] = set()
    for source in payload["sources"]:
        source_id = str(source.get("id", "")).strip()
        if not source_id or source_id in ids:
            raise ValueError(f"Kilderegisteret har manglende eller dubleret id: {source_id!r}")
        parsed = urlparse(str(source.get("url", "")))
        host = (parsed.hostname or "").casefold().rstrip(".")
        if (
            parsed.scheme.casefold() != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(f"Kilden {source_id} har en ugyldig URL.")
        if host == "localhost" or host.endswith(".localhost"):
            raise ValueError(f"Kilden {source_id} må ikke pege på localhost.")
        try:
            literal = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            literal = None
        if literal is not None and not literal.is_global:
            raise ValueError(f"Kilden {source_id} må ikke pege på en privat eller reserveret IP.")
        allowed_hosts = source.get("allowed_hosts", [])
        if not isinstance(allowed_hosts, list) or any(
            not isinstance(item, str)
            or not item.strip()
            or ":" in item
            or "/" in item
            or "@" in item
            for item in allowed_hosts
        ):
            raise ValueError(f"Kilden {source_id} har ugyldige allowed_hosts.")
        ids.add(source_id)
    return payload


def find_source(registry: dict[str, Any], source_id: str) -> dict[str, Any]:
    match = next((item for item in registry["sources"] if item.get("id") == source_id), None)
    if match is None:
        raise KeyError(f"Ukendt kilde-id: {source_id}")
    return match


def load_run_log(path: str | Path) -> dict[str, Any]:
    log_path = Path(path)
    if not log_path.exists():
        return {"schema_version": 1, "sources": {}}
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("sources"), dict):
        raise ValueError(f"Ugyldig dækningslog: {log_path}")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    parent_existed = path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix" and not parent_existed:
        os.chmod(path.parent, 0o700)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
        if os.name == "posix":
            os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def record_run(
    path: str | Path,
    source_id: str,
    *,
    status: str,
    records_seen: int = 0,
    records_written: int = 0,
    pages_visited: int = 0,
    warnings: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    log_path = Path(path)
    payload = load_run_log(log_path)
    entry = {
        "checked_at": datetime.now(TIMEZONE).replace(microsecond=0).isoformat(),
        "status": status,
        "records_seen": int(records_seen),
        "records_written": int(records_written),
        "pages_visited": int(pages_visited),
        "warnings": [str(item)[:1000] for item in (warnings or [])[:100]],
        "details": details or {},
    }
    payload["sources"][source_id] = entry
    payload["updated_at"] = entry["checked_at"]
    _write_json_atomic(log_path, payload)
    return entry


def coverage_report(
    registry: dict[str, Any],
    run_log: dict[str, Any],
    funds: list[dict[str, Any]],
) -> dict[str, Any]:
    now = datetime.now(TIMEZONE)
    source_rows: list[dict[str, Any]] = []
    missing: list[str] = []
    stale: list[str] = []
    failed: list[str] = []
    disabled: list[str] = []
    runs = run_log.get("sources", {})

    for source in registry["sources"]:
        source_id = str(source["id"])
        enabled = bool(source.get("enabled", False))
        run = runs.get(source_id)
        state = "disabled"
        age_days: int | None = None
        if not enabled:
            disabled.append(source_id)
        elif run is None:
            state = "missing"
            missing.append(source_id)
        else:
            try:
                checked = datetime.fromisoformat(str(run.get("checked_at", "")))
                if checked.tzinfo is None:
                    checked = checked.replace(tzinfo=TIMEZONE)
                age_days = max(0, (now - checked.astimezone(TIMEZONE)).days)
            except ValueError:
                state = "invalid_timestamp"
                failed.append(source_id)
            else:
                if run.get("status") != "success":
                    state = "failed"
                    failed.append(source_id)
                elif age_days > int(source.get("update_frequency_days", 30)):
                    state = "stale"
                    stale.append(source_id)
                else:
                    state = "current"
        source_rows.append(
            {
                "id": source_id,
                "name": source.get("name", ""),
                "kind": source.get("kind", ""),
                "enabled": enabled,
                "state": state,
                "age_days": age_days,
                "last_run": run,
            }
        )

    by_status: dict[str, int] = {}
    missing_official_url = 0
    for fund in funds:
        status = str(fund.get("verification_status", "unknown") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        if not str(fund.get("official_url") or fund.get("url") or "").startswith(("http://", "https://")):
            missing_official_url += 1

    current_coverage = not missing and not stale and not failed
    return {
        "generated_at": now.replace(microsecond=0).isoformat(),
        "definition": registry.get("completeness_definition", ""),
        "coverage_current": current_coverage,
        "coverage_label": "dokumenteret kildeaktuel" if current_coverage else "ufuldstændig eller forældet",
        "permanent_completeness_claim": False,
        "sources": {
            "total": len(source_rows),
            "enabled": sum(1 for row in source_rows if row["enabled"]),
            "current": sum(1 for row in source_rows if row["state"] == "current"),
            "missing": missing,
            "stale": stale,
            "failed": failed,
            "disabled_requires_manual_or_special_adapter": disabled,
            "items": source_rows,
        },
        "funds": {
            "total": len(funds),
            "by_verification_status": dict(sorted(by_status.items())),
            "missing_official_url": missing_official_url,
            # Kildestatus alene kan aldrig gøre en fond klar til et konkret
            # projekt. Projekt-id, beløb, deadline, portalsvar og bilag skal
            # stadig bestå den fondsspecifikke preflight.
            "not_application_ready": len(funds),
            "verified_source_records": by_status.get("verified", 0),
            "application_readiness_requires_project_preflight": True,
        },
    }
