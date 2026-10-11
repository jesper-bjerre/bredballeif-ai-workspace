"""Portable board PDF with proposed ratings, evidence and reconciliation."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .analysis import Department, Portfolio, questions, selected_lines

NAVY=colors.HexColor('#142E46')
TEAL=colors.HexColor('#087F8C')
INK=colors.HexColor('#263C4D')
MUTED=colors.HexColor('#617181')
PALE=colors.HexColor('#F1F5F8')
LINE=colors.HexColor('#D9E3EB')
WIDTH=A4[0]-72
RATINGS={
    'Rød':('Høj prioritet','røde','#AC2835','#FCECEF'),
    'Gul':('Afklaring','gule','#936100','#FFF4D9'),
    'Grøn':('Lav prioritet','grønne','#17694F','#E7F4EE'),
    'Grå':('Afklar aktivitet','grå','#617181','#EDF0F3'),
}


def money(value: Decimal, signed: bool=False) -> str:
    rounded=value.quantize(Decimal(1),rounding=ROUND_HALF_UP)
    sign='-' if rounded<0 else '+' if signed and rounded>0 else ''
    return sign+f'{abs(rounded):,.0f}'.replace(',','.')


def percent(value: Decimal | None) -> str:
    if value is None:
        return 'i.m.'
    rounded=value.quantize(Decimal('0.1'),rounding=ROUND_HALF_UP)
    sign='-' if rounded<0 else '+' if rounded>0 else ''
    return sign+f'{abs(rounded):.1f}'.replace('.',',')+'%'


def policy_label(value: Decimal) -> str:
    whole,_,fraction=format(value,'f').partition('.')
    return f'{int(whole):,}'.replace(',','.')+(','+fraction.rstrip('0') if fraction.rstrip('0') else '')


def build_pdf(portfolio: Portfolio) -> tuple[bytes,int]:
    # Vera is shipped with ReportLab; neither Windows fonts nor downloads are needed.
    fonts=Path(reportlab.__file__).resolve().parent/'fonts'
    pdfmetrics.registerFont(TTFont('BIF',str(fonts/'Vera.ttf')))
    pdfmetrics.registerFont(TTFont('BIF-Bold',str(fonts/'VeraBd.ttf')))
    pdfmetrics.registerFontFamily('BIF',normal='BIF',bold='BIF-Bold',italic='BIF',boldItalic='BIF-Bold')
    styles={
        'title':ParagraphStyle('title',fontName='BIF-Bold',fontSize=27,leading=32,textColor=NAVY,spaceAfter=12),
        'h1':ParagraphStyle('h1',fontName='BIF-Bold',fontSize=20,leading=25,textColor=NAVY,spaceAfter=10),
        'h2':ParagraphStyle('h2',fontName='BIF-Bold',fontSize=12,leading=15,textColor=NAVY,spaceBefore=8,spaceAfter=6),
        'body':ParagraphStyle('body',fontName='BIF',fontSize=10,leading=14,textColor=INK,spaceAfter=7),
        'small':ParagraphStyle('small',fontName='BIF',fontSize=8.6,leading=11.6,textColor=INK,spaceAfter=5),
        'tiny':ParagraphStyle('tiny',fontName='BIF',fontSize=7.8,leading=10.4,textColor=MUTED),
        'cell':ParagraphStyle('cell',fontName='BIF',fontSize=8.4,leading=11.4,textColor=INK),
        'num':ParagraphStyle('num',fontName='BIF',fontSize=8.4,leading=11.4,textColor=INK,alignment=TA_RIGHT),
        'thead':ParagraphStyle('thead',fontName='BIF-Bold',fontSize=8,leading=10.6,textColor=colors.white),
        'theadnum':ParagraphStyle('theadnum',fontName='BIF-Bold',fontSize=8,leading=10.6,textColor=colors.white,alignment=TA_RIGHT),
        'card':ParagraphStyle('card',fontName='BIF-Bold',fontSize=12,leading=15,textColor=NAVY,spaceAfter=5),
    }
    def p(text: str, style: str='body') -> Paragraph:
        return Paragraph(text,styles[style])
    def table(data,widths,compact=False,header=True):
        result=Table(data,colWidths=widths,hAlign='LEFT',repeatRows=1 if header else 0)
        rules=[('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),
               ('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),5 if compact else 8),
               ('BOTTOMPADDING',(0,0),(-1,-1),5 if compact else 8),
               ('LINEBELOW',(0,0),(-1,0),0.6,LINE),('LINEBELOW',(0,1),(-1,-1),0.4,LINE)]
        if header:
            rules += [('BACKGROUND',(0,0),(-1,0),NAVY),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,PALE])]
        result.setStyle(TableStyle(rules))
        return result
    def heading(kicker,title,subtitle=None):
        result=[p(escape(kicker.upper()),'tiny'),Spacer(1,6),p(escape(title),'h1')]
        if subtitle:
            result.append(p(escape(subtitle),'small'))
        return result
    def metrics(d: Department,compact=False):
        data=[[p(label,'thead' if i==0 else 'theadnum') for i,label in enumerate(
              ['Hovedtal / kr.',f'Bogført {portfolio.year}','Helårsbudget','Forskel / kr.','Forskel / %'])]]
        for label,key in [('Indtægter','income'),('Udgifter','costs'),('Resultat','result')]:
            values=getattr(d,key)
            pct=d.result_pct(portfolio.policy) if key=='result' else values.pct
            data.append([p(label,'cell'),p(money(values.actual),'num'),p(money(values.budget),'num'),
                         p(money(values.delta,True),'num'),p(percent(pct),'num')])
        return table(data,[WIDTH*.22,WIDTH*.21,WIDTH*.21,WIDTH*.22,WIDTH*.14],compact)

    dates=[]
    for d in portfolio.departments:
        try:
            date=datetime.fromisoformat(d.source['retrieved_at'])
            if date.tzinfo is None:
                raise ValueError('Udtræksdato mangler tidszone')
            dates.append(date)
        except (KeyError,TypeError,ValueError) as exc:
            raise ValueError('En verificerbar udtræksdato med tidszone mangler') from exc
    first,last=min(dates),max(dates)
    date_label=first.strftime('%d.%m.%Y')
    if first.date()!=last.date():
        date_label+=' - '+last.strftime('%d.%m.%Y')
    consolidated=portfolio.consolidated
    ranked=portfolio.ranked
    counts=Counter(d.rating for d in ranked)
    story=[p('BREDBALLE IF / BESTYRELSESRAPPORT','tiny'),Spacer(1,13),
           p(f'Budgetopfølgning<br/>{portfolio.year}','title'),
           p(f'Samlet overblik over {len(ranked)} afdelinger og regnskabsområder','h2'),
           p(f'Conventus-udtræk: {date_label}. Bogførte beløb sammenholdt med helårsbudget. Rapporten er et grundlag for spørgsmål og opfølgning.'),
           metrics(consolidated),Spacer(1,10)]
    cells=[p(f'<font color="{RATINGS[r][2]}"><b>{counts[r]} {RATINGS[r][1]}</b></font><br/>{RATINGS[r][0]}','cell') for r in RATINGS]
    rating_table=table([cells],[WIDTH/4]*4,header=False)
    for i,rating in enumerate(RATINGS):
        rating_table.setStyle(TableStyle([('BACKGROUND',(i,0),(i,0),colors.HexColor(RATINGS[rating][3]))]))
    story += [rating_table,Spacer(1,8),p('Bestyrelsens vigtigste opfølgninger','h2')]
    red=', '.join(d.name for d in ranked if d.rating=='Rød')
    story.append(p('<b>1. Prioritér afklaringer:</b> '+(escape(red)+'. Der er konkrete udslag på rapportens kriterier. Bed om årsag, udestående bilag og restårsforpligtelser.' if red else 'Ingen afdelinger rammer de røde kriterier. Følg de gule punkter og bekræft ajourføringen.'),'small'))
    internal_income=next((line for line in consolidated.lines if line.account=='1124'),None)
    internal_cost=next((line for line in consolidated.lines if line.account=='3125'),None)
    if internal_income and internal_cost:
        story.append(p('<b>2. Afstem interne medlemsbidrag:</b> Hovedkassens indtægt: '+money(internal_income.values.actual)+' kr. mod '+money(internal_income.values.budget)+' kr. i budget. Afdelingernes udgift: '+money(internal_cost.values.actual)+' kr. mod '+money(internal_cost.values.budget)+' kr. Afstem modposter og medlemsgrundlag før afdelingernes resultater bruges til beslutninger.','small'))
    else:
        story.append(p('<b>2. Afstem interne fordelinger:</b> Kontrollér afsender, modtager og restårsforpligtelser for interne bidrag og sponsormidler. Bruttosummer kan indeholde interne overførsler.','small'))
    story.append(p('<b>3. Bekræft bogføring og sæson:</b> Indhent bogføringens ajourføringsdato, aktivitetsstatus og dokumenterede restårsindtægter og -udgifter fra aktive afdelinger. Behandl lave udgifter som et afklaringspunkt, indtil udestående bilag er kontrolleret.','small'))
    story.append(p('<b>Vigtig læsning:</b> Det bogførte resultat på '+money(consolidated.result.actual)+' kr. er ikke en helårsprognose. Budgettet er for hele kalenderåret; en gunstig forskel dokumenterer ikke en besparelse eller et forventet årsoverskud.','small'))
    story.append(p('Ratinger og grænser er rapportens foreslåede prioritering, ikke vedtagne BIF-regler. Grøn betyder lavere prioritet på de viste tal. Bogføringens skæringsdato er ikke verificeret.','tiny'))
    story.append(PageBreak())

    story += heading('Sådan læses rapporten','Grundlag, rating og kontrol')
    story.append(p(f'<b>Afgrænsning:</b> Regnskabet {escape(portfolio.account)}, året {portfolio.year}, alle observerede afdelingsvalg samt en samlet kontrolrapport. Områder uden budget og bogførte beløb er også med.','small'))
    story.append(p('<b>Perioder og fortegn:</b> Helårsbudgettet gælder 1. januar - 31. december. Udtræksdato er ikke bogføringens skæringsdato. Der findes intet verificeret periodebudget. Conventus-indtægter er vendt til positive tal; udgifter vises positivt og resultat = indtægter minus udgifter. Forskel = bogført minus helårsbudget. Plus er gunstigt for indtægt/resultat og ugunstigt for udgift.','small'))
    policy=portfolio.policy
    story.append(p('<b>Procent:</b> Forskel / absolut budget × 100. i.m. = ikke meningsfuld ved nulbudget. Resultatprocent undertrykkes desuden, når resultatbudgettet er under '+policy_label(policy['result_pct_base_min_pct'])+'% af det største indtægts-/udgiftsbudget. DKK og hele kroner i præsentationen; beregninger med øre. Ingen lineær fremskrivning.','small'))
    story.append(p('Foreslåede kriterier for prioritering','h2'))
    def limit(key):
        return policy_label(policy[key])
    criteria=[
        ('Rød',f"Mindst ét kriterium: samlet udgiftsoverskridelse mindst {limit('total_cost_min')} kr. og {limit('total_cost_pct')}%; resultat under helårsbudget med mindst {limit('result_red_min')} kr. og {limit('result_red_cost_pct')}% af udgiftsbudget; eller en udgiftspost over budget med mindst {limit('line_red_min')} kr. og {limit('line_red_cost_pct')}% af afdelingens udgiftsbudget, og enten mindst {limit('line_overrun_pct')}% af postbudgettet eller nulbudget på posten. Nulbudget opfylder et procentkrav på samlet udgift."),
        ('Gul',f"Ingen røde kriterier, men aktivt område uden beløbsmæssigt budget; en udgiftspost over budget mindst {limit('line_amber_min')} kr. og {limit('line_overrun_pct')}% (eller nulbudget); resultatgab mindst {limit('result_amber_min')} kr.; indtægtsgab mindst {limit('income_gap_min')} kr. og {limit('income_gap_pct')}%; en indtægtspost mangler mindst {limit('income_line_gap_min')} kr. og {limit('income_line_gap_pct')}%; eller højst {limit('low_cost_execution_pct')}% af udgiftsbudget på mindst {limit('low_cost_budget_min')} kr. er bogført. Tomt område med navnematch til en udgift andetsteds giver også et afklaringspunkt."),
        ('Grøn','Ingen af ovenstående kriterier. Kontrollér stadig bogføringens ajourføring og dokumenterede restårsforpligtelser.'),
        ('Grå','Intet beløbsmæssigt budget, ingen bogførte beløb og intet relateret afklaringspunkt. Bekræft om området er uden aktivitet.'),
    ]
    for rating,text in criteria:
        story.append(p(f'<font color="{RATINGS[rating][2]}"><b>{rating.upper()} / {RATINGS[rating][0]}:</b></font> '+text,'small'))
    story.append(p('Afstemning og kilde','h2'))
    story.append(p('Alle kontolinjer stemmer til hovedtallene, og indtægter minus udgifter stemmer til resultatet. Summen af afdelingernes bogførte beløb og budget stemmer til den samlede Conventus-rapport: 0,00 kr. i difference i alle seks hovedtal. Tallene er bruttosummer før særskilt eliminering af interne indtægter og udgifter.','small'))
    story.append(p(f'Kilde: Conventus / {escape(portfolio.account)} / {portfolio.year} / Budget og Resultatopgørelse. Udtræk {date_label}, {first:%H:%M} - {last:%H:%M} (UTC{first:%z}). Bogføringens skæringsdato er ukendt. Balance, bankkonti og medlemsdata er udeladt. Afvigelsesårsager og helårsprognose kræver supplerende dokumentation.','tiny'))
    story.append(PageBreak())

    overview_count=(len(ranked)+9)//10
    for part in range(overview_count):
        story += heading(f'Bestyrelsens oversigt / {part+1} af {overview_count}','Afdelinger i prioriteret rækkefølge',
                         'Alle forskelle er bogført minus helårsbudget. Afdelingsnoterne viser kontoafvigelser og spørgsmål.')
        data=[[p(label,'thead' if i<2 else 'theadnum') for i,label in enumerate(
              ['Afdeling / rating','Fokus for opfølgning','Indtægt: forskel','Udgift: forskel','Resultat: forskel'])]]
        for d in ranked[part*10:(part+1)*10]:
            row=[p(f'<b>{escape(d.name)}</b><br/><font color="{RATINGS[d.rating][2]}">{d.rating.upper()}</font>','cell'),p(escape(d.reason),'cell')]
            for key in ('income','costs','result'):
                values=getattr(d,key)
                pct=d.result_pct(policy) if key=='result' else values.pct
                row.append(p(money(values.delta,True)+' kr.<br/>'+percent(pct),'num'))
            data.append(row)
        story += [table(data,[WIDTH*.19,WIDTH*.30,WIDTH*.17,WIDTH*.17,WIDTH*.17]),Spacer(1,9),
                  p('i.m. = nul eller uegnet procentgrundlag. En positiv resultatforskel er en bogført position mod helårsbudget, ikke en prognose.','tiny'),PageBreak()]

    detail_count=(len(ranked)+1)//2
    for part in range(detail_count):
        story += heading(f'Afdelingsnoter / {part+1} af {detail_count}','Hovedtal og væsentlige poster',
                         'Forskel mod helårsbudget. Mindre udgifter er ikke nødvendigvis besparelser; årsager skal afklares.')
        for d in ranked[part*2:(part+1)*2]:
            card=[p(escape(d.name)+f' <font color="{RATINGS[d.rating][2]}">/ {d.rating.upper()}</font>','card'),metrics(d,True),Spacer(1,4)]
            selected=selected_lines(d,policy)
            if selected:
                data=[[p('Væsentlige kontoposter','thead'),p('Bogført / budget','theadnum'),p('Forskel / kr. og %','theadnum')]]
                for line in selected:
                    kind='Indtægt' if line.kind=='income' else 'Udgift'
                    data.append([p(escape(line.account+' '+line.name)+f'<br/><font color="{MUTED.hexval()}">{kind}</font>','cell'),
                                 p(money(line.values.actual)+' / '+money(line.values.budget),'num'),
                                 p(money(line.values.delta,True)+'<br/>'+percent(line.values.pct),'num')])
                card.append(table(data,[WIDTH*.49,WIDTH*.27,WIDTH*.24],True))
            else:
                card.append(p('Ingen kontoposter med beløbsafvigelse.','small'))
            card += [Spacer(1,5),p('<b>Opfølgning:</b> '+escape(' '.join(questions(d,policy))),'small'),Spacer(1,12)]
            story.append(KeepTogether(card))
        if part+1<detail_count:
            story.append(PageBreak())

    def decorate(canvas,doc):
        canvas.saveState()
        canvas.setFillColor(TEAL); canvas.rect(0,A4[1]-7,A4[0],7,fill=1,stroke=0)
        canvas.setFillColor(NAVY); canvas.setFont('BIF-Bold',8)
        canvas.drawString(36,A4[1]-26,'BREDBALLE IF')
        canvas.setFillColor(MUTED); canvas.setFont('BIF',8)
        canvas.drawRightString(A4[0]-36,A4[1]-26,f'BUDGETOPFØLGNING {portfolio.year}')
        canvas.setStrokeColor(LINE); canvas.line(36,36,A4[0]-36,36)
        canvas.setFont('BIF',7)
        canvas.drawString(36,23,f'Bestyrelsen | Conventus {date_label} | Internt arbejdsgrundlag')
        canvas.drawRightString(A4[0]-36,23,f'Side {doc.page}')
        canvas.restoreState()
    output=BytesIO()
    doc=SimpleDocTemplate(output,pagesize=A4,leftMargin=36,rightMargin=36,topMargin=48,bottomMargin=48,
                          title=f'Bredballe IF - Samlet budgetopfølgning {portfolio.year}',author='Bredballe IF')
    doc.build(story,onFirstPage=decorate,onLaterPages=decorate)
    result=output.getvalue()
    reader=PdfReader(BytesIO(result))
    text=' '.join(' '.join((page.extract_text() or '').split()) for page in reader.pages)
    for d in ranked:
        if ' '.join(d.name.split()) not in text:
            raise ValueError('PDF-kontrollen fandt ikke alle afdelinger')
    return result,len(reader.pages)
