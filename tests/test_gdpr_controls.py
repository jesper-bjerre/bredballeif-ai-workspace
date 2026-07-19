from __future__ import annotations

import unittest
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.gdpr_controls import (
    ApprovalContext,
    DataClassification,
    PolicyViolation,
    Provider,
    SkillPolicy,
    TestScope,
    assert_model_payload_allowed,
    audit_event,
    enforce_record_limit,
    minimize_member,
    redact_sensitive_data,
    reject_broad_query,
    validate_provider_route,
)


class ProviderPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.personal = SkillPolicy("personal-skill", (DataClassification.PERSONAL,))
        self.registry = {
            "tensorx-eu": Provider("tensorx-eu", "EU", True, True, True),
            "non-eu": Provider("non-eu", "CN", True, True, True),
            "unapproved-eu": Provider("unapproved-eu", "EU", False, True, True),
        }

    def test_personal_accepts_verified_eu_provider(self) -> None:
        route = validate_provider_route(self.personal, "tensorx-eu", [], self.registry)
        self.assertEqual(route[0].name, "tensorx-eu")

    def test_personal_rejects_non_eu_provider(self) -> None:
        with self.assertRaises(PolicyViolation):
            validate_provider_route(self.personal, "non-eu", [], self.registry)

    def test_personal_rejects_unknown_provider(self) -> None:
        with self.assertRaises(PolicyViolation):
            validate_provider_route(self.personal, "unknown", [], self.registry)

    def test_personal_rejects_non_eu_fallback_and_fails_closed(self) -> None:
        with self.assertRaises(PolicyViolation):
            validate_provider_route(self.personal, "tensorx-eu", ["non-eu"], self.registry)

    def test_personal_rejects_unapproved_provider(self) -> None:
        with self.assertRaises(PolicyViolation):
            validate_provider_route(self.personal, "unapproved-eu", [], self.registry)

    def test_internal_rejects_primary_outside_allowed_regions(self) -> None:
        internal = SkillPolicy("internal-skill", (DataClassification.INTERNAL,), allowed_regions=("EU",))
        with self.assertRaises(PolicyViolation):
            validate_provider_route(internal, "non-eu", [], self.registry)

    def test_public_can_use_explicitly_allowed_non_eu_primary_without_fallback(self) -> None:
        public = SkillPolicy("public-skill", (DataClassification.PUBLIC,), allowed_regions=("CN",))
        route = validate_provider_route(public, "non-eu", [], self.registry)
        self.assertEqual(route[0].region, "CN")

    def test_missing_allowed_regions_fails_closed(self) -> None:
        policy = SkillPolicy("invalid-route", (DataClassification.PUBLIC,), allowed_regions=())
        with self.assertRaises(PolicyViolation):
            validate_provider_route(policy, "tensorx-eu", [], self.registry)


class PayloadTests(unittest.TestCase):
    def test_secret_data_is_rejected(self) -> None:
        with self.assertRaises(PolicyViolation):
            assert_model_payload_allowed(DataClassification.PERSONAL, {"api_key": "synthetic-secret"})

    def test_sensitive_data_is_rejected_by_default(self) -> None:
        with self.assertRaises(PolicyViolation):
            assert_model_payload_allowed(DataClassification.SENSITIVE, {"status": "syntetisk"})

    def test_member_is_minimized_and_forbidden_fields_are_removed(self) -> None:
        source = {
            "id": "TEST-001",
            "fornavn": "Test",
            "status": "aktiv",
            "afdeling": "SYSTEMTEST",
            "email": "synthetic@example.invalid",
            "adresse": "Syntetisk vej 1",
            "foedselsdato": "2000-01-01",
            "notes": "syntetisk note",
        }
        result = minimize_member(source, ("member_id", "first_name", "membership_status", "department"))
        self.assertEqual(
            result,
            {
                "member_id": "TEST-001",
                "first_name": "Test",
                "membership_status": "aktiv",
                "department": "SYSTEMTEST",
            },
        )
        self.assertNotIn("email", result)
        self.assertNotIn("notes", result)


class LoggingTests(unittest.TestCase):
    def test_common_personal_and_secret_values_are_redacted(self) -> None:
        value = {
            "email": "synthetic@example.invalid",
            "phone": "+45 12 34 56 78",
            "api_key": "synthetic-key",
            "Authorization": "Bearer synthetic-token",
            "message": "Kontakt synthetic@example.invalid på 12 34 56 78",
        }
        redacted = redact_sensitive_data(value)
        rendered = repr(redacted)
        for forbidden in ("synthetic@example.invalid", "12 34 56 78", "synthetic-key", "synthetic-token"):
            self.assertNotIn(forbidden, rendered)

    def test_member_object_is_not_logged_raw(self) -> None:
        redacted = redact_sensitive_data({"member": {"navn": "Test Person", "email": "test@example.invalid"}})
        self.assertEqual(redacted["member"], "[REDACTED_PERSONAL]")


class QueryAndApprovalTests(unittest.TestCase):
    def test_default_record_limit_is_enforced(self) -> None:
        with self.assertRaises(PolicyViolation):
            enforce_record_limit(list(range(11)))

    def test_caller_cannot_raise_limit_without_bulk_approval(self) -> None:
        with self.assertRaises(PolicyViolation):
            enforce_record_limit(list(range(5)), limit=100)

    def test_bulk_extraction_requires_approval(self) -> None:
        approved = enforce_record_limit(list(range(11)), limit=11, bulk_approved=True)
        self.assertEqual(len(approved), 11)

    def test_empty_and_broad_queries_are_rejected(self) -> None:
        for query in ("", "*", "all", "a"):
            with self.subTest(query=query), self.assertRaises(PolicyViolation):
                reject_broad_query(query)

    def test_write_requires_current_scoped_approval(self) -> None:
        now = datetime.now(timezone.utc)
        context = ApprovalContext(
            frozenset({"member.update"}),
            "padel-admin",
            "TEST-CORRELATION-001",
            now + timedelta(minutes=5),
            True,
        )
        context.require("member.update", now=now)
        with self.assertRaises(PolicyViolation):
            context.require("member.delete", now=now)

    def test_expired_write_approval_is_rejected(self) -> None:
        now = datetime.now(timezone.utc)
        context = ApprovalContext(
            frozenset({"member.update"}),
            "padel-admin",
            "TEST-CORRELATION-001",
            now - timedelta(seconds=1),
            True,
        )
        with self.assertRaises(PolicyViolation):
            context.require("member.update", now=now)

    def test_read_operation_does_not_need_write_approval(self) -> None:
        records = enforce_record_limit([{"id": "TEST-001"}])
        self.assertEqual(len(records), 1)

    def test_mass_write_requires_separate_action(self) -> None:
        now = datetime.now(timezone.utc)
        context = ApprovalContext(
            frozenset({"member.update"}),
            "padel-admin",
            "TEST-CORRELATION-001",
            now + timedelta(minutes=5),
            True,
        )
        with self.assertRaises(PolicyViolation):
            context.require("member.bulk-update", now=now)

    def test_audit_event_contains_metadata_not_payload(self) -> None:
        event = audit_event(
            "member.update",
            "approved",
            record_count=1,
            actor_role="padel-admin",
            correlation_id="TEST-CORRELATION-001",
        )
        self.assertEqual(event["recordCount"], 1)
        self.assertNotIn("member", event)

    def test_testmode_restricts_member_and_department(self) -> None:
        scope = TestScope(frozenset({"TEST-001"}), frozenset({"SYSTEMTEST"}))
        scope.require_member("TEST-001")
        scope.require_department("SYSTEMTEST")
        with self.assertRaises(PolicyViolation):
            scope.require_member("REAL-001")


class PolicyManifestTests(unittest.TestCase):
    def test_every_manifest_skill_has_fail_closed_policy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "skills.manifest.json").read_text(encoding="utf-8"))
        policies = json.loads((root / "config" / "gdpr-skill-policies.json").read_text(encoding="utf-8"))
        expected = {item["name"] for item in manifest["skills"]}
        actual = set(policies["skills"])
        self.assertEqual(actual, expected)
        self.assertEqual(policies["defaults"]["unknown_provider_behavior"], "DENY")
        self.assertEqual(
            policies["defaults"]["classification_mode"],
            "HIGHEST_ACTUAL_INVOCATION_PAYLOAD",
        )
        self.assertFalse(policies["defaults"]["allow_non_eu_fallback"])
        for policy in policies["skills"].values():
            self.assertLessEqual(policy["max_records"], 10)
            self.assertFalse(policy["allow_non_eu_fallback"])


class WrapperPolicyTests(unittest.TestCase):
    CASES = {
        "bredballeif-padel-baner": ("book-court",),
        "bredballeif-padel-conventus": ("create-americano", "create-mexicano", "create-group"),
        "bredballeif-padel-halbooking": (
            "discover", "create", "onboard", "export", "welcome-email", "process-emails", "book-court",
        ),
        "bredballeif-padel-onboarding": (
            "discover", "create", "onboard", "export", "welcome-email", "process-emails", "book-court",
        ),
    }

    def test_read_wrappers_do_not_allow_write_or_bulk_actions(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for skill, actions in self.CASES.items():
            for suffix in ("sh", "ps1"):
                with self.subTest(skill=skill, suffix=suffix):
                    path = root / "skills" / skill / "bin" / f"{skill}.{suffix}"
                    content = path.read_text(encoding="utf-8")
                    marker = "-h|--help" if suffix == "sh" else "$AllowedActions"
                    allowlist = next((line for line in content.splitlines() if marker in line), content)
                    for action in actions:
                        self.assertNotIn(action, allowlist)

    def test_admin_wrappers_only_expose_explicit_approval_gated_actions(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for skill, actions in self.CASES.items():
            for suffix in ("sh", "ps1"):
                with self.subTest(skill=skill, suffix=suffix):
                    path = root / "skills" / skill / "bin" / f"{skill}-admin.{suffix}"
                    content = path.read_text(encoding="utf-8")
                    for action in actions:
                        self.assertIn(action, content)
                    self.assertRegex(content.lower(), r"approval|godkend")


class RepositorySafetyIntegrationTests(unittest.TestCase):
    def test_browser_screenshots_are_explicit_opt_in(self) -> None:
        root = Path(__file__).resolve().parents[1]
        paths = (
            "skills/bredballeif-padel-baner/scripts/halbooking_automation.py",
            "skills/bredballeif-padel-conventus/scripts/conventus_group_automation.py",
            "skills/bredballeif-padel-halbooking/scripts/halbooking_automation.py",
            "skills/bredballeif-padel-onboarding/scripts/halbooking_automation.py",
        )
        for relative in paths:
            with self.subTest(path=relative):
                content = (root / relative).read_text(encoding="utf-8")
                self.assertIn("BIF_ALLOW_DIAGNOSTIC_SCREENSHOTS", content)
                self.assertIn("if not DIAGNOSTIC_SCREENSHOTS_ENABLED", content)

    def test_raw_halbooking_html_is_not_persisted(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for skill in ("bredballeif-padel-halbooking", "bredballeif-padel-onboarding"):
            content = (
                root / "skills" / skill / "scripts" / "halbooking_automation.py"
            ).read_text(encoding="utf-8")
            self.assertNotIn("baner_grid.html", content)
            self.assertNotIn("el => el.outerHTML", content)

    def test_email_batch_requires_batch_and_nested_onboard_approval(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for skill in ("bredballeif-padel-halbooking", "bredballeif-padel-onboarding"):
            content = (
                root / "skills" / skill / "scripts" / "conventus_email_processor.py"
            ).read_text(encoding="utf-8")
            self.assertIn('require_write_approval("onboarding.process-emails")', content)
            self.assertIn('approval.require("onboarding.onboard")', content)

    def test_member_integration_logs_do_not_render_raw_exceptions_or_streams(self) -> None:
        root = Path(__file__).resolve().parents[1]
        paths = (
            "skills/bredballeif-boerneattest/scripts/agent.py",
            "skills/bredballeif-padel-conventus/scripts/agent.py",
            "skills/bredballeif-padel-conventus/scripts/conventus_group_automation.py",
            "skills/bredballeif-padel-halbooking/scripts/agent.py",
            "skills/bredballeif-padel-halbooking/scripts/conventus_agent.py",
            "skills/bredballeif-padel-halbooking/scripts/conventus_email_processor.py",
            "skills/bredballeif-padel-halbooking/scripts/halbooking_automation.py",
            "skills/bredballeif-padel-onboarding/scripts/agent.py",
            "skills/bredballeif-padel-onboarding/scripts/conventus_agent.py",
            "skills/bredballeif-padel-onboarding/scripts/conventus_email_processor.py",
            "skills/bredballeif-padel-onboarding/scripts/halbooking_automation.py",
        )
        forbidden = ("{e}", "str(e)", "traceback.print_exc", "stdout[:", "stderr[:")
        for relative in paths:
            with self.subTest(path=relative):
                content = (root / relative).read_text(encoding="utf-8")
                for pattern in forbidden:
                    self.assertNotIn(pattern, content)


if __name__ == "__main__":
    unittest.main()
