# Samlet budgetopfølgning for Bredballe IF

## Formål og udtræk

`board-report` laver en PDF til bestyrelsen for alle finansafdelinger i det valgte Bredballe IF-regnskab.
Regnskabs- og afdelingsvalg hentes gennem Conventus-skillens headless-kode. Ingen medlemsopslag,
posteringer, budgetter eller andre Conventus-data ændres.

Der bruges én login-session og et udtrykkeligt bestilt samlet finansscope. Afdelingslisten opdages
for det valgte år; antal og navne er ikke hardcodet. Hvert filter og årsvalg verificeres. Et samlet
afdelingsvalg bruges kun til kontrolrapporten. Hvis listen ændres under udtrækket, stoppes det.

Installer `skills/bredballeif-oekonomi/requirements.txt` i runtime-Python, og installer Playwright
Chromium som samme OS-bruger. PDF-fonten Vera følger med ReportLab på både Windows og Linux.
Der kræves ingen synlig browser, Windows-font eller AI-/fonttjeneste.

## Beregninger og afstemning

- Conventus-indtægter vendes til positive tal. Udgifter vises positive; resultat = indtægt minus udgift.
- Kontoafvigelse og hovedtalsforskel = bogført minus helårsbudget.
- Procent = forskel / absolut budget × 100. Plus på udgift er ugunstigt; plus på indtægt/resultat er gunstigt.
- Ved nulbudget vises `i.m.`. Resultatprocent undertrykkes også ved et meget lille resultatbudget
  relativt til afdelingens indtægts-/udgiftsbudget; standarden er under 1%.
- Konto- og hovedtal afstemmes med `Decimal` uden præsentationsafrunding. Afdelingernes seks hovedtal
  afstemmes mod kontrolrapporten, også budgettet. Difference medfører stop; undersøg bl.a. poster uden afdeling.
- Bruttosummer kan indeholde interne fordelinger. Modposter skal afstemmes, før der argumenteres
  ud fra en enkelt afdelings overskud. Rapporten hævder ikke ekstern konsolidering eller likviditet.

Udtræksdato er ikke bogføringens skæringsdato. Der er intet verificeret periodebudget, og årsager
som sæson, manglende bilag og aktivitet er spørgsmål til afdelingen, ikke dokumenterede forklaringer.
Der dannes ingen helårsprognose uden yderligere forudsætninger.

## Foreslåede ratinger

Standardkriterierne svarer til `assets/rating-policy.json` og gengives med de anvendte grænser i PDF'en.
De er **analytiske forslag**, ikke bestyrelsesgodkendte BIF-regler.

| Rating | Prioritet | Grundlag |
|---|---|---|
| Rød | Høj | Væsentlig samlet udgiftsoverskridelse; resultat under helårsbudget; eller en større udgiftspost over/uden budget. Kombinationer af beløbs- og procentgrænser begrænser udslag fra små budgetbaser. |
| Gul | Afklaring | Mindre overskridelse; indtægtsgab; meget få bogførte udgifter; aktiv afdeling uden beløbsmæssigt budget; eller et tomt område med navnematch til en udgift bogført andetsteds. |
| Grøn | Lav | Ingen udslag på kriterierne. Bogføring og restårsforpligtelser skal stadig bekræftes. |
| Grå | Afklar aktivitet | Nul i bogført og budget samt intet relateret afklaringspunkt. Bekræft, om området er inaktivt. |

Navnematch til en udgift i et andet område er alene et kontrolpunkt og medfører aldrig automatisk
omklassifikation. Områder med forskellige navne, fx Fitness og Fitnesscenter, holdes adskilt.

En privat konfigurationsfil kan ændre udvalgte grænser:

```bash
./bin/bredballeif-oekonomi.sh board-report --year 2026 --rating-policy data/rating-policy.json --output data/reports/opfoelgning.pdf
```

Ukendte parametre, negative grænser og NaN/uendelige tal afvises. PDF'en viser altid de faktisk
anvendte grænser. Ændrede analytiske grænser gør dem ikke automatisk til officielle BIF-regler.

## Genbrug af privat udtræk

Normalt hentes tallene live, og rådata gemmes ikke. Et eksisterende privat JSON fra
`fetch_budget_portfolio` kan genbruges:

```bash
./bin/bredballeif-oekonomi.sh board-report --year 2026 --input data/privat-portefolje.json --output data/reports/ny-opfoelgning.pdf
```

JSON-kontrakten har `year`, `account`, `departments` (liste af `value`/`label`), `reports` (én eksisterende
Conventus-resultatopgørelse pr. label) og `consolidated` (samme rapportformat med
`scope: "all_departments"`). Rapporterne har `year`, `account`, `department`, `retrieved_at` med
tidszone, `period`, `has_budget` og én `tables`-tabel. Manglende afdeling, budget, periode eller
afstemning afvises. `--year` skal matche inputfilens år; PDF'en bruger inputfilens udtræksdato.

## Aflevering og PDF-kontrol

Kommandoen skriver ét JSON-statusobjekt uden finansbeløb. PDF'en skabes først efter dataafstemning;
en eksisterende destination overskrives aldrig. Brug `data/reports/` eller brugerens private destination.
Rapporter med andre destinationer skal holdes ude af git. Rapportfiler under
`docs/analyse/fonde/Budgetopfoelgning_*.pdf` er også ignoreret.

Den indbyggede kontrol genåbner PDF'en og verificerer, at alle afdelingsnavne kan læses. Render
derudover med en tilgængelig PDF-renderer, fx Poppler, og kontrollér siderne visuelt før aflevering.
Kontrollér især lange afdelingsnavne, tabelombrydning, kroner/procent, danske tegn og sidefødder.
Bestyrelsens resume og samlede oversigt kommer først; derefter følger noter for hver afdeling.

Padels sæson-/betalingsforhold fra `references/padel.md` er relevante opfølgningspunkter, men skal
bekræftes som aktuelle. Den genererede rapport stiller spørgsmål og hævder ikke, at forklaringerne
allerede er verificeret.
