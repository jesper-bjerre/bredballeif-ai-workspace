"""Agent-neutral CLI for Bredballe IF fund discovery and applications."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

from batch_workflow import (
    BatchPreparationError,
    approve_application,
    prepare_application_batch,
    validate_batch_directory,
    validate_requirement_research,
)
from importers import (
    ImportDependencyError,
    ImportFormatError,
    HistoryDownloadError,
    import_application_history,
    import_dgi_workbook,
    import_fund_workbook,
    import_history_from_url,
)
from json_store import JsonFundStore as BaseIndexStore
from matching import ProjectValidationError, match_funds, validate_project
from seed_catalog import import_seed
from scrapers import (
    FundraisingClubCrawler,
    PublicSourceCrawler,
    ScrapeError,
    fetch_current_dgi_workbook,
    sync_eu_funding_feed,
    sync_state_grants_feed,
)
from source_registry import coverage_report, find_source, load_registry, load_run_log, record_run


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TIMEZONE = ZoneInfo("Europe/Copenhagen")
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
ASSETS_DIR = SKILL_DIR / "assets"
DEFAULT_REGISTRY = SKILL_DIR / "references" / "source-registry.json"
DEFAULT_SEED = ASSETS_DIR / "funds-seed.jsonl"
SKILL_NAME = "bredballeif-fondsansoegning"


class IndexStore(BaseIndexStore):
    """Runtime store that bootstraps an empty installation from the bundled public seed."""

    def initialize(self) -> "IndexStore":
        super().initialize()
        seed_disabled = os.environ.get("BREDBALLEIF_FONDS_DISABLE_SEED", "").strip() == "1"
        private_seed = os.environ.get("BREDBALLEIF_FONDS_PRIVATE_SEED", "").strip()
        seed_path = Path(private_seed).expanduser().resolve() if private_seed else DEFAULT_SEED
        if private_seed and not seed_path.is_file():
            raise ValueError(f"BREDBALLEIF_FONDS_PRIVATE_SEED peger ikke på en fil: {seed_path}")
        if not self.memory and not seed_disabled and not self.list_funds() and seed_path.is_file():
            self.seed_import = import_seed(self, seed_path)
        else:
            self.seed_import = {"records": 0, "inserted": 0, "updated": 0, "scope": ""}
        return self


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    workspace: Path | None = None
    for candidate in (SKILL_DIR, *SKILL_DIR.parents):
        if (candidate / "skills.manifest.json").is_file():
            workspace = candidate
            break
    candidates = [SKILL_DIR / ".env"]
    if workspace is not None:
        candidates.append(workspace / ".env")
    for path in candidates:
        if path.is_file():
            load_dotenv(path, override=False)
            return


_load_dotenv()


def _workspace_root() -> Path | None:
    for candidate in (SKILL_DIR, *SKILL_DIR.parents):
        if (candidate / "skills.manifest.json").is_file():
            return candidate
    return None


def _default_data_dir() -> Path:
    configured = os.environ.get("BREDBALLEIF_FONDS_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    workspace = _workspace_root()
    if workspace is not None:
        return (workspace / "data" / SKILL_NAME).resolve()
    return (Path.cwd() / "data" / SKILL_NAME).resolve()


def _ensure_private_output(path: str | Path, *, label: str = "Output") -> Path:
    candidate = Path(path).expanduser().resolve()
    workspace = _workspace_root()
    if workspace is not None:
        workspace = workspace.resolve()
        private_root = (workspace / "data").resolve()
        inside_workspace = candidate == workspace or workspace in candidate.parents
        inside_private_root = candidate == private_root or private_root in candidate.parents
        if inside_workspace and not inside_private_root:
            raise ValueError(
                f"{label} må ikke ligge i en committet workspace-mappe; brug repoets gitignorerede data/ eller en ekstern privat sti."
            )
    return candidate


def _paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    data_dir = _ensure_private_output(
        Path(args.data_dir).expanduser().resolve() if args.data_dir else _default_data_dir(),
        label="Runtime-data",
    )
    store_path = _ensure_private_output(
        Path(args.store).expanduser().resolve() if args.store else data_dir / "store",
        label="JSON-lager",
    )
    run_log = data_dir / "source-runs.json"
    return data_dir, store_path, run_log


def _registry(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.registry).expanduser().resolve()
    if (
        path != DEFAULT_REGISTRY.resolve()
        and os.environ.get("BREDBALLEIF_FONDS_ALLOW_CUSTOM_REGISTRY", "").strip() != "1"
    ):
        raise ValueError(
            "Et alternativt kilderegister er deaktiveret som standard; redigér det committede register "
            "eller sæt BREDBALLEIF_FONDS_ALLOW_CUSTOM_REGISTRY=1 i et betroet udviklingsmiljø."
        )
    return load_registry(path)


def _read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON-filen skal indeholde et objekt: {source}")
    return payload


def _write_json(path: str | Path, payload: Any, *, overwrite: bool = False) -> Path:
    destination = Path(path).expanduser().resolve()
    unresolved = Path(path).expanduser()
    if unresolved.is_symlink() or destination.is_symlink():
        raise ValueError(f"Afviser at skrive JSON gennem et symlink: {unresolved}")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Filen findes allerede: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if not overwrite:
        try:
            with destination.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        except FileExistsError as exc:
            raise FileExistsError(f"Filen findes allerede: {destination}") from exc
        if os.name == "posix":
            os.chmod(destination, 0o600)
        return destination
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="." + destination.name + ".",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    if os.name == "posix":
        os.chmod(destination, 0o600)
    return destination


def _print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _upsert_records(store: IndexStore, records: list[dict[str, Any]]) -> dict[str, int]:
    inserted = 0
    updated = 0
    known_ids = {int(item["fund_id"]) for item in store.list_funds()}
    for record in records:
        fund_id = store.upsert_fund(
            record,
            source_name=str(record.get("source_name", "")),
            source_record_id=record.get("source_record_id"),
            source_url=str(record.get("source_url", "")),
            source_kind=str(record.get("source_kind", "")),
            raw=record,
            observed_at=str(record.get("last_seen_at", "")) or None,
        )
        if fund_id not in known_ids:
            inserted += 1
            known_ids.add(fund_id)
        else:
            updated += 1
    return {"inserted": inserted, "updated": updated, "written": len(records)}


def cmd_initialiser(args: argparse.Namespace) -> int:
    data_dir, db_path, run_log = _paths(args)
    data_dir.mkdir(parents=True, exist_ok=True)
    registry = _registry(args)
    with IndexStore(db_path) as store:
        stats = store.stats()
        seed_import = store.seed_import
    _print(
        {
            "success": True,
            "data_dir": str(data_dir),
            "store": str(db_path),
            "source_run_log": str(run_log),
            "registered_sources": len(registry["sources"]),
            "seed_import": seed_import,
            "stats": stats,
        }
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    _, db_path, run_log_path = _paths(args)
    registry = _registry(args)
    with IndexStore(db_path) as store:
        funds = store.list_funds()
        stats = store.stats()
    report = coverage_report(registry, load_run_log(run_log_path), funds)
    _print({"success": True, "store": str(db_path), "stats": stats, "coverage": report})
    return 0


def cmd_daekning(args: argparse.Namespace) -> int:
    _, db_path, run_log_path = _paths(args)
    registry = _registry(args)
    with IndexStore(db_path) as store:
        funds = store.list_funds()
    report = coverage_report(registry, load_run_log(run_log_path), funds)
    _print({"success": report["coverage_current"] or not args.strict, "coverage": report})
    return 0 if report["coverage_current"] or not args.strict else 1


def cmd_genopbyg_indeks(args: argparse.Namespace) -> int:
    """Rebuild the derived JSONL index from canonical fund files."""

    _, store_path, _ = _paths(args)
    with IndexStore(store_path) as store:
        result = store.rebuild_index()
        integrity = store.integrity_check()
    _print({"success": integrity["valid"], "index": result, "integrity": integrity})
    return 0 if integrity["valid"] else 1


def cmd_liste(args: argparse.Namespace) -> int:
    _, db_path, _ = _paths(args)
    with IndexStore(db_path) as store:
        funds = store.list_funds(
            limit=args.limit,
            verification_status=args.verification_status,
            search=args.search,
            offset=args.offset,
        )
    _print({"success": True, "count": len(funds), "funds": funds})
    return 0


def cmd_importer_regneark(args: argparse.Namespace) -> int:
    _, db_path, run_log_path = _paths(args)
    source = Path(args.path).expanduser().resolve()
    with IndexStore(db_path) as store:
        result = import_fund_workbook(
            source,
            store,
            source_name=args.source_name,
            source_url=args.source_url,
        )
        stats = store.stats()
    source_id = args.source_id or "seed-workbook"
    record_run(
        run_log_path,
        source_id,
        status="success" if result.ok else "failed",
        records_seen=result.records_seen,
        records_written=result.imported,
        warnings=result.errors,
        details={"path": str(source), "import": result.to_dict()},
    )
    _print({"success": result.ok, "import": result.to_dict(), "stats": stats})
    return 0 if result.ok else 1


def cmd_synkroniser_dgi(args: argparse.Namespace) -> int:
    _, db_path, run_log_path = _paths(args)
    try:
        content, download_url = fetch_current_dgi_workbook(timeout_seconds=args.timeout)
        with tempfile.TemporaryDirectory(prefix="bredballeif-dgi-") as directory:
            workbook = Path(directory) / "dgi-fondsliste.xlsx"
            workbook.write_bytes(content)
            with IndexStore(db_path) as store:
                result = import_dgi_workbook(
                    workbook,
                    store,
                    source_name="DGI – aktuel fondsliste",
                    source_url=download_url,
                )
                stats = store.stats()
    except Exception as exc:
        record_run(
            run_log_path,
            "dgi-170-fonde",
            status="failed",
            warnings=[f"{exc.__class__.__name__}: {str(exc)[:500]}"],
        )
        raise
    record_run(
        run_log_path,
        "dgi-170-fonde",
        status="success" if result.ok else "failed",
        records_seen=result.records_seen,
        records_written=result.imported,
        warnings=result.errors,
        details={"download_url": download_url, "import": result.to_dict()},
    )
    _print({"success": result.ok, "download_url": download_url, "import": result.to_dict(), "stats": stats})
    return 0 if result.ok else 1


def cmd_importer_historik(args: argparse.Namespace) -> int:
    _, db_path, _ = _paths(args)
    with IndexStore(db_path) as store:
        if args.url:
            result = import_history_from_url(
                args.url,
                store,
                sheet_name=args.sheet,
                header_row=args.header_row,
                include_notes=args.include_notes,
            )
        else:
            result = import_application_history(
                Path(args.path).expanduser().resolve(),
                store,
                sheet_name=args.sheet,
                header_row=args.header_row,
                source_name=args.source_name,
                include_notes=args.include_notes,
            )
        stats = store.stats()
    _print({"success": result.ok, "import": result.to_dict(), "stats": stats})
    return 0 if result.ok else 1


def cmd_historik(args: argparse.Namespace) -> int:
    _, db_path, _ = _paths(args)
    with IndexStore(db_path) as store:
        rows = store.list_history(
            limit=args.limit,
            fund_id=args.fund_id,
            project_id=args.project_id,
        )
    _print({"success": True, "count": len(rows), "history": rows})
    return 0


def cmd_opdater_resultat(args: argparse.Namespace) -> int:
    _, db_path, _ = _paths(args)
    with IndexStore(db_path) as store:
        updated = store.update_history_result(
            args.history_id,
            status=args.status,
            notes=args.notes,
            decision_at=args.decision_at,
            awarded_amount=args.awarded_amount,
        )
    _print({"success": True, "history": updated})
    return 0


def cmd_synkroniser_statens_puljer(args: argparse.Namespace) -> int:
    _, db_path, run_log_path = _paths(args)
    try:
        crawl, counts = sync_state_grants_feed(
            include_inactive=args.include_inactive,
            include_all_active=args.include_all_active,
            timeout_seconds=args.timeout,
        )
        with IndexStore(db_path) as store:
            writes = _upsert_records(store, crawl.records)
            stats = store.stats()
    except Exception as exc:
        record_run(
            run_log_path,
            "statens-tilskudspuljer",
            status="failed",
            warnings=[f"{exc.__class__.__name__}: {str(exc)[:500]}"],
        )
        raise
    record_run(
        run_log_path,
        "statens-tilskudspuljer",
        status="success",
        records_seen=counts["total"],
        records_written=writes["written"],
        pages_visited=1,
        warnings=crawl.warnings,
        details={"feed_counts": counts, "writes": writes},
    )
    _print({"success": True, "feed": counts, "writes": writes, "stats": stats})
    return 0


def cmd_synkroniser_eu(args: argparse.Namespace) -> int:
    _, db_path, run_log_path = _paths(args)
    try:
        crawl, counts = sync_eu_funding_feed(
            include_all_open=args.include_all_open,
            page_size=args.page_size,
            max_pages=args.max_pages,
            delay_seconds=args.delay,
            timeout_seconds=args.timeout,
        )
        with IndexStore(db_path) as store:
            writes = _upsert_records(store, crawl.records)
            stats = store.stats()
    except Exception as exc:
        record_run(
            run_log_path,
            "eu-funding-api",
            status="failed",
            warnings=[f"{exc.__class__.__name__}: {str(exc)[:500]}"],
        )
        raise
    complete = bool(crawl.complete)
    record_run(
        run_log_path,
        "eu-funding-api",
        status="success" if complete else "incomplete",
        records_seen=int(counts["processed"]),
        records_written=writes["written"],
        pages_visited=crawl.pages_visited,
        warnings=crawl.warnings,
        details={"feed_counts": counts, "writes": writes},
    )
    _print(
        {
            "success": complete,
            "feed": counts,
            "pages_visited": crawl.pages_visited,
            "writes": writes,
            "warnings": crawl.warnings,
            "stats": stats,
        }
    )
    return 0 if complete else 1


def cmd_synkroniser_kilder(args: argparse.Namespace) -> int:
    _, db_path, run_log_path = _paths(args)
    registry = _registry(args)
    if args.source_id:
        sources = [find_source(registry, source_id) for source_id in args.source_id]
        specialised = [source for source in sources if source.get("adapter")]
        if specialised:
            names = ", ".join(str(source["id"]) for source in specialised)
            raise ValueError(f"Kilden har en specialadapter og kan ikke køres generisk: {names}")
    else:
        sources = [
            source
            for source in registry["sources"]
            if source.get("enabled") and source.get("kind") in {"directory", "opportunity"}
            and not source.get("adapter")
        ]
    summaries: list[dict[str, Any]] = []
    any_failed = False
    with IndexStore(db_path) as store:
        for source in sources:
            source_id = str(source["id"])
            crawler = PublicSourceCrawler(delay_seconds=args.delay, timeout_seconds=args.timeout)
            try:
                crawl = crawler.crawl(source, max_pages=args.max_pages)
                if crawl.pages_visited == 0:
                    raise ScrapeError("Ingen sider blev hentet; kilden kan ikke markeres som aktuel.")
                writes = _upsert_records(store, crawl.records)
                status = "success" if crawl.complete else "incomplete"
                error = ""
                if not crawl.complete:
                    any_failed = True
            except (ScrapeError, ValueError) as exc:
                crawl = None
                writes = {"inserted": 0, "updated": 0, "written": 0}
                status = "failed"
                error = str(exc)
                any_failed = True
            finally:
                crawler.close()
            warnings = ([] if crawl is None else crawl.warnings) + ([error] if error else [])
            pages = 0 if crawl is None else crawl.pages_visited
            seen = 0 if crawl is None else len(crawl.records)
            record_run(
                run_log_path,
                source_id,
                status=status,
                records_seen=seen,
                records_written=writes["written"],
                pages_visited=pages,
                warnings=warnings,
                details={"writes": writes},
            )
            summaries.append(
                {
                    "source_id": source_id,
                    "status": status,
                    "pages_visited": pages,
                    "records_seen": seen,
                    "writes": writes,
                    "warnings": warnings,
                }
            )
        stats = store.stats()
    _print({"success": not any_failed, "sources": summaries, "stats": stats})
    return 1 if any_failed else 0


def cmd_synkroniser_fundraisingclub(args: argparse.Namespace) -> int:
    _, db_path, run_log_path = _paths(args)
    username = os.environ.get("FUNDRAISINGCLUB_USERNAME", "")
    password = os.environ.get("FUNDRAISINGCLUB_PASSWORD", "")
    base_url = os.environ.get("FUNDRAISINGCLUB_BASE_URL", "https://app.fundraisingclub.dk")
    crawler: FundraisingClubCrawler | None = None
    try:
        crawler = FundraisingClubCrawler(
            base_url=base_url,
            delay_seconds=args.delay,
            timeout_seconds=args.timeout,
            confirm_authorized_use=args.confirm_authorized_use,
        )
        crawler.login(username, password)
        crawl = crawler.crawl(
            start_urls=args.start_url or (),
            max_pages=args.max_pages,
            max_depth=args.max_depth,
        )
        with IndexStore(db_path) as store:
            writes = _upsert_records(store, crawl.records)
            stats = store.stats()
    except Exception as exc:
        record_run(
            run_log_path,
            "fundraising-club",
            status="failed",
            warnings=[f"{exc.__class__.__name__}: {str(exc)[:500]}"],
        )
        raise
    finally:
        if crawler is not None:
            crawler.close()
    complete = bool(crawl.complete)
    record_run(
        run_log_path,
        "fundraising-club",
        status="success" if complete else "incomplete",
        records_seen=len(crawl.records),
        records_written=writes["written"],
        pages_visited=crawl.pages_visited,
        warnings=crawl.warnings,
        details={"writes": writes},
    )
    _print(
        {
            "success": complete,
            "pages_visited": crawl.pages_visited,
            "records_seen": len(crawl.records),
            "writes": writes,
            "warnings": crawl.warnings,
            "stats": stats,
        }
    )
    return 0 if complete else 1


def cmd_valider_projekt(args: argparse.Namespace) -> int:
    project = _read_json(args.project)
    report = validate_project(project, stage=args.stage, as_of=args.as_of)
    _print({"success": report["valid"], "validation": report})
    return 0 if report["valid"] else 1


def cmd_match(args: argparse.Namespace) -> int:
    _, db_path, _ = _paths(args)
    project = _read_json(args.project)
    with IndexStore(db_path) as store:
        results = match_funds(
            store,
            project,
            fund_ids=args.fund_id,
            limit=args.limit,
            as_of=args.as_of,
            include_blocked=args.include_blocked,
        )
    payload = {"success": True, "count": len(results), "matches": results}
    if args.output:
        destination = _write_json(
            _ensure_private_output(args.output, label="Match-output"),
            payload,
            overwrite=args.overwrite,
        )
        payload["output"] = str(destination)
    _print(payload)
    return 0


def _criterion_requirement(payload: dict[str, Any], category: str) -> str:
    criteria = payload.get("criteria", [])
    if not isinstance(criteria, list):
        return ""
    for item in criteria:
        if isinstance(item, dict) and str(item.get("category", "")) == category:
            return str(item.get("requirement", "")).strip()
    return ""


def cmd_opdater_fond(args: argparse.Namespace) -> int:
    """Promote one fund only after current official requirements were researched."""

    _, db_path, _ = _paths(args)
    payload = _read_json(args.requirements)
    payload_fund_id = payload.get("fund_id")
    if payload_fund_id in (None, "") or str(payload_fund_id) != str(args.fund_id):
        raise ValueError("requirements-filens fund_id skal matche --fund-id.")
    lifecycle = str(payload.get("status", "open")).casefold().strip()
    no_go_mode = (
        lifecycle in {"closed", "lukket", "inactive", "inaktiv"}
        or str(payload.get("go_no_go", "")).casefold().strip() in {"no_go", "no-go", "no go"}
    )
    research_validation = validate_requirement_research(payload, allow_no_go=no_go_mode)
    if not research_validation["valid"]:
        raise BatchPreparationError(
            "Kravresearch er ikke komplet nok til at verificere fonden.",
            errors=research_validation["errors"],
        )
    official_url = str(payload.get("official_source_url", "")).strip()
    parsed_url = urlparse(official_url)
    if (
        parsed_url.scheme.casefold() != "https"
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        raise ValueError("requirements-filen mangler en sikker HTTPS official_source_url uden credentials.")
    checked_at = str(payload.get("checked_at", "")).strip()
    if not checked_at:
        raise ValueError("requirements-filen mangler checked_at.")
    checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=TIMEZONE)
    if checked.astimezone(TIMEZONE) > datetime.now(TIMEZONE):
        raise ValueError("checked_at må ikke ligge i fremtiden.")

    verification_status = "closed" if lifecycle in {"closed", "lukket", "inactive", "inaktiv"} else "verified"
    indexed = payload.get("indexed_requirements")
    structured = indexed if isinstance(indexed, dict) else payload
    amount = payload.get("amount", {})
    deadline = payload.get("deadline", {})
    applicant_types = structured.get("applicant_types") or _criterion_requirement(
        payload, "applicant_eligibility"
    )
    purposes = structured.get("purposes") or _criterion_requirement(payload, "purpose_and_target_group")
    eligible_expenses = structured.get("eligible_expenses") or _criterion_requirement(
        payload, "eligible_and_excluded_costs"
    )
    exclusions = structured.get("excluded_expenses") or payload.get("exclusions", [])
    deadline_value = deadline.get("value", "") if isinstance(deadline, dict) else deadline
    if isinstance(deadline, dict) and deadline.get("rolling"):
        deadline_value = deadline_value or "Løbende"
    if isinstance(amount, dict):
        minimum = amount.get("minimum_dkk")
        maximum = amount.get("maximum_dkk")
        if minimum is not None and maximum is not None:
            amount_text = f"{minimum}–{maximum} DKK"
        elif maximum is not None:
            amount_text = f"Op til {maximum} DKK"
        elif minimum is not None:
            amount_text = f"Fra {minimum} DKK"
        else:
            amount_text = ""
    else:
        amount_text = str(amount)

    with IndexStore(db_path) as store:
        fund = store.get_fund(args.fund_id)
        if fund is None:
            raise KeyError(f"Fonden findes ikke i indekset: {args.fund_id}")
        if str(payload.get("fund_name", "")).strip() != str(fund.get("name", "")).strip():
            raise ValueError("requirements-filens fund_name skal matche fondens aktuelle navn i indekset.")
        extra = dict(fund.get("extra", {})) if isinstance(fund.get("extra"), dict) else {}
        extra.update(
            {
                "requirements": payload,
                "requirements_data": payload,
                "source": {"url": official_url, "checked_at": checked_at, "official": True},
                "lifecycle_status": lifecycle,
                "eligible_expenses": eligible_expenses,
                "ineligible_expenses": exclusions,
                "target_groups": structured.get("target_groups", []),
                "required_documents": payload.get("attachments", []),
                "portal_fields": payload.get("portal_fields", []),
                "application_url": payload.get("application_url", ""),
                "project_may_start_before_decision": (
                    deadline.get("project_may_start_before_decision") if isinstance(deadline, dict) else None
                ),
            }
        )
        record = {
            **fund,
            "url": official_url,
            "official_url": official_url,
            "domain": parsed_url.hostname or "",
            "applicant_types": applicant_types,
            "purposes": purposes,
            "amount": amount_text or fund.get("amount", ""),
            "deadline": deadline_value or fund.get("deadline", ""),
            "requirements": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            "exclusions": exclusions,
            "verification_status": verification_status,
            "last_checked": checked_at,
            "extra": extra,
        }
        store.upsert_fund(
            record,
            target_fund_id=args.fund_id,
            source_name="Officiel kravresearch",
            source_record_id=f"fund-{args.fund_id}-{checked.date().isoformat()}",
            source_url=official_url,
            source_kind="official_requirement_snapshot",
            raw=payload,
            observed_at=checked_at,
        )
        updated = store.get_fund(args.fund_id)
    _print({"success": True, "fund": updated})
    return 0


def _default_batch_dir(data_dir: Path, project: dict[str, Any]) -> Path:
    project_id = str(project.get("project_id") or project.get("id") or "projekt")
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in project_id).strip("-")
    timestamp = datetime.now(TIMEZONE).strftime("%Y%m%d-%H%M%S")
    return data_dir / "batches" / f"{timestamp}-{safe or 'projekt'}"


def cmd_forbered_batch(args: argparse.Namespace) -> int:
    data_dir, db_path, _ = _paths(args)
    project = _read_json(args.project)
    output = Path(args.output).expanduser().resolve() if args.output else _default_batch_dir(data_dir, project)
    output = _ensure_private_output(output, label="Batch-output")
    with IndexStore(db_path) as store:
        manifest = prepare_application_batch(
            store,
            project,
            output,
            fund_ids=args.fund_id,
            limit=args.limit,
            ready=args.confirm_ready,
            as_of=args.as_of,
            source_max_age_days=args.source_max_age_days,
            template_dir=ASSETS_DIR,
            overwrite=args.overwrite,
        )
    _print({"success": True, "output": str(output), "batch": manifest})
    return 0


def cmd_valider_batch(args: argparse.Namespace) -> int:
    _, db_path, _ = _paths(args)
    with IndexStore(db_path) as store:
        validation = validate_batch_directory(
            args.batch,
            store=store,
            as_of=args.as_of,
            max_age=args.source_max_age_days,
            require_approval=args.require_approval,
        )
    _print({"success": validation["valid"], "validation": validation})
    return 0 if validation["valid"] else 1


def cmd_godkend(args: argparse.Namespace) -> int:
    _, db_path, _ = _paths(args)
    approvals: list[dict[str, Any]] = []
    with IndexStore(db_path) as store:
        for fund_id in args.fund_id:
            approval = approve_application(
                args.batch,
                fund_id,
                args.approved_by,
                approved_at=args.approved_at,
                store=store,
                as_of=args.as_of,
                max_age=args.source_max_age_days,
            )
            approvals.append(dict(approval))
    _print(
        {
            "success": True,
            "approved": approvals,
            "network_action_performed": False,
            "message": "Intern godkendelse er registreret; ingen ansøgning er indsendt.",
        }
    )
    return 0


def _batch_fund_directory(batch_root: Path, item: dict[str, Any]) -> Path:
    raw = str(item.get("relative_folder") or item.get("folder") or "")
    if not raw:
        raise ValueError("Batchposten mangler folder.")
    path = Path(raw)
    candidate = path.resolve() if path.is_absolute() else (batch_root / path).resolve()
    if candidate != batch_root and batch_root not in candidate.parents:
        if ".." in path.parts:
            raise ValueError("Batchposten peger uden for batchmappen.")
        candidate = (batch_root / path.name).resolve()
    if batch_root not in candidate.parents:
        raise ValueError("Batchposten peger uden for batchmappen.")
    return candidate


def cmd_registrer_indsendelse(args: argparse.Namespace) -> int:
    if not args.confirm_submitted:
        raise ValueError("Bekræft den faktiske eksterne indsendelse med --confirm-submitted.")
    batch_root = Path(args.batch).expanduser().resolve()
    manifest_path = batch_root / "batch.json"
    manifest = _read_json(manifest_path)
    project_payload = _read_json(batch_root / "project.json")
    normalized_project = project_payload.get("normalized", {})
    if not isinstance(normalized_project, dict):
        raise ValueError("project.json mangler normalized-projektet.")
    project_id = normalized_project.get("project_id") or manifest.get("project_id")
    if str(project_id) != str(manifest.get("project_id")):
        raise ValueError("Projekt-id i project.json og batch.json stemmer ikke overens.")
    items = manifest.get("applications", [])
    if not isinstance(items, list):
        raise ValueError("batch.json har et ugyldigt applications-felt.")
    target = next(
        (dict(item) for item in items if isinstance(item, dict) and str(item.get("fund_id")) == str(args.fund_id)),
        None,
    )
    if target is None:
        raise KeyError(f"Fonden findes ikke i batchen: {args.fund_id}")
    fund_dir = _batch_fund_directory(batch_root, target)
    approval = _read_json(fund_dir / "approval.json")
    if (
        approval.get("status") != "approved"
        or not str(approval.get("approved_by") or "").strip()
        or not str(approval.get("approved_at") or "").strip()
    ):
        raise ValueError("Ansøgningen er ikke internt godkendt.")
    _, db_path, _ = _paths(args)
    with IndexStore(db_path) as store:
        validation = validate_batch_directory(
            batch_root,
            store=store,
            as_of=args.as_of,
            max_age=args.source_max_age_days,
            require_approval=True,
        )
        target_errors = [
            error
            for error in validation.get("errors", [])
            if str(error.get("fund_id")) in {"None", str(args.fund_id)}
        ]
        if target_errors:
            raise BatchPreparationError(
                "Den godkendte pakke er ændret eller ikke længere gyldig.",
                errors=target_errors,
            )
        submitted_at = args.submitted_at or datetime.now(TIMEZONE).replace(microsecond=0).isoformat()
        submission = {
            "schema_version": 1,
            "batch_id": manifest.get("batch_id"),
            "project_id": manifest.get("project_id"),
            "fund_id": args.fund_id,
            "fund_name": target.get("fund_name"),
            "submitted_at": submitted_at,
            "channel": args.channel,
            "reference": args.reference,
            "status": args.status,
            "network_action_performed_by_this_command": False,
            "approval_hash": approval.get("approval_hash"),
        }
        submission_path = fund_dir / "submission.json"
        if submission_path.exists() and not args.overwrite:
            existing_submission = _read_json(submission_path)
            if args.submitted_at is None:
                submission["submitted_at"] = existing_submission.get("submitted_at")
            stable_fields = (
                "batch_id",
                "project_id",
                "fund_id",
                "fund_name",
                "submitted_at",
                "channel",
                "reference",
                "status",
                "approval_hash",
            )
            if any(
                str(existing_submission.get(field, "")) != str(submission.get(field, ""))
                for field in stable_fields
            ):
                raise FileExistsError(
                    "submission.json findes med andre indsendelsesmetadata; kontrollér filen eller brug --overwrite bevidst."
                )
            submission = dict(existing_submission)
            submitted_at = str(existing_submission.get("submitted_at") or submitted_at)
        else:
            _write_json(submission_path, submission, overwrite=args.overwrite)
        history_id = store.add_history(
            {
                "fund_id": args.fund_id,
                "fund_name": target.get("fund_name"),
                "fund_url": approval.get("submission", {}).get("history_record_after_submission", {}).get("fund_url", ""),
                "project_id": project_id,
                "project_name": normalized_project.get("title") or project_id,
                "submitted_at": submitted_at,
                "status": submission.get("status", args.status),
                "amount_requested": approval.get("submission", {}).get("requested_amount_dkk", ""),
                "external_id": submission.get("reference", args.reference),
                "source_kind": "confirmed_submission",
                "source_name": str(manifest.get("batch_id", "")),
                "extra": {
                    "channel": submission.get("channel", args.channel),
                    "approval_hash": approval.get("approval_hash"),
                    "batch_id": manifest.get("batch_id"),
                },
            }
        )
    updated_items: list[Any] = []
    for item in items:
        if isinstance(item, dict) and str(item.get("fund_id")) == str(args.fund_id):
            updated = dict(item)
            updated["status"] = "submitted"
            updated["submitted_at"] = submitted_at
            updated["submission_file"] = str(submission_path.relative_to(batch_root))
            updated_items.append(updated)
        else:
            updated_items.append(item)
    manifest["applications"] = updated_items
    _write_json(manifest_path, manifest, overwrite=True)
    _print(
        {
            "success": True,
            "history_id": history_id,
            "submission": submission,
            "message": "Allerede udført ekstern indsendelse er registreret; kommandoen sendte intet.",
        }
    )
    return 0


def cmd_opret_projekt(args: argparse.Namespace) -> int:
    source = ASSETS_DIR / "project-brief.example.json"
    destination = _ensure_private_output(args.output, label="Projektbrief")
    _write_json(destination, json.loads(source.read_text(encoding="utf-8")), overwrite=args.overwrite)
    _print({"success": True, "project_template": str(destination)})
    return 0


def _add_global_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-dir", help="Privat runtime-mappe; default er repoets gitignored data-mappe")
    parser.add_argument("--store", help="Alternativ sti til det filbaserede JSON-lager")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY), help="Sti til source-registry.json")
    parser.add_argument("--debug", action="store_true", help="Vis traceback ved fejl")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=SKILL_NAME,
        description="Find, match og forbered fondsspecifikke ansøgninger for Bredballe IF.",
    )
    _add_global_arguments(parser)
    sub = parser.add_subparsers(dest="action", metavar="<action>")

    sub.add_parser("initialiser", help="Opret privat indeks og vis stier")
    sub.add_parser("status", help="Vis indeks- og kildestatus")
    sub.add_parser("genopbyg-indeks", help="Genopbyg index.jsonl fra funds/*.json")

    coverage = sub.add_parser("daekning", help="Vis dokumenteret kildedækning")
    coverage.add_argument("--strict", action="store_true", help="Returnér fejl hvis en aktiv kilde mangler/er forældet")

    listing = sub.add_parser("liste", help="List fonde i indekset")
    listing.add_argument("--search")
    listing.add_argument("--verification-status", action="append")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--offset", type=int, default=0)

    workbook = sub.add_parser("importer-regneark", help="Importér 02_Aktuelle og 03_Fondsindeks fra XLSX")
    workbook.add_argument("--path", required=True)
    workbook.add_argument("--source-name")
    workbook.add_argument("--source-url")
    workbook.add_argument("--source-id")

    dgi = sub.add_parser("synkroniser-dgi", help="Find og importér DGI's aktuelle offentlige Excel-liste")
    dgi.add_argument("--timeout", type=float, default=60.0)

    history = sub.add_parser("importer-historik", help="Importér tidligere ansøgninger fra privat XLSX/CSV")
    history_source = history.add_mutually_exclusive_group(required=True)
    history_source.add_argument("--path")
    history_source.add_argument("--url", help="Direkte, offentligt XLSX-downloadlink på en tilladt OneDrive/SharePoint-host")
    history.add_argument("--sheet")
    history.add_argument("--header-row", type=int)
    history.add_argument("--source-name")
    history.add_argument(
        "--include-notes",
        action="store_true",
        help="Importér fritekstnoter bevidst; standard er dataminimering uden noter",
    )

    history_list = sub.add_parser("historik", help="List tidligere ansøgninger og udfald")
    history_list.add_argument("--fund-id", type=int)
    history_list.add_argument("--project-id")
    history_list.add_argument("--limit", type=int, default=100)

    outcome = sub.add_parser("opdater-resultat", help="Opdatér svar/bevilling for en indsendt ansøgning")
    outcome.add_argument("--history-id", required=True, type=int)
    outcome.add_argument("--status", required=True)
    outcome.add_argument("--decision-at")
    outcome.add_argument("--awarded-amount")
    outcome.add_argument("--notes")

    state = sub.add_parser("synkroniser-statens-puljer", help="Importér det officielle statslige CSV-feed")
    state.add_argument("--include-all-active", action="store_true")
    state.add_argument("--include-inactive", action="store_true")
    state.add_argument("--timeout", type=float, default=60.0)

    eu = sub.add_parser("synkroniser-eu", help="Importér åbne/kommende muligheder fra EU's officielle API")
    eu.add_argument("--include-all-open", action="store_true", help="Bevar alle åbne/kommende poster uden relevansfilter")
    eu.add_argument("--page-size", type=int, default=50)
    eu.add_argument("--max-pages", type=int, default=100)
    eu.add_argument("--delay", type=float, default=1.0)
    eu.add_argument("--timeout", type=float, default=60.0)

    public = sub.add_parser("synkroniser-kilder", help="Monitorér offentlige kilder fra kilderegisteret")
    public.add_argument("--source-id", action="append")
    public.add_argument("--max-pages", type=int, default=25)
    public.add_argument("--delay", type=float, default=1.25)
    public.add_argument("--timeout", type=float, default=30.0)

    club = sub.add_parser("synkroniser-fundraisingclub", help="Privat metadataindeks via eget abonnement")
    club.add_argument("--confirm-authorized-use", action="store_true", help="Bekræft egen adgang og tilladt automatiseret privat brug")
    club.add_argument("--start-url", action="append")
    club.add_argument("--max-pages", type=int, default=500)
    club.add_argument("--max-depth", type=int, default=3)
    club.add_argument("--delay", type=float, default=1.5)
    club.add_argument("--timeout", type=float, default=30.0)

    project = sub.add_parser("opret-projekt", help="Kopiér projektbrief-skabelonen til privat runtime-data")
    project.add_argument("--output", required=True)
    project.add_argument("--overwrite", action="store_true")

    project_validation = sub.add_parser("valider-projekt", help="Validér et projektbrief")
    project_validation.add_argument("--project", required=True)
    project_validation.add_argument("--stage", choices=("matching", "application"), default="matching")
    project_validation.add_argument("--as-of")

    matching = sub.add_parser("match", help="Beregn 0–100 matchscore")
    matching.add_argument("--project", required=True)
    matching.add_argument("--fund-id", action="append", type=int)
    matching.add_argument("--limit", type=int, default=10)
    matching.add_argument("--as-of")
    matching.add_argument("--include-blocked", action="store_true")
    matching.add_argument("--output")
    matching.add_argument("--overwrite", action="store_true")

    update_fund = sub.add_parser(
        "opdater-fond",
        help="Gem aktuelle officielle krav og kontroldato for én fond",
    )
    update_fund.add_argument("--fund-id", required=True, type=int)
    update_fund.add_argument("--requirements", required=True, help="Udfyldt requirements.json")

    batch = sub.add_parser("forbered-batch", help="Lav 1–10 separate ansøgningspakker")
    batch.add_argument("--project", required=True)
    batch.add_argument("--fund-id", action="append", type=int)
    batch.add_argument("--limit", type=int, default=10)
    batch.add_argument("--output")
    batch.add_argument("--as-of")
    batch.add_argument("--source-max-age-days", type=int, default=30)
    batch.add_argument("--confirm-ready", action="store_true", help="Brugeren har sagt at projektet er klar til fondsvalg og udkast")
    batch.add_argument("--overwrite", action="store_true")

    validate_batch = sub.add_parser("valider-batch", help="Kontrollér alle pakker, kilder og hashes")
    validate_batch.add_argument("--batch", required=True)
    validate_batch.add_argument("--as-of")
    validate_batch.add_argument("--source-max-age-days", type=int, default=30)
    validate_batch.add_argument("--require-approval", action="store_true")

    approve = sub.add_parser("godkend", help="Registrér intern godkendelse; indsender ikke")
    approve.add_argument("--batch", required=True)
    approve.add_argument("--fund-id", action="append", required=True, type=int)
    approve.add_argument("--approved-by", required=True)
    approve.add_argument("--approved-at")
    approve.add_argument("--as-of")
    approve.add_argument("--source-max-age-days", type=int, default=30)

    submitted = sub.add_parser("registrer-indsendelse", help="Log en allerede udført ekstern indsendelse")
    submitted.add_argument("--batch", required=True)
    submitted.add_argument("--fund-id", required=True, type=int)
    submitted.add_argument("--channel", required=True)
    submitted.add_argument("--reference", required=True)
    submitted.add_argument("--submitted-at")
    submitted.add_argument("--status", default="submitted")
    submitted.add_argument("--as-of")
    submitted.add_argument("--source-max-age-days", type=int, default=30)
    submitted.add_argument("--confirm-submitted", action="store_true")
    submitted.add_argument("--overwrite", action="store_true")
    return parser


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "initialiser": cmd_initialiser,
    "status": cmd_status,
    "genopbyg-indeks": cmd_genopbyg_indeks,
    "daekning": cmd_daekning,
    "liste": cmd_liste,
    "importer-regneark": cmd_importer_regneark,
    "synkroniser-dgi": cmd_synkroniser_dgi,
    "importer-historik": cmd_importer_historik,
    "historik": cmd_historik,
    "opdater-resultat": cmd_opdater_resultat,
    "synkroniser-statens-puljer": cmd_synkroniser_statens_puljer,
    "synkroniser-eu": cmd_synkroniser_eu,
    "synkroniser-kilder": cmd_synkroniser_kilder,
    "synkroniser-fundraisingclub": cmd_synkroniser_fundraisingclub,
    "opret-projekt": cmd_opret_projekt,
    "valider-projekt": cmd_valider_projekt,
    "match": cmd_match,
    "opdater-fond": cmd_opdater_fond,
    "forbered-batch": cmd_forbered_batch,
    "valider-batch": cmd_valider_batch,
    "godkend": cmd_godkend,
    "registrer-indsendelse": cmd_registrer_indsendelse,
}


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.action is None:
        parser.print_help()
        raise SystemExit(0)
    try:
        code = COMMANDS[args.action](args)
    except (
        BatchPreparationError,
        FileExistsError,
        HistoryDownloadError,
        ImportDependencyError,
        ImportFormatError,
        json.JSONDecodeError,
        KeyError,
        ProjectValidationError,
        OSError,
        ScrapeError,
        TypeError,
        ValueError,
    ) as exc:
        payload: dict[str, Any] = {
            "success": False,
            "error": exc.__class__.__name__,
            "message": str(exc),
        }
        details = getattr(exc, "errors", None)
        if details:
            payload["details"] = details
        if args.debug:
            payload["traceback"] = traceback.format_exc()
        _print(payload)
        code = 1
    except Exception as exc:  # pragma: no cover - last-resort secret-safe CLI boundary
        payload = {
            "success": False,
            "error": exc.__class__.__name__,
            "message": "Uventet fejl. Brug --debug lokalt; kontrollér at output ikke indeholder fortrolige data.",
        }
        if args.debug:
            payload["traceback"] = traceback.format_exc()
        _print(payload)
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
