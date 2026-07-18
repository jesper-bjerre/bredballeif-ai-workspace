from __future__ import annotations

import io
import json
import sys
import tempfile
import types
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock
from zipfile import ZIP_DEFLATED, ZipFile


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from importers import (  # noqa: E402
    HistoryDownloadError,
    download_shared_workbook,
    import_application_history,
    import_dgi_workbook,
    import_fund_workbook,
    normalize_date_value,
)
from json_store import (  # noqa: E402
    JsonFundStore as IndexStore,
    canonical_fund_key,
    normalize_domain,
    normalize_name,
    normalize_verification,
    safe_json_dumps,
    safe_json_loads,
)


class _FakeSheet:
    def __init__(self, rows):
        self.rows = list(rows)

    def iter_rows(self, min_row=None, values_only=False, **_options):
        del values_only
        start = (min_row or 1) - 1
        return iter(self.rows[start:])


class _FakeWorkbook:
    def __init__(self, sheets):
        self._sheets = sheets
        self.sheetnames = list(sheets)
        self.closed = False

    def __getitem__(self, name):
        return self._sheets[name]

    def close(self):
        self.closed = True


class JsonFundStoreTests(unittest.TestCase):
    def test_file_store_persists_one_json_per_fund_and_rebuilds_jsonl_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "store"
            with IndexStore(root) as store:
                fund_id = store.upsert_fund(
                    {
                        "name": "Filbaseret Idrætspulje",
                        "url": "https://filpulje.example/ansoeg",
                        "purposes": ["Idræt", "Fællesskab"],
                        "verification_status": "discovered_official",
                    },
                    source_kind="official_web",
                    source_name="Puljens hjemmeside",
                    source_url="https://filpulje.example/ansoeg",
                    source_record_id="pulje-1",
                )
                store.add_history(
                    {
                        "fund_id": fund_id,
                        "fund_name": "Filbaseret Idrætspulje",
                        "project_id": "projekt-1",
                        "submitted_at": "2026-07-17",
                    }
                )

            fund_path = root / "funds" / "000001.json"
            observation_path = root / "observations" / "000001.jsonl"
            history_path = root / "history" / "000001.json"
            index_path = root / "index.jsonl"
            self.assertTrue(fund_path.is_file())
            self.assertTrue(observation_path.is_file())
            self.assertTrue(history_path.is_file())
            self.assertTrue(index_path.is_file())
            fund_payload = json.loads(fund_path.read_text(encoding="utf-8"))
            self.assertEqual(fund_payload["purposes"], ["Idræt", "Fællesskab"])
            self.assertNotIn("extra_json", fund_payload)
            self.assertEqual(len(index_path.read_text(encoding="utf-8").splitlines()), 1)

            with IndexStore(root) as reloaded:
                self.assertEqual(reloaded.stats(), {
                    "funds": 1,
                    "observations": 1,
                    "history": 1,
                    "verification_status": {
                        "verified": 0,
                        "discovered_official": 1,
                        "directory_only": 0,
                        "candidate": 0,
                        "unverified": 0,
                        "needs_review": 0,
                        "temporary": 0,
                        "closed": 0,
                        "unknown": 0,
                    },
                })
                self.assertTrue(reloaded.integrity_check()["valid"])
                rebuilt = reloaded.rebuild_index()
                self.assertEqual(rebuilt["records"], 1)

    def test_index_rejects_urls_with_embedded_credentials(self):
        with IndexStore(":memory:") as store:
            with self.assertRaisesRegex(ValueError, "brugernavn eller adgangskode"):
                store.upsert_fund(
                    {
                        "name": "Usikker fond",
                        "url": "https://user:secret@example.org/apply",
                    }
                )

    def test_history_rejects_urls_with_embedded_credentials(self):
        for field in ("fund_url", "source_url"):
            with self.subTest(field=field), IndexStore(":memory:") as store:
                record = {
                    "fund_name": "Usikker historikfond",
                    "project_name": "Klubhusprojekt",
                    "submitted_at": "2026-07-17T12:00:00+02:00",
                    field: "https://user:secret@example.org/application",
                }
                with self.assertRaisesRegex(ValueError, "brugernavn eller adgangskode"):
                    store.add_history(record)

    def test_canonical_upsert_preserves_verified_data_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            with IndexStore(Path(directory) / "store") as store:
                first_id = store.upsert_fund(
                    {
                        "name": "Prøve & Idrætsfonden",
                        "official_url": "https://www.eksempelfond.example/pulje/",
                        "purposes": "Rå beskrivelse",
                        "verification_status": "Ikke verificeret – rådata",
                    },
                    source_kind="xlsx",
                    source_name="indeks.xlsx#03_Fondsindeks",
                    source_record_id="IDX-1",
                    raw={"Fond/pulje": "Prøve & Idrætsfonden"},
                )
                second_id = store.upsert_fund(
                    {
                        "name": "PROEVE OG IDRAETSFONDEN",
                        "url": "https://eksempelfond.example/ansoeg",
                        "purposes": "Kontrolleret formål",
                        "requirements": "Foreningen skal være almennyttig",
                        "verification_status": "Verificeret",
                        "last_verified_at": "2026-07-13",
                    },
                    source_kind="official_site",
                    source_name="Fondens hjemmeside",
                    source_url="https://eksempelfond.example/ansoeg",
                    source_record_id="official-2026",
                )
                third_id = store.upsert_fund(
                    {
                        "name": "Prøve og Idrætsfonden",
                        "url": "https://www.eksempelfond.example/",
                        "purposes": "Ældre råtekst må ikke vinde",
                        "verification_status": "rådata",
                    },
                    source_name="genimport",
                    source_record_id="IDX-2",
                )

                self.assertEqual(first_id, second_id)
                self.assertEqual(second_id, third_id)
                fund = store.get_fund(first_id)
                self.assertIsNotNone(fund)
                self.assertEqual(fund["domain"], "eksempelfond.example")
                self.assertEqual(fund["verification_status"], "verified")
                self.assertEqual(fund["purposes"], "Kontrolleret formål")
                self.assertEqual(fund["last_checked"], "2026-07-13")
                self.assertEqual(fund["official_url"], fund["url"])
                self.assertEqual(len(store.list_observations(first_id)), 3)
                self.assertEqual(store.stats()["funds"], 1)
                self.assertEqual(store.stats()["observations"], 3)

    def test_missing_domain_is_enriched_without_creating_a_duplicate(self):
        with IndexStore(":memory:") as store:
            first = store.upsert_fund({"name": "Lokal aktivitetspulje"})
            second = store.upsert_fund(
                {
                    "name": "Lokal-aktivitetspulje",
                    "url": "https://pulje.example/ansoeg",
                }
            )
            self.assertEqual(first, second)
            self.assertEqual(store.stats()["funds"], 1)
            self.assertEqual(store.get_fund(first)["domain"], "pulje.example")

    def test_closed_status_blocks_weak_feeds_but_fresh_verification_reopens(self):
        with IndexStore(":memory:") as store:
            fund_id = store.upsert_fund(
                {
                    "name": "Aktivitetspuljen",
                    "url": "https://aktivitet.example",
                    "verification_status": "closed",
                    "last_checked": "2026-07-10",
                }
            )
            store.upsert_fund(
                {
                    "name": "Aktivitetspuljen",
                    "url": "https://aktivitet.example",
                    "verification_status": "directory_only",
                    "last_checked": "2026-07-15",
                }
            )
            self.assertEqual(store.get_fund(fund_id)["verification_status"], "closed")
            self.assertEqual(store.get_fund(fund_id)["last_checked"], "2026-07-10")

            store.upsert_fund(
                {
                    "name": "Aktivitetspuljen",
                    "url": "https://aktivitet.example",
                    "verification_status": "verified",
                    "last_checked": "2026-07-16",
                }
            )
            self.assertEqual(store.get_fund(fund_id)["verification_status"], "verified")
            self.assertEqual(store.get_fund(fund_id)["last_checked"], "2026-07-16")

            store.upsert_fund(
                {
                    "name": "Aktivitetspuljen",
                    "url": "https://aktivitet.example/gammel-liste",
                    "verification_status": "closed",
                    "last_checked": "2026-07-01",
                    "description": "Forældet lukningsobservation",
                }
            )
            still_open = store.get_fund(fund_id)
            self.assertEqual(still_open["verification_status"], "verified")
            self.assertEqual(still_open["last_checked"], "2026-07-16")
            self.assertNotEqual(still_open["description"], "Forældet lukningsobservation")

            store.upsert_fund(
                {
                    "name": "Aktivitetspuljen",
                    "url": "https://aktivitet.example",
                    "verification_status": "closed",
                    "last_checked": "2026-07-17",
                }
            )
            self.assertEqual(store.get_fund(fund_id)["verification_status"], "closed")

    def test_equal_rank_newer_verified_record_refreshes_requirements(self):
        with IndexStore(":memory:") as store:
            fund_id = store.upsert_fund(
                {
                    "name": "Udstyrspuljen",
                    "url": "https://udstyr.example",
                    "verification_status": "verified",
                    "last_checked": "2026-06-01",
                    "deadline": "1. juni",
                    "requirements": "Ældre krav",
                }
            )
            store.upsert_fund(
                {
                    "name": "Udstyrspuljen",
                    "url": "https://udstyr.example/krav",
                    "verification_status": "verified",
                    "last_checked": "2026-07-17",
                    "deadline": "1. september",
                    "requirements": {"eligible": "Idrætsforeninger"},
                }
            )
            fund = store.get_fund(fund_id)
            self.assertEqual(fund["deadline"], "1. september")
            self.assertEqual(fund["requirements"], {"eligible": "Idrætsforeninger"})
            self.assertEqual(fund["last_checked"], "2026-07-17")

    def test_equal_discovery_observations_union_geographies_but_verified_replaces(self):
        with IndexStore(":memory:") as store:
            fund_id = store.upsert_fund(
                {
                    "name": "Den Lokale Fond",
                    "url": "https://lokal.example",
                    "geography": "Vejle",
                    "verification_status": "unverified",
                }
            )
            store.upsert_fund(
                {
                    "name": "Den Lokale Fond",
                    "url": "https://lokal.example",
                    "geography": "Kolding",
                    "verification_status": "unverified",
                }
            )
            self.assertEqual(store.get_fund(fund_id)["geography"], ["Vejle", "Kolding"])

            store.upsert_fund(
                {
                    "name": "Den Lokale Fond",
                    "url": "https://lokal.example",
                    "geography": "Danmark",
                    "verification_status": "verified",
                    "last_checked": "2026-07-17",
                }
            )
            self.assertEqual(store.get_fund(fund_id)["geography"], "Danmark")

    def test_explicit_update_migrates_official_domain_without_duplicate(self):
        with IndexStore(":memory:") as store:
            fund_id = store.upsert_fund(
                {"name": "Flyttefonden", "url": "https://old.example/pulje"}
            )
            updated_id = store.upsert_fund(
                {
                    "name": "Flyttefonden",
                    "url": "https://new.example/ansoeg",
                    "domain": "new.example",
                    "verification_status": "verified",
                    "last_checked": "2026-07-17",
                },
                target_fund_id=fund_id,
            )
            updated = store.get_fund(fund_id)
            self.assertEqual(updated_id, fund_id)
            self.assertEqual(store.stats()["funds"], 1)
            self.assertEqual(updated["domain"], "new.example")
            self.assertEqual(updated["canonical_key"], "flyttefonden|new.example")

    def test_history_is_idempotent_and_resolves_known_fund(self):
        with IndexStore(":memory:") as store:
            fund_id = store.upsert_fund(
                {"name": "Fællesskabspuljen", "url": "https://faellesskab.example"}
            )
            record = {
                "fund_name": "FAELLESSKABSPULJEN",
                "fund_url": "https://www.faellesskab.example/vejledning",
                "project_name": "Nyt aktivitetstilbud",
                "submitted_at": "2026-04-01",
                "status": "Sendt",
                "external_id": "ANS-001",
                "source_name": "historik.csv",
            }
            first = store.add_history(record)
            second = store.record_sent_application(record)
            self.assertEqual(first, second)
            history = store.list_history()
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["fund_id"], fund_id)
            self.assertTrue(
                store.has_prior_application(
                    "Fællesskabspuljen", "https://faellesskab.example"
                )
            )

    def test_history_reimport_updates_result_without_duplicate_or_row_identity(self):
        with IndexStore(":memory:") as store:
            first = {
                "fund_name": "Resultatfonden",
                "project_name": "Aktivitetsprojekt",
                "submitted_at": "2026-03-01",
                "status": "Sendt",
                "amount_requested": "50000",
                "source_name": "historik.xlsx",
            }
            history_id = store.add_history(first)
            changed = {**first, "status": "Bevilget", "amount_requested": "45000"}
            self.assertEqual(store.add_history(changed), history_id)
            rows = store.list_history()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "Bevilget")
            self.assertEqual(rows[0]["amount_requested"], "45000")

            updated = store.update_history_result(
                history_id,
                status="Udbetalt",
                decision_at="2026-06-01",
                awarded_amount=45_000,
                notes="Afsluttet",
            )
            self.assertEqual(updated["status"], "Udbetalt")
            self.assertEqual(updated["extra"]["awarded_amount"], "45000")

    def test_normalizers_and_strict_json(self):
        self.assertEqual(normalize_name("  Børn & Unge-puljen "), "boern og unge puljen")
        self.assertEqual(
            normalize_domain("https://WWW.Eksempel.DK:443/ansoeg"), "eksempel.dk"
        )
        self.assertEqual(
            canonical_fund_key("Børn & Unge", "www.eksempel.dk/path"),
            "boern og unge|eksempel.dk",
        )
        self.assertEqual(normalize_verification("Ikke verificeret – rådata"), "unverified")
        self.assertEqual(normalize_verification("Kontrollér igen"), "needs_review")
        self.assertEqual(normalize_verification("Verificeret"), "verified")

        encoded = safe_json_dumps(
            {
                "checked": date(2026, 7, 13),
                "amount": Decimal("12500.50"),
                "invalid_number": float("nan"),
            }
        )
        self.assertNotIn("NaN", encoded)
        self.assertEqual(
            safe_json_loads(encoded),
            {
                "amount": "12500.50",
                "checked": "2026-07-13",
                "invalid_number": None,
            },
        )


class ImporterTests(unittest.TestCase):
    def _fund_workbook(self):
        current_headers = (
            "ID",
            "Type",
            "Fond/pulje/portal",
            "Geografi",
            "Hvem kan søge",
            "Typisk formål",
            "Beløb/ramme",
            "Frist/frekvens",
            "Vigtige krav",
            "Vigtige udelukkelser",
            "Status",
            "Sidst kontrolleret",
            "Officiel URL",
            "Praktisk note",
        )
        index_headers = (
            "Indeks-ID",
            "Geografi",
            "Kommune/område",
            "Fond/pulje",
            "Kort beskrivelse",
            "URL",
            "Kilde",
            "Verifikationsstatus",
            "Sidst kontrolleret",
            "Relevans for Bredballe IF",
            "Noter",
        )
        padding = [("titel",), ("forklaring",), tuple()]
        current_rows = padding + [
            current_headers,
            (
                "AKT-001",
                "Pulje",
                "Prøve & Idrætsfonden",
                "Danmark",
                "Idrætsforeninger",
                "Lokale aktiviteter",
                "Op til 100.000 kr.",
                "Løbende",
                "Realistisk budget",
                "Ingen drift",
                "Verificeret",
                date(2026, 7, 13),
                "https://eksempelfond.example/ansoeg",
                "Relevant ved nye aktiviteter",
            ),
        ]
        index_rows = padding + [
            index_headers,
            (
                "DGI-0001",
                "Nationalt",
                "Nationalt",
                "PROEVE OG IDRAETSFONDEN",
                "Ældre beskrivelse",
                "https://www.eksempelfond.example/",
                "Offentlig oversigt",
                "Ikke verificeret – rådata",
                None,
                "Ja",
                "Skal genkontrolleres",
            ),
        ]
        return _FakeWorkbook(
            {
                "02_Aktuelle": _FakeSheet(current_rows),
                "03_Fondsindeks": _FakeSheet(index_rows),
            }
        )

    def test_known_fund_workbook_sheets_and_header_row_four(self):
        workbook = self._fund_workbook()
        fake_openpyxl = types.ModuleType("openpyxl")
        fake_openpyxl.load_workbook = mock.Mock(return_value=workbook)
        with mock.patch.dict(sys.modules, {"openpyxl": fake_openpyxl}):
            with IndexStore(":memory:") as store:
                result = import_fund_workbook(
                    "fondsindeks.xlsx", store, source_name="research.xlsx"
                )
                funds = store.list_funds()
                observations = store.list_observations()

        self.assertTrue(workbook.closed)
        self.assertTrue(result.ok)
        self.assertEqual(result.records_seen, 2)
        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.updated, 1)
        self.assertEqual(len(funds), 1)
        self.assertEqual(funds[0]["verification_status"], "verified")
        self.assertEqual(funds[0]["last_checked"], "2026-07-13")
        self.assertEqual(len(observations), 2)
        self.assertEqual(
            {item["source_record_id"] for item in observations},
            {"AKT-001", "DGI-0001"},
        )

    def test_flexible_semicolon_csv_history_and_privacy_minimization(self):
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "sendte-ansoegninger.csv"
            history_path.write_text(
                "Oversigt over projekter;;;;;;\n"
                "Fond/pulje;Projektnavn;Ansøgningsdato;Ansøgt beløb;Status;Ansøgnings-ID;Kontaktperson;Noter\n"
                "Fællesskabspuljen;Nyt aktivitetstilbud;13-07-2026;50000;Sendt;ANS-001;skal ignoreres;privat fritekst\n",
                encoding="utf-8",
            )
            with IndexStore(":memory:") as store:
                first = import_application_history(history_path, store)
                second = import_application_history(history_path, store)
                rows = store.list_history()
            with IndexStore(":memory:") as store:
                import_application_history(history_path, store, include_notes=True)
                opted_in_rows = store.list_history()

        self.assertEqual(first.inserted, 1)
        self.assertEqual(second.duplicates, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["submitted_at"], "2026-07-13")
        self.assertNotIn("Kontaktperson", json.dumps(rows, ensure_ascii=False))
        self.assertNotIn("skal ignoreres", json.dumps(rows, ensure_ascii=False))
        self.assertNotIn("privat fritekst", json.dumps(rows, ensure_ascii=False))

        self.assertIn("privat fritekst", json.dumps(opted_in_rows, ensure_ascii=False))

    def test_excel_serial_date_normalization(self):
        self.assertEqual(normalize_date_value(46216), "2026-07-13")

    def test_current_dgi_workbook_format_is_imported_and_geographies_are_unioned(self):
        rows = [
            (None, None, None, None),
            ("Kommune ", "Fond", "Kort beskrivelse", "Link"),
            ("Vejle", "Fællesfonden", "Støtter foreningsliv", "https://faelles.example"),
            ("Kolding", "Fællesfonden", "Støtter foreningsliv", "https://faelles.example"),
            (" Nationalt", "Landsfonden", "Almennyttige formål", "https://land.example"),
        ]
        workbook = _FakeWorkbook({"Fonde - oversigt": _FakeSheet(rows)})
        fake_openpyxl = types.ModuleType("openpyxl")
        fake_openpyxl.load_workbook = mock.Mock(return_value=workbook)
        with mock.patch.dict(sys.modules, {"openpyxl": fake_openpyxl}):
            with IndexStore(":memory:") as store:
                result = import_dgi_workbook("dgi.xlsx", store)
                funds = {item["name"]: item for item in store.list_funds()}

        self.assertTrue(result.ok)
        self.assertEqual(result.records_seen, 3)
        self.assertEqual(result.inserted, 2)
        self.assertEqual(result.updated, 1)
        self.assertEqual(funds["Fællesfonden"]["geography"], ["Vejle", "Kolding"])
        self.assertEqual(funds["Landsfonden"]["geography"], "Danmark")
        self.assertEqual(funds["Landsfonden"]["verification_status"], "unverified")


class DownloadTests(unittest.TestCase):
    class _Response(io.BytesIO):
        def __init__(self, payload, url):
            super().__init__(payload)
            self._url = url
            self.headers = {"Content-Length": str(len(payload))}

        def geturl(self):
            return self._url

    class _Opener:
        def __init__(self, response):
            self.response = response

        def open(self, _request, timeout):
            assert timeout == 30
            return self.response

    @staticmethod
    def _minimal_xlsx():
        output = io.BytesIO()
        with ZipFile(output, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types />")
            archive.writestr("xl/workbook.xml", "<workbook />")
        return output.getvalue()

    def test_shared_download_is_offline_testable_with_injected_opener(self):
        payload = self._minimal_xlsx()
        response = self._Response(payload, "https://onedrive.live.com/download")
        with tempfile.TemporaryDirectory() as directory:
            path = download_shared_workbook(
                "https://1drv.ms/x/example",
                directory,
                opener=self._Opener(response),
            )
            self.assertEqual(path.read_bytes(), payload)

    def test_shared_download_rejects_non_allowlisted_host(self):
        with self.assertRaises(HistoryDownloadError):
            download_shared_workbook("https://example.org/file.xlsx", tempfile.gettempdir())

    def test_shared_download_rejects_suspicious_xlsx_expansion(self):
        output = io.BytesIO()
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types />")
            archive.writestr("xl/workbook.xml", "<workbook />")
            archive.writestr("xl/sharedStrings.xml", b"0" * (11 * 1024 * 1024))
        response = self._Response(output.getvalue(), "https://onedrive.live.com/download")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(HistoryDownloadError, "kompressionsratio"):
                download_shared_workbook(
                    "https://1drv.ms/x/example",
                    directory,
                    opener=self._Opener(response),
                )


if __name__ == "__main__":
    unittest.main()
