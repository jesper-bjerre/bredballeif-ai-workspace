"""Synthetic browser regressions; no credentials or live financial fixtures."""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/bredballeif-padel-conventus/scripts'))
import conventus_budget_automation as budget
from playwright.sync_api import sync_playwright


OPTIONS = [
    {'value': '0', 'label': ''},
    {'value': '40', 'label': '40: 105. E-sport'},
    {'value': '60', 'label': '60: 116. Padel'},
]


class DepartmentTests(unittest.TestCase):
    def test_spelling_variants_and_existing_padel(self):
        for name in ('Esport', 'E-sport', 'e SPORT', '40: 105. E-sport'):
            with self.subTest(name=name):
                self.assertEqual(budget.match_department(OPTIONS, name)['value'], '40')
        self.assertEqual(budget.match_department(OPTIONS, 'Padel')['value'], '60')

    def test_ambiguous_and_broad_requests_fail(self):
        ambiguous = OPTIONS + [{'value': '41', 'label': '41: 106. Esport'}]
        for options, name in [(ambiguous, 'Esport'), (OPTIONS, 'Ukendt'),
                              (OPTIONS, ''), (OPTIONS, 'Alle afdelinger'), (OPTIONS, 'all')]:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    budget.match_department(options, name)

    def test_missing_credentials_fails_before_browser(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(budget, 'ConventusBudgetAutomation') as cls:
            with self.assertRaisesRegex(ValueError, 'CONVENTUS_USERNAME'):
                budget.fetch_budget_report('Esport')
            cls.assert_not_called()

    def test_login_output_does_not_pollute_json(self):
        class Fake:
            def __init__(self, **kwargs): pass
            def start(self): print('debug start')
            def login(self):
                print('private login diagnostic')
                return True
            def fetch_report(self, request): return {'year': request.year, 'department': request.department}
            def stop(self): pass
        output = io.StringIO()
        with patch.dict(os.environ, {'CONVENTUS_USERNAME':'synthetic', 'CONVENTUS_PASSWORD':'synthetic'}), \
                patch.object(budget, 'ConventusBudgetAutomation', Fake), patch('sys.stdout', output):
            budget.print_report(budget.fetch_budget_report('Esport', year=2026))
        self.assertEqual(json.loads(output.getvalue()), {'year':2026, 'department':'Esport'})

    def test_invalid_scope_and_year_count_fail_before_browser(self):
        for kwargs in ({'department':'all'}, {'department':'Esport','year_count':4},
                       {'department':'Esport','year':2100}, {'department':'Esport','account':''}):
            with self.subTest(kwargs=kwargs), patch.object(budget,'ConventusBudgetAutomation') as cls:
                with self.assertRaises(ValueError):
                    budget.fetch_budget_report(**kwargs)
                cls.assert_not_called()

    def test_browser_error_does_not_expose_raw_diagnostics(self):
        with patch.dict(os.environ, {'CONVENTUS_USERNAME':'synthetic','CONVENTUS_PASSWORD':'synthetic'}), \
                patch.object(budget,'ConventusBudgetAutomation') as cls:
            cls.return_value.start.side_effect=budget.BrowserError('Executable doesn\'t exist: PRIVATE_SENTINEL')
            with self.assertRaisesRegex(RuntimeError,'Chromium mangler') as raised:
                budget.fetch_budget_report('Esport',year=2026)
            self.assertNotIn('PRIVATE_SENTINEL',str(raised.exception))
            cls.return_value.stop.assert_called_once()


class BrowserRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.automation = budget.ConventusBudgetAutomation(username='synthetic', password='synthetic')
        self.automation._page = self.context.new_page()
        self.state = {'account':False, 'year':2027, 'wrong_year':False, 'wrong_scope':False,
                      'has_budget':True, 'duplicate_accounts':False}
        self.context.route('**/*', self.serve)
        self.requests = []

    def tearDown(self):
        self.context.close()

    def serve(self, route):
        parsed = urlsplit(route.request.url)
        if parsed.netloc != 'www.conventus.dk':
            route.abort()
            return
        query = parse_qs(parsed.query)
        section = query.get('page', [''])[0]
        if parsed.path == '/favicon.ico':
            route.fulfill(status=204)
            return
        self.requests.append(section)
        if section.endswith('regnskaber/vaelg_action.php'):
            self.state['account'] = True
            route.fulfill(body='<html><body>Regnskab valgt</body></html>', content_type='text/html')
            return
        if section.endswith('regnskabsaar/vaelg_action.php'):
            self.state['year'] = int(query['idv1'][0])
            route.fulfill(body='<html><body>Regnskabsår valgt</body></html>', content_type='text/html')
            return
        if section == 'economy/regnskaber/start.php':
            disabled = 'disabled' if self.state['account'] else ''
            row = f'''<tr><td><button {disabled} onclick="location.href='?page=economy/regnskaber/vaelg_action.php'">Vælg</button></td><td>Bredballe IF</td></tr>'''
            overlay = '' if self.state['account'] else '''<div id="olwin1" style="position:fixed;inset:0;background:white"><table><tr><td onclick="document.getElementById('olwin1').style.display='none'">Luk</td></tr></table></div>'''
            html = f'<table>{row}{row if self.state["duplicate_accounts"] else ""}</table>{overlay}'
        elif section == 'economy/regnskabsaar/start.php':
            html = '<table>' + ''.join(
                f'''<tr><td><button {'disabled' if y==self.state['year'] else ''} onclick="location.href='?page=economy/regnskabsaar/vaelg_action.php&idv1={y}'">Vælg</button></td><td>{y}</td></tr>'''
                for y in (2024,2025,2026,2027)) + '</table>'
        elif section == 'economy/budget/regnskab_liste.php':
            # A non-visible form reproduces the previous is_visible failure.
            html = '<form name="accountform"><table>' + ''.join(
                f'<tr><td><input type="checkbox" id="account_{y}" name="account"></td><td>{y}</td></tr>'
                for y in (2024,2025) if y < self.state['year']) + '</table></form>'
        elif section == 'economy/budget/start.php':
            selected = query.get('afdeling', ['0'])[0]
            if self.state['wrong_scope']: selected = '60'
            options = ''.join(f'<option value="{o["value"]}" {"selected" if o["value"]==selected else ""}>{o["label"]}</option>' for o in OPTIONS)
            table = ''
            if query.get('search'):
                previous = query.get('old_accounts', [''])[0].split(',')
                previous = [y for y in previous if y]
                year = 2027 if self.state['wrong_year'] else self.state['year']
                headers = ['', '', *sorted(previous), str(year)]
                if self.state['has_budget']: headers += [f'{year} Budget',f'{year} Afvigelse']
                header = '<tr>' + ''.join(f'<td>{h}</td>' for h in headers) + '</tr>'
                table = f'<table><tr><td><table>{header}<tr><td></td><td>Resultatopgørelse</td></tr><tr><td>1101</td><td>Kontingent</td><td>-1.000,00</td></tr><tr><td></td><td>Balance</td></tr><tr><td>PRIVATE_BALANCE_SENTINEL</td></tr></table></td></tr></table>'
            html = f'''<table><tr><td>NAVIGATION_SENTINEL</td></tr></table>
                <iframe name="regnskab" style="visibility:hidden" src="/login/popup.php?page=economy/budget/regnskab_liste.php"></iframe>
                <select name="soeg_afdelinger">{options}</select>
                <button onclick="const doc=window.frames.regnskab.document; const years=[...doc.querySelectorAll('input:checked')].map(e=>e.id.replace('account_','')); location.href='?page=economy/budget/start.php&search=true&old_accounts='+years.join(',')+'&afdeling='+document.querySelector('select').value">Vis</button>{table}'''
        else:
            route.fulfill(status=404)
            raise AssertionError(f'Unexpected synthetic request: {parsed.path}, {section}')
        route.fulfill(body=f'<html><body>{html}</body></html>', content_type='text/html; charset=utf-8')

    def test_fresh_session_hidden_frame_esport_and_explicit_year(self):
        report = self.automation.fetch_report(budget.BudgetReportRequest('Esport',year=2026))
        self.assertTrue(self.state['account'])
        self.assertEqual(self.state['year'],2026)
        self.assertEqual(report['department'],'40: 105. E-sport')
        self.assertEqual(report['years'],[2026,2025,2024])
        self.assertTrue(report['has_budget'])
        self.assertEqual(report['period']['budget_basis'],'full_year')
        self.assertIsNone(report['period']['bookkeeping_cutoff'])
        payload = json.dumps(report)
        self.assertNotIn('PRIVATE_BALANCE_SENTINEL',payload)
        self.assertNotIn('NAVIGATION_SENTINEL',payload)
        self.assertEqual(len(report['tables']),1)
        self.assertFalse(any('edit' in r or 'save' in r for r in self.requests))

    def test_current_year_beats_future_year_and_one_year_has_no_history(self):
        with patch.object(budget,'current_time',return_value=datetime.fromisoformat('2026-10-11T10:00:00+02:00')):
            report = self.automation.fetch_report(budget.BudgetReportRequest('Padel',year_count=1))
        self.assertEqual(report['year'],2026)
        self.assertEqual(report['years'],[2026])
        self.assertEqual(report['comparison_years'],[])

    def test_missing_year_fails_instead_of_using_latest(self):
        with self.assertRaisesRegex(RuntimeError,'Regnskabsår 2023'):
            self.automation.fetch_report(budget.BudgetReportRequest('Esport',year=2023))

    def test_duplicate_account_is_not_guessed(self):
        self.state['duplicate_accounts']=True
        with self.assertRaisesRegex(RuntimeError,'Regnskabet'):
            self.automation.fetch_report(budget.BudgetReportRequest('Esport',year=2026))

    def test_report_year_mismatch_is_rejected(self):
        self.state['wrong_year']=True
        with self.assertRaisesRegex(RuntimeError,'regnskabsår matcher ikke'):
            self.automation.fetch_report(budget.BudgetReportRequest('Esport',year=2026))

    def test_report_department_mismatch_is_rejected(self):
        self.state['wrong_scope']=True
        with self.assertRaisesRegex(RuntimeError,'anden afdeling'):
            self.automation.fetch_report(budget.BudgetReportRequest('Esport',year=2026))

    def test_missing_budget_and_history_are_reported(self):
        self.state['has_budget']=False
        report = self.automation.fetch_report(budget.BudgetReportRequest('Esport',year=2024))
        self.assertFalse(report['has_budget'])
        self.assertEqual(report['years'],[2024])
        self.assertTrue(any('budgetkolonne' in w for w in report['warnings']))
        self.assertTrue(any('Færre historiske' in w for w in report['warnings']))

    def test_broad_request_fails_before_navigation(self):
        with self.assertRaises(ValueError):
            self.automation.fetch_report(budget.BudgetReportRequest('all',year=2026))
        self.assertEqual(self.requests,[])


if __name__ == '__main__':
    unittest.main()
