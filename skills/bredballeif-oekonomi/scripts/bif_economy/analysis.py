"""Account-level validation, Decimal arithmetic and proposed rating criteria."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ZERO = Decimal(0)
POLICY_PATH = Path(__file__).resolve().parents[2] / 'assets/rating-policy.json'


def load_policy(path: Path | None = None) -> dict[str, Decimal]:
    defaults = json.loads(POLICY_PATH.read_text(encoding='utf-8'))
    overrides = json.loads(path.read_text(encoding='utf-8')) if path else {}
    if not isinstance(overrides, dict) or set(overrides)-set(defaults):
        raise ValueError('Ukendte ratingparametre; brug skabelonen assets/rating-policy.json')
    try:
        values = {key: Decimal(str(overrides.get(key, value))) for key, value in defaults.items()}
    except InvalidOperation:
        raise ValueError('Ratinggrænser skal være tal') from None
    if any(not value.is_finite() or value < 0 for value in values.values()):
        raise ValueError('Ratinggrænser skal være endelige, ikke-negative tal')
    return values


def amount(text: str) -> Decimal:
    if not isinstance(text,str):
        raise ValueError('Conventus-beløb skal være tekst i dansk talformat')
    text = text.strip().replace('\xa0', '')
    if not text:
        return ZERO
    if not re.fullmatch(r'-?\d+(?:\.\d{3})*(?:,\d{2})?', text):
        raise ValueError('Et Conventus-beløb kunne ikke læses sikkert')
    return Decimal(text.replace('.', '').replace(',', '.'))


def normalize(text: str) -> str:
    return re.sub(r'[\W_]+', '', text.casefold())


@dataclass(frozen=True)
class Pair:
    actual: Decimal
    budget: Decimal

    @property
    def delta(self) -> Decimal:
        return self.actual - self.budget

    @property
    def pct(self) -> Decimal | None:
        return self.delta / abs(self.budget) * 100 if self.budget else None


@dataclass(frozen=True)
class Line:
    account: str
    name: str
    kind: str
    values: Pair


@dataclass
class Department:
    label: str
    name: str
    income: Pair
    costs: Pair
    result: Pair
    lines: list[Line]
    source: dict[str, Any]
    rating: str = ''
    reason: str = ''
    related: list[tuple[str, Line]] = field(default_factory=list)

    @property
    def adverse(self) -> list[Line]:
        return sorted((line for line in self.lines if line.kind=='cost' and line.values.delta>0),
                      key=lambda line: line.values.delta, reverse=True)

    def result_pct(self, policy: dict[str, Decimal]) -> Decimal | None:
        base = abs(self.result.budget)
        scale = max(abs(self.income.budget), abs(self.costs.budget))
        return self.result.pct if base and base>=scale*policy['result_pct_base_min_pct']/100 else None


@dataclass
class Portfolio:
    year: int
    account: str
    departments: list[Department]
    consolidated: Department
    policy: dict[str, Decimal]

    @property
    def ranked(self) -> list[Department]:
        priority = {'Rød':0, 'Gul':1, 'Grøn':2, 'Grå':3}
        return sorted(self.departments, key=lambda d:(priority[d.rating],
                      -max((line.values.delta for line in d.adverse),default=ZERO), d.name))


def parse_report(report: dict[str, Any], year: int, account: str) -> Department:
    if not isinstance(report,dict):
        raise ValueError('En resultatopgørelse har forkert format')
    if report.get('year')!=year or report.get('account')!=account:
        raise ValueError('Rapporternes regnskab eller år matcher ikke bestillingen')
    if not report.get('has_budget'):
        raise ValueError('En rapport mangler årets budgetkolonne; rating kan ikke beregnes')
    period=report.get('period', {})
    if period.get('budget_basis')!='full_year' or period.get('from')!=f'{year}-01-01' or period.get('to')!=f'{year}-12-31':
        raise ValueError('Rapportens budgetperiode kunne ikke verificeres')
    tables=report.get('tables', [])
    if not isinstance(tables,list) or len(tables)!=1:
        raise ValueError('Resultatopgørelsen skal bestå af én tabel')
    rows=tables[0]
    if not isinstance(rows,list) or not rows or any(not isinstance(row,list) or len(row)<2 or
            any(not isinstance(cell,str) for cell in row) for row in rows):
        raise ValueError('Resultatopgørelsens rækker har forkert format')
    if rows[0].count(str(year))!=1 or rows[0].count(f'{year} Budget')!=1:
        raise ValueError('Års- og budgetkolonnerne findes ikke entydigt')
    try:
        actual_index=rows[0].index(str(year))
        budget_index=rows[0].index(f'{year} Budget')
        def total(label: str, factor: int=1) -> Pair:
            matches=[row for row in rows if len(row)>1 and row[1]==label]
            if len(matches)!=1:
                raise ValueError('Et hovedtal mangler eller er dubleret: '+label)
            row=matches[0]
            return Pair(factor*amount(row[actual_index]), factor*amount(row[budget_index]))
        income=total('Indtægter i alt', -1)
        costs=total('Udgifter i alt')
        result=total('Resultat før overførsel til Balance', -1)
        income_end=next(i for i,row in enumerate(rows) if row[1]=='Indtægter i alt')
        result_start=next(i for i,row in enumerate(rows) if row[1]=='Resultat før overførsel til Balance')
        if income_end>=result_start:
            raise ValueError('Resultatopgørelsens struktur er ændret')
        lines=[]
        accounts=set()
        for index,row in enumerate(rows[:result_start]):
            if not re.fullmatch(r'\d+', row[0]):
                continue
            if row[0] in accounts:
                raise ValueError('En konto er dubleret i resultatopgørelsen')
            accounts.add(row[0])
            kind='income' if index<income_end else 'cost'
            factor=-1 if kind=='income' else 1
            values=Pair(factor*amount(row[actual_index]), factor*amount(row[budget_index]))
            if values.actual or values.budget:
                lines.append(Line(row[0],row[1],kind,values))
    except (IndexError, KeyError, TypeError, StopIteration) as exc:
        raise ValueError('Ufuldstændig resultatopgørelse; rapporten kan ikke afstemmes') from exc
    for kind, expected in [('income',income),('cost',costs)]:
        if sum((line.values.actual for line in lines if line.kind==kind),ZERO)!=expected.actual or \
                sum((line.values.budget for line in lines if line.kind==kind),ZERO)!=expected.budget:
            raise ValueError('Kontolinjerne stemmer ikke til hovedtallene')
    if income.actual-costs.actual!=result.actual or income.budget-costs.budget!=result.budget:
        raise ValueError('Indtægter minus udgifter stemmer ikke til resultatet')
    label=report['department']
    name=re.sub(r'^\d+\s*:\s*\d+\.\s*', '', label).strip()
    return Department(label,name,income,costs,result,lines,report)


def rate(d: Department, policy: dict[str, Decimal]) -> tuple[str,str]:
    def pct_of(value: Decimal, base: Decimal, threshold: Decimal) -> bool:
        return value>=abs(base)*threshold/100
    if not any([d.income.actual,d.income.budget,d.costs.actual,d.costs.budget]):
        return ('Gul','Ingen egne tal; relateret udgift i et andet område.') if d.related else \
               ('Grå','Intet beløbsmæssigt budget og ingen bogførte beløb.')
    if d.costs.delta>=policy['total_cost_min'] and pct_of(d.costs.delta,d.costs.budget,policy['total_cost_pct']):
        return 'Rød','Samlede udgifter overstiger helårsbudgettet væsentligt.'
    if -d.result.delta>=policy['result_red_min'] and pct_of(-d.result.delta,d.costs.budget,policy['result_red_cost_pct']):
        return 'Rød','Resultatet ligger væsentligt under helårsbudgettet.'
    def overrun(line: Line) -> bool:
        return line.values.pct is None or line.values.pct>=policy['line_overrun_pct']
    if any(line.values.delta>=policy['line_red_min'] and
           pct_of(line.values.delta,d.costs.budget,policy['line_red_cost_pct']) and overrun(line) for line in d.adverse):
        return 'Rød','Væsentlig udgift uden budget eller over helårsbudget.'
    if not d.income.budget and not d.costs.budget:
        return 'Gul','Bogførte beløb, men intet beløbsmæssigt budget.'
    if any(line.values.delta>=policy['line_amber_min'] and overrun(line) for line in d.adverse):
        return 'Gul','En udgiftspost kræver forklaring eller budgetafklaring.'
    if -d.result.delta>=policy['result_amber_min']:
        return 'Gul','Resultatet ligger under helårsbudgettet.'
    if -d.income.delta>=policy['income_gap_min'] and pct_of(-d.income.delta,d.income.budget,policy['income_gap_pct']):
        return 'Gul','Indtægtsgabet kræver afklaring af sæson og aktivitet.'
    if any(line.kind=='income' and -line.values.delta>=policy['income_line_gap_min'] and
           line.values.pct is not None and -line.values.pct>=policy['income_line_gap_pct'] for line in d.lines):
        return 'Gul','Større indtægtspost mangler en væsentlig del af helårsbudget.'
    if d.costs.budget>=policy['low_cost_budget_min'] and d.costs.actual<=d.costs.budget*policy['low_cost_execution_pct']/100:
        return 'Gul','Meget få udgifter mod helårsbudget; afstem bogføring.'
    return 'Grøn','Ingen udslag på rapportens væsentlighedskriterier.'


def analyze(payload: dict[str, Any], policy: dict[str, Decimal]) -> Portfolio:
    if not isinstance(payload,dict):
        raise ValueError('Porteføljeudtrækket skal være et JSON-objekt')
    year=payload['year']; account=payload['account']
    if not isinstance(year,int) or not 1900<=year<=2099 or not isinstance(account,str) or not account.strip():
        raise ValueError('Ugyldigt regnskabsår eller regnskabsnavn')
    options=payload['departments']; reports=payload['reports']
    if not isinstance(options,list) or not isinstance(reports,list) or any(
            not isinstance(option,dict) or not isinstance(option.get('value'),str) or
            not isinstance(option.get('label'),str) for option in options) or any(
            not isinstance(report,dict) for report in reports):
        raise ValueError('Afdelingsliste eller rapportliste har forkert format')
    if not options or len(options)!=len(reports) or any(option['value']=='0' or not option['label'] for option in options):
        raise ValueError('Udtrækket dækker ikke den observerede afdelingsliste')
    if len({option['value'] for option in options})!=len(options) or len({option['label'] for option in options})!=len(options):
        raise ValueError('Afdelingslisten indeholder dubletter')
    if {report['department'] for report in reports}!={option['label'] for option in options}:
        raise ValueError('Udtrækket dækker ikke de samme afdelinger som afdelingslisten')
    departments=[parse_report(report,year,account) for report in reports]
    if payload['consolidated'].get('scope')!='all_departments':
        raise ValueError('En samlet kontrolrapport for alle afdelinger mangler')
    consolidated=parse_report(payload['consolidated'],year,account)
    for key in ('income','costs','result'):
        for field_name in ('actual','budget'):
            if sum((getattr(getattr(d,key),field_name) for d in departments),ZERO)!=getattr(getattr(consolidated,key),field_name):
                raise ValueError('Afdelingerne stemmer ikke til den samlede kontrolrapport; afklar poster uden afdeling')
    # A name match flags a question, never an inferred reclassification.
    for d in departments:
        if not any([d.income.actual,d.income.budget,d.costs.actual,d.costs.budget]) and len(normalize(d.name))>=4:
            d.related=[(other.name,line) for other in departments if other is not d for line in other.lines
                       if line.kind=='cost' and line.values.actual>0 and normalize(d.name) in normalize(line.name)]
        d.rating,d.reason=rate(d,policy)
    return Portfolio(year,account,departments,consolidated,policy)


def selected_lines(d: Department, policy: dict[str,Decimal]) -> list[Line]:
    selected=sorted((line for line in d.lines if line.values.delta),key=lambda line:abs(line.values.delta),reverse=True)[:3]
    if d.rating in ('Rød','Gul') and d.adverse and d.adverse[0].values.delta>=policy['line_amber_min'] and d.adverse[0] not in selected:
        selected=selected[:2]+[d.adverse[0]]
    return selected


def questions(d: Department, policy: dict[str,Decimal]) -> list[str]:
    result=[]
    if d.related:
        locations=', '.join(sorted({name for name,line in d.related}))
        result.append('Afstem relaterede udgifter i '+locations+'; bekræft budget- og konteringsansvar uden at ompostere på baggrund af navnet alene.')
    if d.rating=='Grå':
        return ['Bekræft at området er uden aktivitet, og at eventuelle aktiviteter ikke er bogført andetsteds.']
    if d.lines and not d.income.budget and not d.costs.budget:
        result.append('Afstem bogførte indtægter og forventede udgifter, og forelæg et beløbsmæssigt budget for bestyrelsen.')
    if d.adverse and d.adverse[0].values.delta>=policy['line_amber_min']:
        result.append('Forklar '+d.adverse[0].account+' '+d.adverse[0].name+' over eller uden budget; afstem aktivitet, godkendelse og resterende forpligtelser.')
    if any(line.account in ('1190','2390') for line in d.lines):
        result.append('Afstem salgsregistrering, varekøb og lager for at forklare vareforbrug og bruttoavance.')
    if d.costs.budget>=policy['low_cost_budget_min'] and d.costs.actual<=d.costs.budget*policy['low_cost_execution_pct']/100:
        result.append('Er udgifter og bilag ajourført? Afstem gennemførte aktiviteter og endnu ikke bogførte omkostninger.')
    specific={'1150':'Hvilke sponsormidler afventer fakturering, betaling eller intern overførsel? Afstem kontrakter og modposter.',
              '3122':'Hvornår bogføres budgetterede lån og afskrivninger?',
              '3125':'Afstem medlemsbidrag mod aktuelt medlemstal og hovedkassens modpost.',
              '1124':'Afstem interne medlemsbidrag mod afdelingernes modposter og medlemsgrundlag.',
              '3190':'Afstem viderefordeling af sponsormidler mod modtagernes poster og resterende forpligtelser.'}
    for line in d.lines:
        if line.account in specific and line.values.budget and line.values.actual<line.values.budget:
            result.append(specific[line.account])
            break
    if d.income.delta<0:
        result.append('Hvilke indtægter og aktiviteter resterer? Afklar sæson, fakturering og eventuel permanent ændring.')
    if normalize(d.name)=='padel':
        result.insert(0,'Afstem banelejens kvartalsbetalinger, efterårskontingenter og sponsorfakturering; bekræft at Padel-forudsætningerne fortsat gælder.')
    return result[:3] or ['Bekræft bogføringens ajourføring og resterende indtægter og udgifter før helårsresultatet vurderes.']
