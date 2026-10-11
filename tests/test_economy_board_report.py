"""Synthetic finances only: reconciliation, ratings, CLI and portable PDF."""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/bredballeif-oekonomi/scripts'))
from bif_economy.analysis import analyze, load_policy, Pair, Department, Line, rate, amount, questions
from bif_economy.pdf_report import build_pdf, money
from bif_economy.__main__ import main
from pypdf import PdfReader


def dk(value):
    return f'{value:.2f}'.replace('.',',')


def report(label, income=(1000,2000), cost=(400,1000), year=2026):
    rows=[['','',str(year),f'{year} Budget'],['','Resultatopgørelse','',''],
          ['1104','Kontingent 25-60år',dk(-income[0]),dk(-income[1])],
          ['','Indtægter i alt',dk(-income[0]),dk(-income[1])],
          ['2310','Materialer',dk(cost[0]),dk(cost[1])],
          ['','Udgifter i alt',dk(cost[0]),dk(cost[1])],
          ['','Resultat før overførsel til Balance',dk(cost[0]-income[0]),dk(cost[1]-income[1])]]
    return {'account':'Bredballe IF','year':year,'department':label,'has_budget':True,
            'period':{'from':f'{year}-01-01','to':f'{year}-12-31','budget_basis':'full_year','bookkeeping_cutoff':None},
            'retrieved_at':'2026-10-11T10:00:00+02:00','tables':[rows]}


def fixture(year=2026):
    labels=['10: 100. Test ÆØÅ','20: 101. Test Beta']
    return {'account':'Bredballe IF','year':year,
            'departments':[{'value':str(i+1),'label':label} for i,label in enumerate(labels)],
            'reports':[report(labels[0],year=year),report(labels[1],(500,1000),(200,500),year)],
            'consolidated':dict(report('',(1500,3000),(600,1500),year),scope='all_departments')}


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.policy=load_policy()

    def test_full_reconciliation_and_signs(self):
        portfolio=analyze(fixture(),self.policy)
        self.assertEqual(portfolio.consolidated.result,Pair(Decimal(900),Decimal(1500)))
        self.assertEqual(portfolio.consolidated.income.delta,Decimal(-1500))

    def test_rejects_wrong_year_missing_budget_duplicate_and_missing_department(self):
        payloads=[]
        data=fixture();data['reports'][0]['year']=2025;payloads.append(data)
        data=fixture();data['reports'][0]['has_budget']=False;payloads.append(data)
        data=fixture();data['departments'][1]=data['departments'][0];payloads.append(data)
        data=fixture();data['reports']=data['reports'][:1];payloads.append(data)
        for payload in payloads:
            with self.subTest(payload=payload),self.assertRaises(ValueError):
                analyze(payload,self.policy)

    def test_stops_on_account_and_portfolio_reconciliation_differences(self):
        data=fixture();data['reports'][0]['tables'][0][2][2]='-999,00'
        with self.assertRaisesRegex(ValueError,'Kontolinjerne'):
            analyze(data,self.policy)
        data=fixture();data['consolidated']=dict(report('',(1600,3000),(600,1500)),scope='all_departments')
        with self.assertRaisesRegex(ValueError,'samlede kontrolrapport'):
            analyze(data,self.policy)

    def test_rejects_malformed_rows_and_ambiguous_headers(self):
        for invalid in ('not a table', [['short']], [['','', '2026','2026','2026 Budget']]):
            data=fixture();data['reports'][0]['tables']=[invalid]
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                analyze(data,self.policy)
        with self.assertRaises(ValueError):amount(10)

    def test_sales_and_stock_generate_a_relevant_question(self):
        data=fixture()
        data['reports'][0]['tables'][0][4][0]='2390'
        d=analyze(data,self.policy).departments[0]
        self.assertTrue(any('varekøb og lager' in question for question in questions(d,self.policy)))

    def test_amount_validation_and_zero_percent(self):
        self.assertEqual(amount('-1.234,56'),Decimal('-1234.56'))
        self.assertIsNone(Pair(Decimal(10),Decimal(0)).pct)
        for value in ('NaN','1234.56','1.23,00','PRIVATE_SENTINEL'):
            with self.assertRaises(ValueError): amount(value)

    def test_rating_boundaries_and_zero_budget(self):
        pair=lambda a,b:Pair(Decimal(a),Decimal(b))
        def dept(ia,ib,ca,cb,lines=None):
            return Department('Test','Test',pair(ia,ib),pair(ca,cb),pair(ia-ca,ib-cb),lines or [],{})
        self.assertEqual(rate(dept(0,0,0,0),self.policy)[0],'Grå')
        self.assertEqual(rate(dept(10000,10000,10000,0),self.policy)[0],'Rød')
        self.assertEqual(rate(dept(100000,100000,110000,100000),self.policy)[0],'Rød')
        self.assertEqual(rate(dept(100000,100000,109999,100000),self.policy)[0],'Gul')
        self.assertEqual(rate(dept(80000,100000,50000,100000),self.policy)[0],'Gul')
        self.assertEqual(rate(dept(7999,10000,5000,10000),self.policy)[0],'Grøn')
        self.assertEqual(rate(dept(1000,0,0,0),self.policy)[0],'Gul')
        line=Line('2313','Tøj','cost',pair(25000,0))
        self.assertEqual(rate(dept(100000,100000,50000,100000,[line]),self.policy)[0],'Rød')
        self.assertEqual(rate(dept(1000000,1000000,50000,1000000,[line]),self.policy)[0],'Gul')

    def test_custom_policy_and_small_result_base(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'policy.json'
            for value in ('NaN',-1):
                path.write_text(json.dumps({'line_red_min':value}))
                with self.assertRaises(ValueError):load_policy(path)
            path.write_text(json.dumps({'unknown':100}))
            with self.assertRaises(ValueError):load_policy(path)
            path.write_text(json.dumps({'line_red_min':'50000'}))
            self.assertEqual(load_policy(path)['line_red_min'],Decimal(50000))
        d=analyze(fixture(),self.policy).departments[0]
        d.result=Pair(Decimal(500),Decimal(1))
        self.assertIsNone(d.result_pct(self.policy))

    def test_inactive_area_with_related_cost_is_amber(self):
        data=fixture()
        data['reports'][0]=report('10: 100. Test ÆØÅ',(0,0),(0,0))
        data['reports'][1]['tables'][0][4][1]='Udgifter Test ÆØÅ'
        data['consolidated']=dict(report('',(500,1000),(200,500)),scope='all_departments')
        result=analyze(data,self.policy)
        self.assertEqual(result.departments[0].rating,'Gul')
        self.assertEqual(len(result.departments[0].related),1)


class PdfAndCliTests(unittest.TestCase):
    def test_portable_pdf_contains_all_departments_year_and_evidence(self):
        data=fixture(year=2025)
        portfolio=analyze(data,load_policy())
        content,pages=build_pdf(portfolio)
        pdf=PdfReader(io.BytesIO(content))
        self.assertEqual(len(pdf.pages),pages)
        text=' '.join(page.extract_text() for page in pdf.pages)
        self.assertIn('Test ÆØÅ',text)
        self.assertIn('Test Beta',text)
        self.assertIn('2025',text)
        self.assertIn('ikke en helårsprognose',text)
        self.assertIn('0,00 kr.',text)
        for d in portfolio.departments:
            self.assertIn(money(d.result.actual),text)

    def test_pdf_describes_fractional_custom_limits_without_rounding(self):
        policy=load_policy()
        policy['line_overrun_pct']=Decimal('20.5')
        policy['result_pct_base_min_pct']=Decimal('0.5')
        content,_=build_pdf(analyze(fixture(),policy))
        text=' '.join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)
        self.assertIn('20,5%',text)
        self.assertIn('0,5%',text)

    def test_cli_outputs_only_status_metadata_and_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.json';output=Path(folder)/'report.pdf'
            source.write_text(json.dumps(fixture()),encoding='utf-8')
            stdout=io.StringIO()
            with patch('sys.stdout',stdout):
                self.assertEqual(main(['board-report','--year','2026','--input',str(source),'--output',str(output)]),0)
            status=json.loads(stdout.getvalue())
            self.assertEqual(status['departments'],2)
            self.assertNotIn('income',status)
            previous=output.read_bytes()
            with patch('sys.stderr',io.StringIO()):
                self.assertEqual(main(['board-report','--input',str(source),'--output',str(output)]),1)
            self.assertEqual(output.read_bytes(),previous)

    def test_invalid_request_or_input_does_not_fetch_or_write(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'report.pdf'
            with patch('bif_economy.__main__.fetch_live') as fetch,patch('sys.stderr',io.StringIO()):
                self.assertEqual(main(['board-report','--year','2100','--output',str(output)]),1)
                fetch.assert_not_called()
            source=Path(folder)/'source.json'
            source.write_text(json.dumps(fixture()),encoding='utf-8')
            with patch('sys.stderr',io.StringIO()):
                self.assertEqual(main(['board-report','--year','2025','--input',str(source),'--output',str(output)]),1)
            data=fixture()
            data['account']='Andet regnskab'
            for report_data in [*data['reports'],data['consolidated']]:
                report_data['account']='Andet regnskab'
            source.write_text(json.dumps(data),encoding='utf-8')
            with patch('sys.stderr',io.StringIO()):
                self.assertEqual(main(['board-report','--input',str(source),'--output',str(output)]),1)
            self.assertFalse(output.exists())

    def test_windows_wrapper_routes_help_and_rejects_member_and_write_actions(self):
        if sys.platform!='win32':self.skipTest('PowerShell wrapper check on Windows')
        wrapper=ROOT/'skills/bredballeif-oekonomi/bin/bredballeif-oekonomi.ps1'
        help_result=subprocess.run(['pwsh','-NoProfile','-File',str(wrapper),'board-report','--help'],capture_output=True)
        self.assertEqual(help_result.returncode,0)
        self.assertIn(b'--output',help_result.stdout)
        for action in ('search','list','create-group'):
            result=subprocess.run(['pwsh','-NoProfile','-File',str(wrapper),action],capture_output=True)
            self.assertNotEqual(result.returncode,0)


if __name__=='__main__':
    unittest.main()
