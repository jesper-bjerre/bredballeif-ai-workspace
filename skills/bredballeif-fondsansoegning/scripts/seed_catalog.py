"""Build and load a public-safe, versioned starter catalogue.

The seed deliberately excludes licensed-only records, source observations,
free-text descriptions, requirements, notes, history and application data.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from json_store import JsonFundStore, safe_json_dumps


SEED_SCHEMA_VERSION = 1
PRIVATE_SOURCE_KINDS = {"licensed_directory", "private", "application_history"}
PRIVATE_SOURCE_NAMES = {"fundraising club", "bundled public seed"}
SEED_FIELDS = (
    "name",
    "url",
    "official_url",
    "type",
    "geography",
    "area",
    "applicant_types",
    "purposes",
    "amount",
    "deadline",
    "verification_status",
    "last_checked",
    "relevance",
)
PRIVATE_SEED_FIELDS = SEED_FIELDS + (
    "description",
    "requirements",
    "exclusions",
    "notes",
    "extra",
)
MAX_SEED_BYTES = 20 * 1024 * 1024
MAX_LINE_BYTES = 256 * 1024


def _is_public_observation(item: Mapping[str, Any]) -> bool:
    kind = str(item.get("source_kind", "")).strip().casefold()
    name = str(item.get("source_name", "")).strip().casefold()
    return bool(kind or name) and kind not in PRIVATE_SOURCE_KINDS and name not in PRIVATE_SOURCE_NAMES


def public_seed_records(store: JsonFundStore) -> list[dict[str, Any]]:
    public_ids = {
        int(item["fund_id"])
        for item in store.list_observations()
        if _is_public_observation(item)
    }
    records: list[dict[str, Any]] = []
    for fund in store.list_funds():
        if int(fund["fund_id"]) not in public_ids:
            continue
        record = {
            key: fund[key]
            for key in SEED_FIELDS
            if key in fund and fund[key] not in (None, "", [], {})
        }
        record.update(
            {
                "seed_schema_version": SEED_SCHEMA_VERSION,
                "seed_scope": "public",
                "source_kind": "public_seed",
                "source_name": "Bundled public seed",
                "source_record_id": str(fund.get("canonical_key", "")),
                "source_url": str(fund.get("official_url", "")),
            }
        )
        records.append(record)
    records.sort(key=lambda item: (str(item.get("name", "")).casefold(), str(item.get("source_record_id", ""))))
    return records


def private_seed_records(store: JsonFundStore) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for fund in store.list_funds():
        record = {
            key: fund[key]
            for key in PRIVATE_SEED_FIELDS
            if key in fund and fund[key] not in (None, "", [], {})
        }
        record.update(
            {
                "seed_schema_version": SEED_SCHEMA_VERSION,
                "seed_scope": "private",
                "source_kind": "private_seed",
                "source_name": "Private deployment seed",
                "source_record_id": str(fund.get("canonical_key", "")),
                "source_url": str(fund.get("official_url", "")),
            }
        )
        records.append(record)
    records.sort(key=lambda item: (str(item.get("name", "")).casefold(), str(item.get("source_record_id", ""))))
    return records


def _write_seed_records(records: list[dict[str, Any]], output_path: str | Path) -> dict[str, Any]:
    destination = Path(output_path).expanduser().resolve()
    if destination.exists() and destination.is_symlink():
        raise ValueError(f"Afviser at skrive seed gennem et symlink: {destination}")
    if not records:
        raise ValueError("Seedet ville blive tomt; kontrollér runtime-lageret og kildeobservationerne.")
    content = "".join(safe_json_dumps(record) + "\n" for record in records)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "records": len(records),
        "bytes": len(content.encode("utf-8")),
        "output": str(destination),
        "scope": str(records[0].get("seed_scope", "")),
    }


def write_public_seed(store_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    with JsonFundStore(store_path) as store:
        records = public_seed_records(store)
    return _write_seed_records(records, output_path)


def write_private_seed(store_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    with JsonFundStore(store_path) as store:
        records = private_seed_records(store)
    return _write_seed_records(records, output_path)


def read_seed(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path).expanduser().resolve()
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"Seed-filen mangler eller er et symlink: {source}")
    if source.stat().st_size > MAX_SEED_BYTES:
        raise ValueError("Seed-filen overskrider størrelsesgrænsen.")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            raise ValueError(f"Seed-linje {line_number} overskrider størrelsesgrænsen.")
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Ugyldig JSON i seed-linje {line_number}.") from exc
        if not isinstance(record, dict) or record.get("seed_schema_version") != SEED_SCHEMA_VERSION:
            raise ValueError(f"Ukendt eller ugyldigt seed-schema i linje {line_number}.")
        if record.get("seed_scope") not in {"public", "private"}:
            raise ValueError(f"Seed-linje {line_number} mangler et gyldigt scope.")
        if not str(record.get("name", "")).strip():
            raise ValueError(f"Seed-linje {line_number} mangler fondsnavn.")
        records.append(record)
    if not records:
        raise ValueError("Seed-filen indeholder ingen fonde.")
    return records


def import_seed(store: JsonFundStore, path: str | Path) -> dict[str, int]:
    records = read_seed(path)
    inserted = 0
    known = {int(item["fund_id"]) for item in store.list_funds()}
    for record in records:
        fund_id = store.upsert_fund(
            record,
            source_name=str(record.get("source_name", "")),
            source_kind=str(record.get("source_kind", "")),
            source_record_id=record.get("source_record_id"),
            source_url=str(record.get("source_url", "")),
            raw=record,
        )
        if fund_id not in known:
            inserted += 1
            known.add(fund_id)
    return {
        "records": len(records),
        "inserted": inserted,
        "updated": len(records) - inserted,
        "scope": str(records[0].get("seed_scope", "")),
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generér et offentligt, saniteret fonds-seed fra et runtime-lager.")
    parser.add_argument("--store", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--private", action="store_true", help="Medtag hele fondsindekset til privat deployment")
    args = parser.parse_args(list(argv) if argv is not None else None)
    writer = write_private_seed if args.private else write_public_seed
    print(json.dumps(writer(args.store, args.output), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
