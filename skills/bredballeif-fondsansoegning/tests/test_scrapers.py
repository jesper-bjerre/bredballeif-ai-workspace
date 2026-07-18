from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from scrapers import (
    FundraisingClubCrawler,
    PublicSourceCrawler,
    ScrapeError,
    extract_fund_record,
    sync_eu_funding_feed,
    sync_state_grants_feed,
)
from source_registry import load_registry


class ScraperParsingTests(unittest.TestCase):
    def test_extracts_bounded_fund_metadata_and_official_link(self) -> None:
        html = """
        <html><head><title>Eksempelfond | Katalog</title></head><body>
          <main>
            <h1>Eksempelfondens Idrætspulje</h1>
            <p>Hvem kan søge: Frivillige idrætsforeninger.</p>
            <p>Ansøgningsfrist: 1. oktober.</p>
            <a href="https://example.org/ansoeg">Officiel hjemmeside og ansøgning</a>
          </main>
        </body></html>
        """
        record = extract_fund_record(
            html,
            "https://directory.invalid/fond/42",
            source_name="Syntetisk katalog",
            source_kind="licensed_directory",
            geography="Danmark",
            excluded_external_hosts={"directory.invalid"},
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record["name"], "Eksempelfondens Idrætspulje")
        self.assertEqual(record["official_url"], "https://example.org/ansoeg")
        self.assertEqual(record["verification_status"], "directory_only")
        self.assertIn("Ansøgningsfrist", record["extra"]["labeled_fields"])
        self.assertNotIn("<html", record["description"])

    def test_rejects_generic_directory_page_without_requirements(self) -> None:
        html = "<html><body><main><h1>Nyheder</h1><p>Velkommen til vores nyheder.</p></main></body></html>"
        self.assertIsNone(
            extract_fund_record(
                html,
                "https://example.org/nyheder",
                source_name="Eksempel",
                source_kind="official_web",
            )
        )

    def test_fundraising_login_never_posts_to_external_form_action(self) -> None:
        crawler = FundraisingClubCrawler(confirm_authorized_use=True)
        html = """
        <form id="rcp_login_form" action="https://evil.example/collect">
          <input name="rcp_login_nonce" value="nonce">
        </form>
        """
        with patch.object(
            crawler,
            "_private_html_request",
            return_value=(html, "https://app.fundraisingclub.dk/login/"),
        ) as request:
            with self.assertRaisesRegex(ScrapeError, "credentials blev ikke sendt"):
                crawler.login("bruger", "hemmelig")
        self.assertEqual(request.call_count, 1)
        crawler.close()

    def test_fundraising_crawl_rejects_external_start_url_before_fetch(self) -> None:
        crawler = FundraisingClubCrawler(confirm_authorized_use=True)
        with patch.object(crawler, "_private_html_request") as request:
            with self.assertRaisesRegex(ScrapeError, "start-URL"):
                crawler.crawl(start_urls=["https://evil.example/fonde"])
        request.assert_not_called()
        crawler.close()

    def test_fundraising_crawl_does_not_report_success_without_records(self) -> None:
        crawler = FundraisingClubCrawler(confirm_authorized_use=True)
        with patch.object(
            crawler,
            "_private_html_request",
            return_value=(
                "<html><body><main><h1>Fonde</h1><p>Ingen poster.</p></main></body></html>",
                "https://app.fundraisingclub.dk/fonde/",
            ),
        ):
            with self.assertRaisesRegex(ScrapeError, "ingen genkendelige fondsposter"):
                crawler.crawl(max_pages=1)
        crawler.close()

    @patch("scrapers._assert_safe_public_url")
    @patch("requests.Session")
    def test_state_feed_filters_and_normalizes_active_relevant_rows(
        self, session_class: Mock, _safe_url_check: Mock
    ) -> None:
        csv_data = (
            "\ufeffIsActive;IsApplicantModule;Created;Keywords;IsEUFunded;PoolViewLink;"
            "AuthorityPoolApplicationLink; Modified;AuthorityName;Title;NextDeadline;AllDeadlines;\n"
            "True;False;;idræt,forening,;False;https://example.org/pulje;;;Styrelsen;"
            "Foreningspuljen;01-10-2026 12:00:00;;ekstra-felt;\n"
            "True;False;;jernbane,;False;https://example.org/tog;;;Styrelsen;Togpuljen;;;\n"
            "False;False;;sport,;False;https://example.org/lukket;;;Styrelsen;Lukket sportspulje;;;\n"
        ).encode("utf-8")
        response = Mock()
        response.status_code = 200
        response.url = "https://www.statens-tilskudspuljer.dk/DataExport/statens-tilskudspuljer.csv"
        response.headers = {"Content-Type": "text/csv"}
        response.iter_content.return_value = [csv_data]
        response.raise_for_status.return_value = None
        session_class.return_value.get.return_value = response

        result, counts = sync_state_grants_feed()

        self.assertEqual(counts, {"total": 3, "active": 2, "included": 1, "filtered_irrelevant": 1})
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0]["name"], "Foreningspuljen")
        self.assertEqual(result.records[0]["verification_status"], "discovered_official")

    def test_public_crawler_revalidates_redirect_destination(self) -> None:
        crawler = PublicSourceCrawler()
        redirect = Mock()
        redirect.status_code = 302
        redirect.headers = {"Location": "https://127.0.0.1/private"}
        with patch.object(crawler.session, "get", return_value=redirect), patch(
            "scrapers._assert_safe_public_url",
            side_effect=[None, ScrapeError("privat mål")],
        ):
            with self.assertRaisesRegex(ScrapeError, "privat mål"):
                crawler._get("https://example.org/fonde", allowed_hosts={"example.org", "127.0.0.1"})
        redirect.close.assert_called_once()
        crawler.close()

    def test_public_crawler_marks_robots_skip_and_fetch_failure_incomplete(self) -> None:
        source = {
            "name": "Officiel pulje",
            "url": "https://example.org/fonde",
            "kind": "opportunity",
            "crawl_depth": 1,
        }
        for robots_allowed, get_side_effect in (
            (False, None),
            (True, ScrapeError("syntetisk hentefejl")),
        ):
            with self.subTest(robots_allowed=robots_allowed):
                crawler = PublicSourceCrawler()
                with patch.object(crawler, "_robots_allowed", return_value=robots_allowed), patch.object(
                    crawler, "_get", side_effect=get_side_effect
                ):
                    result = crawler.crawl(source)
                self.assertFalse(result.complete)
                self.assertEqual(result.pages_skipped, 1)
                crawler.close()

    def test_public_crawler_marks_relevant_max_depth_link_incomplete_but_skips_pdf(self) -> None:
        crawler = PublicSourceCrawler()
        html = """
        <main><h1>Idrætspuljen</h1><p>Hvem kan søge: idrætsforeninger.</p>
          <a href="/ny-pulje">Ny relevant pulje</a>
          <a href="/vilkaar.pdf">Puljens vilkår</a>
        </main>
        """
        source = {
            "name": "Officiel pulje",
            "url": "https://example.org/fonde",
            "kind": "opportunity",
            "crawl_depth": 0,
        }
        with patch.object(crawler, "_robots_allowed", return_value=True), patch.object(
            crawler, "_get", return_value=(html, source["url"])
        ):
            result = crawler.crawl(source)
        self.assertFalse(result.complete)
        self.assertTrue(any("crawl_depth=0" in warning for warning in result.warnings))
        crawler.close()

    def test_fundraising_crawler_follows_facetwp_pages_and_only_fund_details(self) -> None:
        crawler = FundraisingClubCrawler(confirm_authorized_use=True)
        start = "https://app.fundraisingclub.dk/fonde/"
        page_two = "https://app.fundraisingclub.dk/fonde/?_paged=2"
        first = "https://app.fundraisingclub.dk/fonde/foerste/"
        second = "https://app.fundraisingclub.dk/fonde/anden/"
        irrelevant = "https://app.fundraisingclub.dk/kurser/"
        pager = '<script>window.FWP_JSON={"settings":{"pager":{"total_rows":2,"total_pages":2}}};</script>'
        listing = f'<main><h1>Fonde</h1><a href="{first}">Første</a><a href="{irrelevant}">Kursus</a></main>{pager}'
        listing_two = f'<main><h1>Fonde</h1><a href="{second}">Anden</a></main>{pager}'
        fund_page = """
        <main><h1>Eksempelfondens Idrætspulje</h1>
          <div><h2>Formål</h2><p>Støtte til lokale idrætsforeninger.</p></div>
          <div><h2>Hvem kan ansøge</h2><p>Frivillige foreninger.</p></div>
          <div><h2>Seneste relaterede nyheder</h2><p>Dette er ikke fondskrav.</p></div>
          <p>Ansøgningsfrist: 1. oktober.</p>
          <a href="https://example.org/ansoeg">Officiel ansøgning</a>
        </main>
        """
        responses = {
            start: (listing, start),
            page_two: (listing_two, page_two),
            first: (fund_page, first),
            second: (fund_page.replace("Eksempelfondens", "Andenfonds"), second),
        }
        fetched: list[str] = []

        def fetch(_method: str, url: str):
            fetched.append(url)
            return responses[url]

        with patch.object(crawler, "_private_html_request", side_effect=fetch):
            result = crawler.crawl(start_urls=[start], max_depth=1)
        self.assertTrue(result.complete)
        self.assertEqual(result.pages_visited, 4)
        self.assertEqual(len(result.records), 2)
        self.assertNotIn(irrelevant, fetched)
        self.assertEqual(result.records[0]["extra"]["sections"]["Formål"], "Støtte til lokale idrætsforeninger.")
        self.assertNotIn("Seneste relaterede nyheder", result.records[0]["extra"]["sections"])
        self.assertEqual(result.records[0]["source_record_id"], "foerste")
        crawler.close()

    def test_fundraising_crawler_marks_caps_and_fetch_failures_incomplete(self) -> None:
        crawler = FundraisingClubCrawler(confirm_authorized_use=True)
        start = "https://app.fundraisingclub.dk/fonde/"
        page_two = "https://app.fundraisingclub.dk/fonde/?_paged=2"
        child = "https://app.fundraisingclub.dk/fonde/eksempel/"
        pager = '<script>window.FWP_JSON={"pager":{"total_rows":2,"total_pages":2}};</script>'
        listing = f'<main><h1>Fonde</h1><a href="{child}">Eksempelfond</a></main>{pager}'
        fund_page = """
        <main><h1>Eksempelfondens Idrætspulje</h1>
          <p>Hvem kan søge: frivillige idrætsforeninger. Ansøgningsfrist: 1. oktober.</p>
        </main>
        """

        with patch.object(crawler, "_private_html_request", return_value=(listing, start)):
            with self.assertRaisesRegex(ScrapeError, "ingen genkendelige fondsposter"):
                crawler.crawl(start_urls=[start], max_pages=1)

        broken = "https://app.fundraisingclub.dk/fonde/broken/"
        listing_with_broken_link = (
            f'<main><h1>Fonde</h1><a href="{child}">Eksempel</a>'
            f'<a href="{broken}">Defekt</a></main>'
            '<script>window.FWP_JSON={"pager":{"total_rows":2,"total_pages":1}};</script>'
        )

        def fetch(_method: str, url: str):
            if url == broken:
                raise ScrapeError("syntetisk hentefejl")
            if url == start:
                return listing_with_broken_link, start
            if url == child:
                return fund_page, child
            raise AssertionError(url)

        with patch.object(crawler, "_private_html_request", side_effect=fetch):
            failure_result = crawler.crawl(start_urls=[start], max_depth=1)
        self.assertFalse(failure_result.complete)
        self.assertEqual(failure_result.pages_skipped, 1)
        crawler.close()

    def test_source_registry_rejects_localhost_and_url_credentials(self) -> None:
        for url in ("https://127.0.0.1/fonde", "https://user:secret@example.org/fonde"):
            with self.subTest(url=url), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "registry.json"
                path.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "sources": [{"id": "bad", "url": url, "enabled": True}],
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaises(ValueError):
                    load_registry(path)

    @patch("scrapers.time.sleep")
    @patch("requests.Session")
    def test_eu_feed_paginates_and_keeps_only_relevant_discovery(
        self, session_class: Mock, sleep: Mock
    ) -> None:
        relevant_metadata = {
            "identifier": ["ERASMUS-SPORT-2026-TEST"],
            "title": ["Grassroots sport partnerships"],
            "callIdentifier": ["ERASMUS-SPORT-2026"],
            "callTitle": ["Sport"],
            "deadlineDate": ["2026-10-01T00:00:00.000+0000"],
            "startDate": ["2026-07-01T00:00:00.000+0000"],
            "status": ["31094502"],
            "type": ["1"],
            "programmePeriod": ["2021 - 2027"],
            "tags": ["SPORT", "VOLUNTEERING"],
            "descriptionByte": ["<p>Support for community physical activity.</p>"],
            "topicConditions": ["<p>Conditions</p>"],
            "url": [
                "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/ERASMUS-SPORT-2026-TEST"
            ],
            "links": [
                '[{"url":"https://ec.europa.eu/research/participants/submission/manage/screen/submission/create-draft/1"}]'
            ],
            "budgetOverview": [
                '{"budgetTopicActionMap":{"1":[{"action":"ERASMUS-SPORT-2026-TEST - ERASMUS-LS","minContribution":10000,"maxContribution":50000,"budgetYearMap":{"2026":"100000"}}]}}'
            ],
        }
        irrelevant_metadata = {
            "identifier": ["HORIZON-INDUSTRY-2026-TEST"],
            "title": ["Advanced waterborne transport systems"],
            "callTitle": ["Industrial technology"],
            "deadlineDate": ["2026-11-01T00:00:00.000+0000"],
            "status": ["31094502"],
            "type": ["1"],
            "descriptionByte": ["<p>Research for zero-emission transport logistics.</p>"],
            "url": [
                "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/HORIZON-INDUSTRY-2026-TEST"
            ],
        }
        responses = []
        for metadata in (relevant_metadata, irrelevant_metadata):
            response = Mock()
            response.status_code = 200
            response.raise_for_status.return_value = None
            payload = {
                "totalResults": 2,
                "apiVersion": "test-version",
                "results": [{"metadata": metadata, "reference": metadata["identifier"][0]}],
            }
            response.iter_content.return_value = [json.dumps(payload).encode("utf-8")]
            responses.append(response)
        session = session_class.return_value
        session.post.side_effect = responses

        result, counts = sync_eu_funding_feed(page_size=1, max_pages=5)

        self.assertEqual(result.pages_visited, 2)
        self.assertEqual(counts["processed"], 2)
        self.assertEqual(counts["included"], 1)
        self.assertEqual(counts["filtered_irrelevant"], 1)
        self.assertEqual(result.records[0]["source_record_id"], "ERASMUS-SPORT-2026-TEST")
        self.assertEqual(result.records[0]["amount"], "EUR 10,000–50,000")
        self.assertEqual(result.records[0]["verification_status"], "discovered_official")
        self.assertNotIn("<p>", result.records[0]["description"])
        self.assertEqual(session.post.call_count, 2)
        sleep.assert_called_once()
        session.close.assert_called_once()

    @patch("requests.Session")
    def test_eu_feed_marks_page_cap_as_incomplete(self, session_class: Mock) -> None:
        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        payload = {
            "totalResults": 2,
            "apiVersion": "test-version",
            "results": [],
        }
        response.iter_content.return_value = [json.dumps(payload).encode("utf-8")]
        session_class.return_value.post.return_value = response

        result, counts = sync_eu_funding_feed(page_size=1, max_pages=1)

        self.assertFalse(result.complete)
        self.assertTrue(counts["truncated"])
        self.assertEqual(result.pages_visited, 1)


if __name__ == "__main__":
    unittest.main()
