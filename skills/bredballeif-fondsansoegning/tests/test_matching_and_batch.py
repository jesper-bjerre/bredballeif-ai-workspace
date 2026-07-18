from __future__ import annotations

from copy import deepcopy
from argparse import Namespace
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS = (
    Path(__file__).resolve().parents[1] / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

from batch_workflow import (  # noqa: E402
    BatchPreparationError,
    MAX_BATCH_SIZE,
    approve_application,
    contains_placeholders,
    prepare_application_batch,
    validate_batch_directory,
    verify_approval_hash,
    validate_requirement_research,
    _write_text,
)
from matching import MATCH_WEIGHTS, match_funds, score_fund, validate_project  # noqa: E402
from json_store import JsonFundStore as IndexStore  # noqa: E402
from agent import cmd_registrer_indsendelse  # noqa: E402


AS_OF = "2026-07-17"


def project(*, ready: bool = True) -> dict:
    return {
        "project_id": "nyt-faellesskab-2027",
        "title": "Nyt idrætsfællesskab",
        "need": "Flere børn i Bredballe skal have adgang til et lokalt idrætsfællesskab.",
        "purpose": ["idræt"],
        "target_groups": ["børn"],
        "geography": ["Bredballe", "Vejle Kommune"],
        "activities": ["ugentlig træning"],
        "eligible_expenses": ["idrætsudstyr"],
        "timeline": {"start": "2027-01-01", "end": "2027-12-31"},
        "budget": {
            "total_dkk": 150_000,
            "requested_dkk": 100_000,
            "own_financing_dkk": 50_000,
            "other_confirmed_dkk": 0,
            "other_pending_dkk": 0,
            "items": [{"category": "idrætsudstyr", "amount_dkk": 150_000}],
        },
        "multi_funding_strategy": {
            "mode": "alternatives",
            "max_total_grants_dkk": 100_000,
            "allocation_note": "Ansøgningerne er alternative finansieringsveje til samme udstyrspakke.",
            "overaward_plan": "Bestyrelsen reducerer eller afslår efterfølgende tilsagn, så samlet støtte højst er 100.000 kr.",
        },
        "organisation": {
            "name": "Bredballe Idrætsforening",
            "legal_form": "folkeoplysende idrætsforening",
            "cvr": "12345678",
        },
        "contact": {"name": "Test Kontakt", "email": "test@example.invalid"},
        "documentation_available": ["budget.pdf", "vedtaegter.pdf"],
        "outputs": ["40 deltagere"],
        "outcomes": ["flere aktive børn"],
        "measurement": "Deltagertal opgøres ved projektets afslutning",
        "continued_operation": "Foreningen indarbejder aktiviteten i den ordinære drift.",
        "ready_to_apply": ready,
    }


def fund(fund_id: int = 1, name: str = "Eksempelfonden", **overrides) -> dict:
    url = f"https://fond{fund_id}.example.org/pulje"
    record = {
        "fund_id": fund_id,
        "name": name,
        "url": url,
        "official_url": url,
        "type": "fond",
        "geography": ["Danmark"],
        "applicant_types": ["forening"],
        "purposes": ["idræt"],
        "target_groups": ["børn"],
        "amount": {"min": 25_000, "max": 250_000},
        "deadline": "2027-02-01",
        "requirements": {
            "official_source_url": url,
            "application_url": url,
            "project_id": "nyt-faellesskab-2027",
            "checked_at": AS_OF,
            "go_no_go": "go",
            "deadline": {
                "value": "2027-02-01",
                "rolling": False,
                "project_may_start_before_decision": True,
            },
            "amount": {
                "requested_dkk": 100_000,
                "minimum_dkk": 25_000,
                "maximum_dkk": 250_000,
                "cofinancing_required": True,
            },
            "eligible_expenses": ["idrætsudstyr"],
            "attachments": ["budget", "vedtægter"],
            "attachments_reviewed": True,
            "portal_fields": [
                {
                    "field": "Projektets formål",
                    "project_response": "Nyt lokalt idrætsfællesskab for børn",
                    "character_limit": 1000,
                },
                {
                    "field": "Budget",
                    "project_response": "Samlet budget 150.000 kr.; der søges 100.000 kr.",
                    "character_limit": None,
                },
            ],
            "portal_fields_reviewed": True,
            "source_documents": [
                {"kind": "program_page", "url": url, "checked_at": AS_OF},
                {"kind": "application_process", "url": url, "checked_at": AS_OF},
            ],
            "criteria": [
                {
                    "category": category,
                    "requirement": f"Dokumenteret krav for {category}",
                    "project_response": f"Projektets svar for {category}",
                    "satisfied": True,
                    "source_url": url,
                    "evidence_note": f"Kontrolleret afsnit om {category}",
                }
                for category in (
                    "applicant_eligibility",
                    "purpose_and_target_group",
                    "eligible_and_excluded_costs",
                    "deadline_and_project_period",
                    "attachments_and_formalia",
                )
            ],
        },
        "exclusions": [],
        "verification_status": "verified",
        "last_checked": AS_OF,
    }
    record.update(overrides)
    return record


class FakeStore:
    def __init__(self, funds: list[dict], prior_ids: set[int] | None = None):
        self.funds = {item["fund_id"]: deepcopy(item) for item in funds}
        self.prior_ids = prior_ids or set()

    def list_funds(self):
        return list(self.funds.values())

    def get_fund(self, fund_id):
        return deepcopy(self.funds.get(int(fund_id)))

    def has_prior_application(self, name=None, url_or_domain="", *, fund_id=None, project_id=None):
        if fund_id is not None:
            return int(fund_id) in self.prior_ids
        return any(item["name"] == name and key in self.prior_ids for key, item in self.funds.items())


class MatchingAndBatchTests(unittest.TestCase):
    def test_weights_and_perfect_score_are_exact_and_deterministic(self):
        self.assertEqual(
            MATCH_WEIGHTS,
            {
                "geography": 20,
                "purpose": 25,
                "target_groups": 15,
                "expenses": 15,
                "amount": 10,
                "deadline": 10,
                "documentation": 5,
            },
        )
        first = score_fund(project(), fund(), as_of=AS_OF)
        second = score_fund(project(), fund(), as_of=AS_OF)
        self.assertEqual(first, second)
        self.assertEqual(first["score"], 100)
        self.assertEqual(first["go_no_go"], "go")
        self.assertTrue(
            all(item["earned"] == item["maximum"] for item in first["breakdown"].values())
        )

    def test_project_validation_supports_nested_canonical_brief_and_reports_errors(self):
        valid = validate_project(project(), stage="application", as_of=AS_OF)
        self.assertTrue(valid["valid"])
        self.assertEqual(valid["project"]["requested_amount"], 100_000)
        self.assertEqual(
            valid["project"]["applicant"]["type"], "folkeoplysende idrætsforening"
        )

        broken = project()
        broken["budget"]["requested_dkk"] = 200_000
        invalid = validate_project(broken, stage="matching", as_of=AS_OF)
        self.assertFalse(invalid["valid"])
        self.assertIn("amount_exceeds_budget", {error["code"] for error in invalid["errors"]})

    def test_hard_blockers_are_separate_from_score(self):
        cases = [
            ({"geography": ["Bornholm"]}, None, "geography_mismatch"),
            ({"amount": {"max": 50_000}}, None, "amount_above_maximum"),
            ({"deadline": "2026-07-16"}, None, "deadline_passed"),
            ({"verification_status": "closed"}, None, "fund_closed"),
            (
                {"requirements": {**fund()["requirements"], "go_no_go": "no_go"}},
                None,
                "official_no_go",
            ),
            ({"type": "funding directory"}, None, "directory_not_program"),
            ({}, True, "prior_application"),
        ]
        for changes, history, blocker in cases:
            with self.subTest(blocker=blocker):
                result = score_fund(project(), fund(**changes), as_of=AS_OF, history=history)
                self.assertIn(blocker, result["hard_blockers"])
                self.assertEqual(result["go_no_go"], "no_go")
                self.assertFalse(result["eligible"])
                self.assertLessEqual(result["score"], 100)
                self.assertGreaterEqual(result["score"], 0)

    def test_danish_geography_and_abbreviated_amount_units_are_parsed(self):
        for amount in ("Op til 5 mio. kr.", "Op til 250 tkr.", "25.000–250.000 kr."):
            with self.subTest(amount=amount):
                result = score_fund(
                    project(),
                    fund(amount=amount, geography=["Landsdækkende"]),
                    as_of=AS_OF,
                )
                self.assertNotIn("amount_above_maximum", result["hard_blockers"])
                self.assertNotIn("geography_mismatch", result["hard_blockers"])
                self.assertEqual(result["breakdown"]["geography"]["earned"], 20)

    def test_application_validation_rejects_invalid_identity_effect_and_budget(self):
        broken = project()
        broken["organisation"]["cvr"] = "x"
        broken["contact"]["email"] = "ikke-en-mail"
        broken["outputs"] = []
        broken["budget"]["items"][0]["amount_dkk"] = 140_000
        broken["budget"]["own_financing_dkk"] = 0
        result = validate_project(broken, stage="application", as_of=AS_OF)
        self.assertFalse(result["valid"])
        codes = {item["code"] for item in result["errors"]}
        self.assertTrue(
            {"invalid_cvr", "invalid_email", "missing_field", "budget_items_mismatch", "financing_plan_mismatch"}
            <= codes
        )

    def test_application_validation_rejects_invalid_and_negative_budget_items(self):
        broken = project()
        broken["budget"]["items"] = [
            {"category": "udstyr", "amount_dkk": 150_000},
            {"category": "ukendt", "amount_dkk": "IKKE-ET-BELØB"},
        ]
        invalid = validate_project(broken, stage="application", as_of=AS_OF)
        self.assertFalse(invalid["valid"])
        self.assertIn("budget_item_invalid_amount", {item["code"] for item in invalid["errors"]})

        broken["budget"]["items"] = [
            {"category": "udstyr", "amount_dkk": 160_000},
            {"category": "rabat", "amount_dkk": -10_000},
        ]
        negative = validate_project(broken, stage="application", as_of=AS_OF)
        self.assertFalse(negative["valid"])
        self.assertIn("budget_item_negative_amount", {item["code"] for item in negative["errors"]})

    def test_match_funds_uses_store_history_and_stable_ranking(self):
        store = FakeStore(
            [
                fund(2, "B-fonden", purposes=["kultur"]),
                fund(1, "A-fonden"),
                fund(3, "C-fonden"),
            ],
            prior_ids={3},
        )
        matches = match_funds(store, project(), as_of=AS_OF)
        self.assertEqual([item["fund_id"] for item in matches], [1, 2, 3])
        self.assertEqual(matches[-1]["hard_blockers"], ["prior_application"])

    def test_unknown_project_history_warns_without_hard_blocking(self):
        result = score_fund(
            project(),
            fund(),
            as_of=AS_OF,
            history={
                "has_prior_application": False,
                "has_any_prior_application": True,
                "has_unknown_project_history": True,
                "count": 1,
            },
        )
        self.assertNotIn("prior_application", result["hard_blockers"])
        self.assertTrue(result["history_warning"])

    def test_closed_requirement_research_can_be_recorded_but_not_applied(self):
        url = "https://lukket.example/pulje"
        closed = {
            "fund_id": 1,
            "official_source_url": url,
            "application_url": "",
            "checked_at": AS_OF,
            "status": "closed",
            "go_no_go": "no_go",
            "go_no_go_reason": "Puljen er officielt lukket",
            "hard_blockers": ["fund_closed"],
            "source_documents": [
                {"kind": "program_page", "url": url, "checked_at": AS_OF}
            ],
        }
        self.assertTrue(
            validate_requirement_research(closed, allow_no_go=True)["valid"]
        )
        self.assertFalse(validate_requirement_research(closed)["valid"])

    def test_requirement_research_requires_dates_start_rule_answers_and_safe_urls(self):
        cases = {}
        invalid_deadline = deepcopy(fund()["requirements"])
        invalid_deadline["deadline"]["value"] = "snarest"
        cases["research_deadline_invalid"] = invalid_deadline

        missing_start_rule = deepcopy(fund()["requirements"])
        missing_start_rule["deadline"].pop("project_may_start_before_decision")
        cases["project_start_rule_missing"] = missing_start_rule

        missing_response = deepcopy(fund()["requirements"])
        missing_response["criteria"][0]["project_response"] = ""
        cases["research_project_response_missing"] = missing_response

        flat_portal_field = deepcopy(fund()["requirements"])
        flat_portal_field["portal_fields"] = ["Projektets formål"]
        cases["portal_field_not_structured"] = flat_portal_field

        unsafe_url = deepcopy(fund()["requirements"])
        unsafe_url["application_url"] = "https://user:secret@fond1.example.org/apply"
        cases["missing_application_url"] = unsafe_url

        http_url = deepcopy(fund()["requirements"])
        http_url["official_source_url"] = "http://fond1.example.org/pulje"
        cases["missing_research_official_url"] = http_url

        future_research = deepcopy(fund()["requirements"])
        future_research["checked_at"] = "2026-07-18"
        cases["research_checked_at_in_future"] = future_research

        missing_source_date = deepcopy(fund()["requirements"])
        missing_source_date["source_documents"][0].pop("checked_at")
        cases["research_source_checked_at_missing"] = missing_source_date

        future_source_date = deepcopy(fund()["requirements"])
        future_source_date["source_documents"][0]["checked_at"] = "2026-07-18"
        cases["research_source_checked_at_in_future"] = future_source_date

        portal_response_too_long = deepcopy(fund()["requirements"])
        portal_response_too_long["portal_fields"][0]["project_response"] = "for langt"
        portal_response_too_long["portal_fields"][0]["character_limit"] = 3
        cases["portal_field_response_too_long"] = portal_response_too_long

        for expected_code, requirements in cases.items():
            with self.subTest(expected_code=expected_code):
                result = validate_requirement_research(requirements, as_of=AS_OF)
                self.assertFalse(result["valid"])
                self.assertIn(expected_code, {item["code"] for item in result["errors"]})

    def test_batch_requires_ready_and_enforces_max_ten(self):
        store = FakeStore([fund()])
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(BatchPreparationError, "ikke markeret ansøgningsklart"):
                prepare_application_batch(store, project(ready=False), temp_dir, as_of=AS_OF)
            with self.assertRaisesRegex(BatchPreparationError, "højst"):
                prepare_application_batch(
                    store,
                    project(),
                    temp_dir,
                    fund_ids=list(range(MAX_BATCH_SIZE + 1)),
                    ready=True,
                    as_of=AS_OF,
                )

    def test_private_batch_writer_rejects_symlink_destination(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "approval.json"
            with patch.object(Path, "is_symlink", return_value=True):
                with self.assertRaisesRegex(BatchPreparationError, "symlink"):
                    _write_text(target, "{}\n", overwrite=True)

    def test_batch_writes_fund_specific_files_and_verifiable_hashes(self):
        store = FakeStore([fund(1, "Den Første Fond"), fund(2, "Den Anden Fond")])
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = prepare_application_batch(
                store,
                project(),
                temp_dir,
                fund_ids=[1, 2],
                ready=True,
                as_of=AS_OF,
            )
            self.assertEqual(manifest["count"], 2)
            self.assertFalse(manifest["network_action_performed"])
            self.assertTrue((Path(temp_dir) / "project.json").is_file())
            applications = []
            for item in manifest["applications"]:
                folder = Path(item["folder"])
                self.assertTrue(
                    {
                        "requirements.json",
                        "application.md",
                        "approval.json",
                        "fund.json",
                        "match.json",
                    }.issubset({path.name for path in folder.iterdir()})
                )
                requirements = json.loads(
                    (folder / "requirements.json").read_text(encoding="utf-8")
                )
                application = (folder / "application.md").read_text(encoding="utf-8")
                approval = json.loads((folder / "approval.json").read_text(encoding="utf-8"))
                self.assertEqual(requirements["go_no_go"], "go")
                self.assertTrue(requirements["amount"]["cofinancing_required"])
                self.assertEqual(requirements["amount"]["minimum_dkk"], 25_000)
                self.assertIn(requirements["fund_name"], application)
                self.assertFalse(contains_placeholders(requirements))
                self.assertFalse(contains_placeholders(application))
                self.assertTrue(verify_approval_hash(requirements, application, approval))
                self.assertFalse(approval["submission"]["network_action_performed"])
                applications.append(application)
            self.assertNotEqual(
                hashlib.sha256(applications[0].encode()).digest(),
                hashlib.sha256(applications[1].encode()).digest(),
            )
            batch = json.loads((Path(temp_dir) / "batch.json").read_text(encoding="utf-8"))
            self.assertEqual(batch["multi_funding_strategy"]["sum_requested_dkk"], 200_000)

    def test_multi_fund_batch_requires_double_funding_strategy(self):
        store = FakeStore([fund(1), fund(2)])
        missing_strategy = project()
        missing_strategy.pop("multi_funding_strategy")
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(BatchPreparationError, "dobbeltfinansieringsstrategi"):
                prepare_application_batch(
                    store,
                    missing_strategy,
                    temp_dir,
                    fund_ids=[1, 2],
                    ready=True,
                    as_of=AS_OF,
                )

    def test_batch_rejects_fund_amount_bounds_and_project_financing_overreach(self):
        above_fund_max = fund()
        above_fund_max["requirements"]["amount"]["requested_dkk"] = 300_000
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(BatchPreparationError) as caught:
                prepare_application_batch(
                    FakeStore([above_fund_max]),
                    project(),
                    temp_dir,
                    fund_ids=[1],
                    ready=True,
                    as_of=AS_OF,
                )
        self.assertIn(
            "research_requested_above_maximum",
            {item["code"] for item in caught.exception.errors},
        )

        above_project_need = fund(amount={"min": 25_000, "max": 400_000})
        above_project_need["requirements"]["amount"].update(
            {"requested_dkk": 120_000, "maximum_dkk": 400_000}
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(BatchPreparationError) as caught:
                prepare_application_batch(
                    FakeStore([above_project_need]),
                    project(),
                    temp_dir,
                    fund_ids=[1],
                    ready=True,
                    as_of=AS_OF,
                )
        self.assertIn(
            "package_amount_exceeds_financing_need",
            {item["code"] for item in caught.exception.errors},
        )

    def test_batch_can_be_validated_and_approved_without_network(self):
        store = FakeStore([fund()])
        with tempfile.TemporaryDirectory() as temp_dir:
            prepare_application_batch(
                store,
                project(),
                temp_dir,
                fund_ids=[1],
                ready=True,
                as_of=AS_OF,
            )
            before = validate_batch_directory(temp_dir, store=store, as_of=AS_OF)
            self.assertTrue(before["valid"], before["errors"])
            self.assertFalse(before["applications"][0]["approved"])
            approval = approve_application(
                temp_dir,
                1,
                "Bestyrelsen",
                "2026-07-17T12:00:00+02:00",
                store=store,
                as_of=AS_OF,
            )
            self.assertEqual(approval["status"], "approved")
            self.assertFalse(approval["network_action_performed"])
            after = validate_batch_directory(
                temp_dir,
                store=store,
                as_of=AS_OF,
                require_approval=True,
            )
            self.assertTrue(after["valid"], after["errors"])

    def test_manual_approval_edit_without_timestamp_cannot_pass_gate(self):
        store = FakeStore([fund()])
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = prepare_application_batch(
                store, project(), temp_dir, fund_ids=[1], ready=True, as_of=AS_OF
            )
            folder = Path(manifest["applications"][0]["folder"])
            approval_path = folder / "approval.json"
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            approval["status"] = "approved"
            approval["approved_by"] = "Manuel redigering"
            approval_path.write_text(json.dumps(approval), encoding="utf-8")

            validation = validate_batch_directory(
                temp_dir, store=store, as_of=AS_OF, require_approval=True
            )
            self.assertFalse(validation["valid"])
            codes = {item["code"] for item in validation["errors"]}
            self.assertIn("approval_metadata_invalid", codes)
            self.assertIn("approval_required", codes)

    def test_package_identity_mismatch_blocks_validation_and_approval(self):
        store = FakeStore([fund()])
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = prepare_application_batch(
                store, project(), temp_dir, fund_ids=[1], ready=True, as_of=AS_OF
            )
            folder = Path(manifest["applications"][0]["folder"])
            requirements_path = folder / "requirements.json"
            requirements = json.loads(requirements_path.read_text(encoding="utf-8"))
            requirements["fund_id"] = 999
            requirements["fund_name"] = "Forkert fond"
            requirements["project_id"] = "forkert-projekt"
            requirements_path.write_text(json.dumps(requirements), encoding="utf-8")

            validation = validate_batch_directory(temp_dir, store=store, as_of=AS_OF)
            self.assertFalse(validation["valid"])
            codes = {item["code"] for item in validation["errors"]}
            self.assertTrue(
                {
                    "package_fund_id_mismatch",
                    "package_fund_name_mismatch",
                    "package_project_id_mismatch",
                }
                <= codes
            )
            with self.assertRaises(BatchPreparationError):
                approve_application(
                    temp_dir,
                    1,
                    "Bestyrelsen",
                    "2026-07-17T12:00:00+02:00",
                    store=store,
                    as_of=AS_OF,
                )

    def test_changed_package_amount_invalidates_financing_plan(self):
        store = FakeStore([fund()])
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = prepare_application_batch(
                store, project(), temp_dir, fund_ids=[1], ready=True, as_of=AS_OF
            )
            folder = Path(manifest["applications"][0]["folder"])
            requirements_path = folder / "requirements.json"
            requirements = json.loads(requirements_path.read_text(encoding="utf-8"))
            requirements["amount"]["requested_dkk"] = 90_000
            requirements_path.write_text(json.dumps(requirements), encoding="utf-8")
            validation = validate_batch_directory(temp_dir, store=store, as_of=AS_OF)
            self.assertFalse(validation["valid"])
            self.assertIn(
                "package_financing_plan_mismatch",
                {item["code"] for item in validation["errors"]},
            )

    def test_application_requested_amount_must_match_requirements_before_approval(self):
        store = FakeStore([fund()])
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = prepare_application_batch(
                store, project(), temp_dir, fund_ids=[1], ready=True, as_of=AS_OF
            )
            folder = Path(manifest["applications"][0]["folder"])
            application_path = folder / "application.md"
            application = application_path.read_text(encoding="utf-8")
            self.assertIn("100.000", application)
            application_path.write_text(
                application.replace("100.000", "90.000"),
                encoding="utf-8",
            )

            validation = validate_batch_directory(temp_dir, store=store, as_of=AS_OF)
            self.assertFalse(validation["valid"])
            self.assertIn(
                "application_requested_amount_mismatch",
                {item["code"] for item in validation["errors"]},
            )
            with self.assertRaises(BatchPreparationError) as caught:
                approve_application(
                    temp_dir,
                    1,
                    "Bestyrelsen",
                    "2026-07-17T12:00:00+02:00",
                    store=store,
                    as_of=AS_OF,
                )
            self.assertIn(
                "application_requested_amount_mismatch",
                {item["code"] for item in caught.exception.errors},
            )

    def test_multi_funding_strategy_and_amounts_are_recomputed_during_validation(self):
        funds = [fund(1), fund(2)]
        for item in funds:
            item["requirements"]["amount"]["requested_dkk"] = 50_000
            item["requirements"]["portal_fields"][1]["project_response"] = (
                "Samlet budget 150.000 kr.; der søges 50.000 kr."
            )
        project_data = project()
        project_data["multi_funding_strategy"]["mode"] = "complementary"
        store = FakeStore(funds)

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = prepare_application_batch(
                store,
                project_data,
                temp_dir,
                fund_ids=[1, 2],
                ready=True,
                as_of=AS_OF,
            )
            initial = validate_batch_directory(temp_dir, store=store, as_of=AS_OF)
            self.assertTrue(initial["valid"], initial["errors"])

            manifest_path = Path(temp_dir) / "batch.json"
            batch = json.loads(manifest_path.read_text(encoding="utf-8"))
            original_allocation = batch["multi_funding_strategy"]["allocation_note"]
            batch["multi_funding_strategy"]["allocation_note"] = "Ændret kun i manifestet"
            manifest_path.write_text(json.dumps(batch), encoding="utf-8")
            mismatch = validate_batch_directory(temp_dir, store=store, as_of=AS_OF)
            self.assertIn(
                "multi_funding_strategy_mismatch",
                {item["code"] for item in mismatch["errors"]},
            )

            batch["multi_funding_strategy"]["allocation_note"] = original_allocation
            batch["multi_funding_strategy"]["sum_requested_dkk"] = 120_000
            manifest_path.write_text(json.dumps(batch), encoding="utf-8")
            for item in manifest["applications"]:
                folder = Path(item["folder"])
                requirements_path = folder / "requirements.json"
                requirements = json.loads(requirements_path.read_text(encoding="utf-8"))
                requirements["amount"]["requested_dkk"] = 60_000
                requirements["amount"]["project_financing"].update(
                    {
                        "this_fund_requested_dkk": 60_000,
                        "remaining_financing_to_secure_dkk": 40_000,
                    }
                )
                requirements["portal_fields"][1]["project_response"] = (
                    "Samlet budget 150.000 kr.; der søges 60.000 kr."
                )
                requirements_path.write_text(json.dumps(requirements), encoding="utf-8")

                application_path = folder / "application.md"
                application = application_path.read_text(encoding="utf-8")
                application = application.replace(
                    "Der søges 50.000 kr.", "Der søges 60.000 kr."
                ).replace("der søges 50.000 kr.", "der søges 60.000 kr.")
                application = application.replace(
                    "Den resterende finansiering, der skal sikres, er 50.000 kr.",
                    "Den resterende finansiering, der skal sikres, er 40.000 kr.",
                )
                application_path.write_text(application, encoding="utf-8")

                approval_path = folder / "approval.json"
                approval = json.loads(approval_path.read_text(encoding="utf-8"))
                approval["submission"]["requested_amount_dkk"] = 60_000
                approval["submission"]["history_record_after_submission"][
                    "amount_requested"
                ] = 60_000
                approval_path.write_text(json.dumps(approval), encoding="utf-8")

            excessive = validate_batch_directory(temp_dir, store=store, as_of=AS_OF)
            codes = {item["code"] for item in excessive["errors"]}
            self.assertIn("multi_funding_amount_exceeds_cap", codes)
            self.assertNotIn("multi_funding_sum_mismatch", codes)

    def test_submission_registration_is_idempotent_and_rejects_changed_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store_path = root / "runtime" / "store"
            batch_path = root / "batch"
            with IndexStore(store_path) as store:
                fund_id = store.upsert_fund(fund())
                self.assertEqual(fund_id, 1)
                prepare_application_batch(
                    store,
                    project(),
                    batch_path,
                    fund_ids=[1],
                    ready=True,
                    as_of=AS_OF,
                )
                approve_application(
                    batch_path,
                    1,
                    "Bestyrelsen",
                    "2026-07-17T12:00:00+02:00",
                    store=store,
                    as_of=AS_OF,
                )

            args = Namespace(
                confirm_submitted=True,
                batch=str(batch_path),
                fund_id=1,
                channel="fondsportal",
                reference="KVIT-001",
                submitted_at="2026-07-17T13:00:00+02:00",
                status="submitted",
                overwrite=False,
                as_of=AS_OF,
                source_max_age_days=30,
                data_dir=str(root / "runtime"),
                store=str(store_path),
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_registrer_indsendelse(args), 0)
                self.assertEqual(cmd_registrer_indsendelse(args), 0)
            with IndexStore(store_path) as store:
                history = store.list_history()
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["status"], "submitted")

            changed = Namespace(**vars(args))
            changed.channel = "anden-kanal"
            with self.assertRaisesRegex(FileExistsError, "andre indsendelsesmetadata"):
                with redirect_stdout(io.StringIO()):
                    cmd_registrer_indsendelse(changed)

    def test_edited_pending_draft_is_bound_to_new_hash_on_approval(self):
        store = FakeStore([fund()])
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = prepare_application_batch(
                store,
                project(),
                temp_dir,
                fund_ids=[1],
                ready=True,
                as_of=AS_OF,
            )
            folder = Path(manifest["applications"][0]["folder"])
            application_path = folder / "application.md"
            application_path.write_text(
                application_path.read_text(encoding="utf-8")
                + "\nFondsspecifik redaktionel tilføjelse.\n",
                encoding="utf-8",
            )

            pending = validate_batch_directory(temp_dir, store=store, as_of=AS_OF)
            self.assertTrue(pending["valid"], pending["errors"])
            self.assertTrue(pending["applications"][0]["pending_hash_refresh"])

            approval = approve_application(
                temp_dir,
                1,
                "Bestyrelsen",
                "2026-07-17T12:00:00+02:00",
                store=store,
                as_of=AS_OF,
            )
            requirements = json.loads(
                (folder / "requirements.json").read_text(encoding="utf-8")
            )
            application = application_path.read_text(encoding="utf-8")
            self.assertTrue(verify_approval_hash(requirements, application, approval))
            final = validate_batch_directory(
                temp_dir,
                store=store,
                as_of=AS_OF,
                require_approval=True,
            )
            self.assertTrue(final["valid"], final["errors"])

    def test_approved_batch_is_invalidated_when_indexed_fund_requirements_change(self):
        store = FakeStore([fund()])
        with tempfile.TemporaryDirectory() as temp_dir:
            prepare_application_batch(
                store,
                project(),
                temp_dir,
                fund_ids=[1],
                ready=True,
                as_of=AS_OF,
            )
            approve_application(
                temp_dir,
                1,
                "Bestyrelsen",
                "2026-07-17T12:00:00+02:00",
                store=store,
                as_of=AS_OF,
            )
            changed = store.funds[1]
            changed["deadline"] = "2027-03-01"
            changed["requirements"]["deadline"] = {
                "value": "2027-03-01",
                "rolling": False,
            }
            changed["requirements"]["attachments"].append("bestyrelsesreferat")

            result = validate_batch_directory(
                temp_dir,
                store=store,
                as_of=AS_OF,
                require_approval=True,
            )
            self.assertFalse(result["valid"])
            self.assertIn(
                "fund_requirements_changed",
                {item["code"] for item in result["errors"]},
            )

    def test_batch_rejects_stale_source_and_custom_template_placeholders(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stale_store = FakeStore([fund(last_checked="2026-01-01")])
            with self.assertRaisesRegex(BatchPreparationError, "ikke klar") as stale:
                prepare_application_batch(
                    stale_store,
                    project(),
                    Path(temp_dir) / "stale",
                    fund_ids=[1],
                    ready=True,
                    as_of=AS_OF,
                )
            self.assertIn("stale_official_source", {item["code"] for item in stale.exception.errors})

            store = FakeStore([fund()])
            bad_template = (
                "# {PROJECT_TITLE} til {FUND_NAME}\n\n{OFFICIAL_URL}\n\n{{UNRESOLVED}}\n"
                + ("tekst " * 80)
            )
            with self.assertRaisesRegex(BatchPreparationError, "kvalitetskontrollen") as placeholders:
                prepare_application_batch(
                    store,
                    project(),
                    Path(temp_dir) / "placeholder",
                    fund_ids=[1],
                    ready=True,
                    as_of=AS_OF,
                    application_template=bad_template,
                )
            self.assertIn(
                "application_placeholders",
                {item["code"] for item in placeholders.exception.errors},
            )

    def test_batch_rejects_unstructured_index_summary_as_requirement_research(self):
        weak = fund(requirements="Se reglerne på hjemmesiden")
        store = FakeStore([weak])
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(BatchPreparationError, "ikke klar") as caught:
                prepare_application_batch(
                    store,
                    project(),
                    temp_dir,
                    fund_ids=[1],
                    ready=True,
                    as_of=AS_OF,
                )
        codes = {item["code"] for item in caught.exception.errors}
        self.assertIn("missing_research_official_url", codes)
        self.assertIn("research_criterion_missing", codes)
        self.assertIn("portal_fields_not_reviewed", codes)


if __name__ == "__main__":
    unittest.main()
