from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import agent  # noqa: E402
from json_store import JsonFundStore  # noqa: E402
from seed_catalog import read_seed, write_private_seed, write_public_seed  # noqa: E402


class SeedCatalogTests(unittest.TestCase):
    def test_export_excludes_licensed_only_records_and_narrative_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            output = root / "funds-seed.jsonl"
            with JsonFundStore(source) as store:
                store.upsert_fund(
                    {
                        "name": "Offentlig Idrætspulje",
                        "url": "https://example.org/pulje",
                        "description": "Lang tekst må ikke distribueres i seedet.",
                        "purposes": "Idræt",
                        "verification_status": "discovered_official",
                        "extra": {"sections": {"Formål": "Licenseret tekst"}},
                    },
                    source_kind="official_feed",
                    source_name="Officiel kilde",
                    source_url="https://example.org/pulje",
                )
                store.upsert_fund(
                    {
                        "name": "Licenseret katalogpost",
                        "url": "https://licensed.example/fond",
                        "verification_status": "directory_only",
                    },
                    source_kind="licensed_directory",
                    source_name="Fundraising Club",
                )

            result = write_public_seed(source, output)
            records = read_seed(output)

            self.assertEqual(result["records"], 1)
            self.assertEqual(records[0]["name"], "Offentlig Idrætspulje")
            self.assertEqual(records[0]["purposes"], "Idræt")
            self.assertNotIn("description", records[0])
            self.assertNotIn("extra", records[0])

    def test_agent_store_bootstraps_empty_runtime_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            seed = root / "funds-seed.jsonl"
            runtime = root / "runtime"
            with JsonFundStore(source) as store:
                store.upsert_fund(
                    {"name": "Seedfond", "url": "https://example.org", "verification_status": "unverified"},
                    source_kind="official_web",
                    source_name="Officiel side",
                )
            write_public_seed(source, seed)

            with patch.object(agent, "DEFAULT_SEED", seed), patch.dict(
                "os.environ", {"BREDBALLEIF_FONDS_DISABLE_SEED": ""}
            ):
                with agent.IndexStore(runtime) as store:
                    self.assertEqual(store.seed_import["inserted"], 1)
                    self.assertEqual(store.stats()["funds"], 1)
                with agent.IndexStore(runtime) as store:
                    self.assertEqual(store.seed_import["inserted"], 0)
                    self.assertEqual(store.stats()["funds"], 1)

    def test_private_seed_includes_licensed_records_and_is_preferred_by_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            seed = root / "private-seed.jsonl"
            runtime = root / "runtime"
            with JsonFundStore(source) as store:
                store.upsert_fund(
                    {
                        "name": "Privat katalogpost",
                        "url": "https://example.org/fond",
                        "description": "Privat beskrivelse",
                        "verification_status": "directory_only",
                        "extra": {"sections": {"Formål": "Privat detalje"}},
                    },
                    source_kind="licensed_directory",
                    source_name="Fundraising Club",
                )
            result = write_private_seed(source, seed)

            self.assertEqual(result["scope"], "private")
            self.assertEqual(read_seed(seed)[0]["description"], "Privat beskrivelse")
            with patch.dict("os.environ", {"BREDBALLEIF_FONDS_PRIVATE_SEED": str(seed)}):
                with agent.IndexStore(runtime) as store:
                    self.assertEqual(store.seed_import["scope"], "private")
                    self.assertEqual(store.stats()["funds"], 1)


if __name__ == "__main__":
    unittest.main()
