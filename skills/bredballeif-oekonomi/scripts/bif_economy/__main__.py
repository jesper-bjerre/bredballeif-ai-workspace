"""Agent-neutral CLI: python -m bif_economy board-report."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from .analysis import analyze, load_policy


def fetch_live(year: int | None) -> dict:
    skill=Path(__file__).resolve().parents[2]
    sibling=skill.parent/'bredballeif-padel-conventus/scripts'
    if not (sibling/'conventus_budget_automation.py').is_file():
        raise ValueError('Importér bredballeif-padel-conventus som søskende til økonomi-skillen')
    sys.path.insert(0,str(sibling))
    from dotenv import load_dotenv
    for candidate in (skill,*skill.parents):
        if (candidate/'.env').is_file():
            load_dotenv(candidate/'.env')
            break
    from conventus_budget_automation import fetch_budget_portfolio
    return fetch_budget_portfolio(year=year)


def main(argv: list[str] | None=None) -> int:
    parser=argparse.ArgumentParser(description='Bredballe IF økonomi: samlet budgetopfølgning til bestyrelsen')
    actions=parser.add_subparsers(dest='action',required=True)
    board=actions.add_parser('board-report',help='Alle finansafdelinger, afstemning, foreslåede ratinger og PDF')
    board.add_argument('--year',type=int,help='Regnskabs- og budgetår; ellers indeværende år i København')
    board.add_argument('--output',type=Path,required=True,help='Privat PDF-destination; brug / på både Windows og Linux')
    board.add_argument('--input',type=Path,help='Genbrug et privat portefølje-JSON; ellers hent fra Conventus')
    board.add_argument('--rating-policy',type=Path,help='JSON med egne analytiske grænser; øvrige bruger standarden')
    args=parser.parse_args(argv)
    try:
        if args.year is not None and not 1900<=args.year<=2099:
            raise ValueError('Regnskabsår skal være mellem 1900 og 2099')
        if args.output.suffix.lower()!='.pdf':
            raise ValueError('Output skal være en PDF-fil')
        if args.output.exists():
            raise ValueError('Outputfilen findes allerede; vælg et nyt filnavn')
        policy=load_policy(args.rating_policy)
        from .pdf_report import build_pdf
        payload=json.loads(args.input.read_text(encoding='utf-8')) if args.input else fetch_live(args.year)
        if not isinstance(payload,dict):
            raise ValueError('Input skal være et komplet portefølje-JSON-objekt')
        if payload.get('account')!='Bredballe IF':
            raise ValueError('Denne bestyrelsesrapport kræver regnskabet Bredballe IF')
        if args.year is not None and payload.get('year')!=args.year:
            raise ValueError('Inputfilens år matcher ikke det bestilte år')
        portfolio=analyze(payload,policy)
        contents,pages=build_pdf(portfolio)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        # Create exclusively: existing reports are never overwritten by this CLI.
        fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(contents)
        except BaseException:
            args.output.unlink(missing_ok=True)
            raise
        print(json.dumps({'status':'ok','year':portfolio.year,'departments':len(portfolio.departments),
                          'ratings':dict(Counter(d.rating for d in portfolio.departments)),
                          'reconciliation':'ok','pages':pages,'output':str(args.output.resolve())},ensure_ascii=False))
        return 0
    except ImportError:
        print('Runtime-dependency mangler; installer skills/bredballeif-oekonomi/requirements.txt i wrapperens Python-miljø.',file=sys.stderr)
    except (ValueError,RuntimeError,OSError) as exc:
        print(str(exc),file=sys.stderr)
    except (KeyError,TypeError,IndexError):
        print('Input er ikke et komplet, gyldigt Conventus-porteføljeudtræk.',file=sys.stderr)
    return 1


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
