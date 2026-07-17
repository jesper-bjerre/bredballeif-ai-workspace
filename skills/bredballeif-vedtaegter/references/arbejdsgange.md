# Arbejdsgange for vedtægtsbestemte opgaver

## Indhold

- [Fælles udførelsesmodel](#fælles-udførelsesmodel)
- [Besvar et spørgsmål eller placér kompetence](#besvar-et-spørgsmål-eller-placér-kompetence)
- [Kontrollér en beslutning](#kontrollér-en-beslutning)
- [Ordinær generalforsamling](#ordinær-generalforsamling)
- [Ekstraordinær generalforsamling](#ekstraordinær-generalforsamling)
- [Digital generalforsamling](#digital-generalforsamling)
- [Afdelingens årlige leverancer](#afdelingens-årlige-leverancer)
- [Afdelingens årlige medlemsmøde](#afdelingens-årlige-medlemsmøde)
- [Afdelingens forretningsorden](#afdelingens-forretningsorden)
- [Opret eller nedlæg en afdeling](#opret-eller-nedlæg-en-afdeling)
- [Udmeldelse, eksklusion og karantæne](#udmeldelse-eksklusion-og-karantæne)
- [Regnskab, budget og revision](#regnskab-budget-og-revision)
- [Tegningsret og fast ejendom](#tegningsret-og-fast-ejendom)
- [Vedtægtsændring og opløsning](#vedtægtsændring-og-opløsning)
- [Årshjul](#årshjul)
- [Genbrugelige leveranceformater](#genbrugelige-leveranceformater)

## Fælles udførelsesmodel

Udfør en opgave i denne rækkefølge:

1. **Kontrollér version:** Sammenhold kildedatoen i [vedtaegter.md](vedtaegter.md) med den officielle side ved en aktuel eller konsekvensfuld opgave.
2. **Afgræns:** Notér hændelse, afdeling, dato, ønsket handling, berørte medlemmer og kendte beslutninger.
3. **Find hjemmel:** Angiv alle relevante paragraffer og eventuelle supplerende forretningsordener/regler.
4. **Placér roller:** Angiv forbereder, beslutningstager/godkender, praktisk udfører og dokumentationsansvarlig.
5. **Kontrollér forudsætninger:** Frister, quorum, flertal, dagsorden, underskrifter, tidligere beslutninger og datakvalitet.
6. **Producer:** Lav beregning, udkast, checkliste, beslutningsoplæg eller færdigt opgavegrundlag. Brug `[Mangler: ...]` for ikke-kritiske input i stedet for at opfinde dem.
7. **Sæt godkendelsesport:** Stop før en reserveret beslutning eller ekstern skrivehandling og vis præcist, hvad den kompetente person eller det kompetente organ skal godkende.
8. **Gennemfør og dokumentér:** Brug kun en relevant systemintegration med tilstrækkelig autorisation. Gem bevis for beslutning og udførelse i BIFs godkendte system, ikke i skill-repoet.

Behandl opgaven som afsluttet først, når både leverancen, den krævede beslutning og dokumentationen foreligger. Et udkast er afsluttet som `udkast`, ikke som gennemført foreningshandling.

## Besvar et spørgsmål eller placér kompetence

1. Omskriv spørgsmålet til den konkrete opgave eller beslutning.
2. Find direkte hjemmel i paragrafmodellen.
3. Undersøg, om en anden paragraf ændrer kompetencen, fx § 7 om budgetorientering over for § 15 om endelig budgetlægning.
4. Svar med:
   - kort konklusion
   - ansvarligt organ/rolle
   - hvad organet skal gøre
   - hvad andre aktører forbereder eller udfører
   - paragrafhenvisninger
   - manglende supplerende regel
5. Markér et udsagn som fortolkning, hvis det ikke følger direkte.

Eksempel på korrekt kompetenceskel:

- Afdelingen udarbejder handlingsplan og budget-/kontingentforslag (§ 15).
- Bestyrelsen foretager den endelige budgetlægning (§ 15).
- Generalforsamlingen orienteres om budgettet (§ 7); den godkender ikke efter ordlyden budgettet.

## Kontrollér en beslutning

Indhent mødetype, dato, det samlede antal personer i organet, antal til stede, stemmer for/imod og afstemningsform. Brug heltalsberegning og vis tæller/nævner.

### Generalforsamlingens almindelige beslutning

- Kontrollér først lovlig indkaldelse; kun da er mødet beslutningsdygtigt uanset fremmøde (§ 7).
- Forslaget er vedtaget, hvis der er simpelt flertal for.
- Ved stemmelighed bortfalder forslaget.
- Anvend ikke denne regel på vedtægtsændring eller opløsning.

### Bestyrelsens beslutningsdygtighed

- Beregn minimum som `afrund_op(samlet antal bestyrelsesmedlemmer / 2)` (§ 10).
- Brug hele bestyrelsen efter § 9 som nævner, inklusive afdelingsrepræsentanter.
- Kontrollér bestyrelsens forretningsorden for almindeligt flertal, habilitet og stemmelighed; vedtægterne fastlægger kun quorum.

### Oprettelse eller nedlæggelse af afdeling

- Beregn både quorum efter § 10 og ja-tærsklen efter § 15.
- Beregn ja-tærsklen som `afrund_op(2 × samtlige bestyrelsesmedlemmer / 3)`.
- Brug samtlige bestyrelsesmedlemmer som nævner, ikke kun de fremmødte eller afgivne stemmer.
- Eksempel: Ved 12 bestyrelsesmedlemmer kræves 8 ja-stemmer. Syv fremmødte, der alle stemmer ja, opfylder quorum, men ikke 2/3-kravet.

### Vedtægtsændring

- Kontrollér, at beslutningen træffes på en generalforsamling (§ 16).
- Beregn minimum som `afrund_op(2 × afgivne stemmer / 3)`.
- Få dirigenten til at fastlægge og dokumentere, hvilke stemmer der regnes som afgivne; vedtægterne forklarer ikke blanke eller ugyldige stemmer.

### Opløsning

- Kontrollér to på hinanden følgende generalforsamlinger med mindst én måned imellem (§ 17).
- Kontrollér mindst 2/3 af de afgivne stemmer på hvert møde.
- Kontrollér skriftlig afstemning på begge møder.
- Hold beslutninger om nødvendigt ejendomssalg, gældsafvikling og formueanvendelse særskilt; de træffes ved simpelt flertal.

Returnér `opfyldt`, `ikke opfyldt` eller `kan ikke afgøres`. Brug aldrig `opfyldt`, hvis et påkrævet input eller en supplerende beslutningsregel mangler.

## Ordinær generalforsamling

### Indhent

- planlagt mødedato og format
- medlemsdistribution i administrationssystemerne
- bestyrelsens beretning og kommende planer
- revisorpåtegnet driftsregnskab og status
- bestyrelsens endelige budget til orientering
- indkomne forslag
- valgturnus, kandidater, revisor og revisorsuppleant
- gældende regler for praktisk mødeafvikling

### Beregn frister

For mødedatoen `M`:

- seneste indkaldelse: `M - 14 kalenderdage`
- seneste modtagelse af medlemsforslag: `M - 7 kalenderdage`
- seneste udsendelse af dagsorden og forslag: `M - 4 kalenderdage`

Kontrollér, at `M` ligger i januar–marts som den operationelle forståelse af `januar kvartal`. Vis altid de konkrete datoer. Anbefal tidligere udsendelse som praksis, men kald ikke den tidligere dato et vedtægtskrav.

### Udarbejd og kontrollér

1. Lav indkaldelse til alle medlemmer pr. mail gennem administrationssystemerne.
2. Angiv dato, tid, sted/format, forslagsfrist og adgang til materialer.
3. Modtag forslag uden at ændre deres substans; kontrollér kun rettidighed og nødvendige metadata.
4. Lav den obligatoriske dagsorden i samme rækkefølge som § 7.
5. Indsæt valg af to bestyrelsesmedlemmer i ulige år og tre i lige år.
6. Kontrollér, at regnskabet er til godkendelse, mens budgettet er til orientering.
7. Planlæg skriftlig afstemning om eksklusion og skriftligt personvalg, hvis ét medlem kræver det.
8. Klargør referat med stemmetal, beslutninger, valg og opfølgningsansvar.
9. Få bestyrelsen/delegeret ansvarlig til at godkende og udsende materialet.
10. Dokumentér udsendelsestidspunkt og modtagergrundlag uden at lægge medlemslisten i repoet.

### Minimumsdagsorden

1. Valg af dirigent
2. Bestyrelsens beretning og planer for kommende år
3. Regnskab for det afsluttede år til godkendelse
4. Orientering om budget for kommende år
5. Indkomne forslag
6. Valg til bestyrelsen
7. Valg af revisor og revisorsuppleant
8. Eventuelt

## Ekstraordinær generalforsamling

### Ved bestyrelsens initiativ

1. Dokumentér bestyrelsens beslutning og den begrundede dagsorden.
2. Brug samme indkaldelsesmåde som til ordinær generalforsamling (§ 8).
3. Afgræns beslutningerne til den varslede dagsorden.
4. Klargør referat og relevante afstemningsformer.

### Ved medlemskrav

1. Kontrollér, at kravet er skriftligt, har mindst 20 medlemmer og indeholder en begrundet dagsorden.
2. Behandl medlemsoplysninger fortroligt og commit dem ikke.
3. Registrér modtagelsesdatoen `R`.
4. Beregn seneste mødedato som `R + 6 uger`; planlæg mødet hurtigst muligt.
5. Brug samme indkaldelsesmåde som ved ordinær generalforsamling.
6. Markér som fortolkningspunkt, hvordan § 6's fire-dages dagsordensfrist og eventuelle supplerende forslag håndteres, hvis den konkrete forretningsorden ikke afgør det.

## Digital generalforsamling

Aktivér kun processen, hvis et fysisk møde er umuligt på grund af force majeure.

Kontrollér og dokumentér:

- force-majeure-hændelsen og hvorfor fysisk møde ikke kan afholdes
- bestyrelsens beslutning om rent digitalt format
- identitetskontrol og blokering af uvedkommende
- mulighed for deltagelse, taleret og stemmeafgivelse
- mulighed for hemmelig afstemning
- driftssikkerhed, support og håndtering af tekniske afbrydelser
- tydelig oplysning om digitalt format i indkaldelsen
- instruktion om system, tilmelding og mødeprocedure

Et ønske om bekvemmelighed eller lavere omkostninger er ikke i sig selv hjemmel efter § 6. Ved hybridformat skal hjemlen afklares, fordi vedtægterne ikke regulerer det.

## Afdelingens årlige leverancer

Udarbejd de tre leverancer samlet, så aktivitet, ressourcer og budget hænger sammen (§ 15).

### Aktivitetsberetning

Brug denne struktur:

```markdown
# [Afdeling] – aktivitetsberetning [år/sæson]

## Kort overblik
[Vigtigste aktiviteter og udvikling]

## Bredde og elite
[Hvordan afdelingen har understøttet begge områder]

## Aktivitet og deltagelse
[Hold, forløb, arrangementer og dokumenterede nøgletal]

## Ledere og instruktører
[Rekruttering, uddannelse og udvikling]

## Resultater og læring
[Opnået, udfordringer og læring]

## Næste periode
[Forbindelse til handlingsplanen]
```

Brug kun aggregerede medlemsdata i et offentligt dokument. Markér ukendte tal i stedet for at gætte.

### Handlingsplan

| Mål | Aktivitet | Forventet effekt | Ansvarlig | Start | Frist | Ressourcer | Budgetpost | Målepunkt | Status |
|---|---|---|---|---|---|---|---|---|---|

- Knyt hvert mål til foreningens formål og afdelingens ansvar for aktivitet, bredde/elite eller uddannelse.
- Adskil vedtagne indsatser fra forslag, der kræver budgetgodkendelse.
- Brug interne ansvarlige og frister som planlægningsvalg, ikke som vedtægtskrav.

### Budget- og kontingentforslag

1. Knyt alle væsentlige poster til handlingsplanens aktiviteter.
2. Vis historik, forudsætninger, beregning og usikkerhed.
3. Medtag et særskilt, begrundet forslag til afdelingskontingenter.
4. Brug `bredballeif-oekonomi` til den økonomiske analyse og dokumenterede Conventus-data.
5. Mærk dokumentet `afdelingens forslag`.
6. Send det til bestyrelsens endelige budgetlægning; påstå ikke, at afdeling eller afdelingsmøde har godkendt foreningens endelige budget.

## Afdelingens årlige medlemsmøde

Indhent først afdelingens godkendte forretningsorden. Den skal levere varsel, stemmeret, valgbarhed, flertal, forslagsfrist og referatkrav, hvis de findes.

Minimumsdagsorden efter § 15:

1. Valg af dirigent
2. Orientering om afsluttet sæsons aktiviteter og kommende sæsons planer
3. Orientering om afsluttet års økonomi og kontingentforslag for kommende år
4. Forslag fra medlemmerne
5. Valg af afdelingsledelse
6. Eventuelt

Udfør:

1. Beregn lokale frister ud fra forretningsordenen; opfind dem ikke.
2. Saml aktivitetsberetning, planer, økonomi og kontingentforslag.
3. Kontrollér valgbare poster og valgperioder mod forretningsordenen.
4. Lav indkaldelse, dagsorden og referatskabelon.
5. Registrér den valgte afdelingsledelse, dens konstituering og valgte bestyrelsesrepræsentant.
6. Send forretningsordensændringer til bestyrelsesgodkendelse, før de behandles som gældende.

## Afdelingens forretningsorden

Lav kun et `udkast`, medmindre en allerede godkendt tekst skal opdateres. Dæk mindst § 15's emner og de proceshuller, som vedtægterne efterlader:

- navn, formål og forhold til Bredballe IFs vedtægter
- organisation, afdelingsledelse og eventuelle udvalg
- mindst tre ledelsesmedlemmer og konstituering med formand/kasserer
- valg af bestyrelsesrepræsentant
- roller, delegation og habilitet
- valgprocedure, valgbarhed, valgperioder og vakancer
- medlemsmødets indkaldelse, forslagsfrist, stemmeret, quorum, flertal og referat
- møde- og beslutningsregler for ledelse/udvalg
- økonomirapportering, handlingsplan, budget- og kontingentforslag
- aktivitetsudvikling og uddannelse af ledere/instruktører
- ændringsprocedure og bestyrelsens godkendelsesport

Markér alle valgmuligheder, der ikke følger af vedtægterne, som beslutningspunkter. Vedlæg en ændringsoversigt ved revision. Forretningsordenen og enhver ændring bliver først gældende efter bestyrelsens godkendelse (§ 15).

## Opret eller nedlæg en afdeling

1. Udarbejd et beslutningsoplæg med formål, aktiviteter, medlemmer, økonomi, risici, overgang og påvirkede aftaler/data.
2. Ved oprettelse: vedlæg udkast til organisation og forretningsorden samt forslag til mindst tre ledelsespersoner.
3. Ved nedlæggelse: planlæg overførsel/afvikling af aktiviteter, medlemmer, økonomi, udstyr, aftaler, data og ansvar.
4. Fastslå hele bestyrelsens aktuelle medlemstal efter § 9.
5. Kontrollér quorum efter § 10.
6. Kræv ja-stemmer fra mindst to tredjedele af samtlige bestyrelsesmedlemmer (§ 15).
7. Dokumentér fremmøde, stemmetal, beslutning, ikrafttrædelse og ansvarlige.
8. Udfør systemændringer først efter den dokumenterede bestyrelsesbeslutning og med relevante integrationer.

## Udmeldelse, eksklusion og karantæne

### Udmeldelse

1. Modtag skriftlig udmeldelse hos afdelingskassereren.
2. Fastslå ønsket virkningsdato.
3. Kontrollér kontingentbetaling frem til virkningsdatoen.
4. Registrér udmeldelsen i afdelingen med den relevante systemskill og autorisation.
5. Send kvittering uden at love tilbagebetaling eller andre vilkår, som ikke er dokumenteret.

### Eksklusion for restance

1. Kontrollér dokumenteret restance længere end to måneder.
2. Udarbejd mindst otte dages skriftligt varsel med beløb, periode, betalingsmulighed og mulig konsekvens.
3. Dokumentér levering og fristens udløb.
4. Forelæg sagen for bestyrelsen; agenten træffer ikke afgørelsen.
5. Dokumentér begrundet beslutning og betingelsen for genoptagelse: gælden skal betales.
6. Behandl person- og økonomidata fortroligt.

### Anden eksklusion

1. Dokumentér hvilken adfærd eller hvilke særlige forhold der påstås, og forbind dem til § 5.
2. Indhent en menneskelig vurdering og relevante supplerende regler.
3. Brug partshøring, proportionalitet, begrundelse og fortrolig sagsbehandling som anbefalet retssikker praksis; markér, at detaljerne ikke står i vedtægterne.
4. Forelæg sagen for bestyrelsen.
5. Oplys den ekskluderede om muligheden for prøvelse på førstkommende generalforsamling.
6. Planlæg skriftlig afstemning, hvis sagen prøves på generalforsamlingen (§ 7).

### Karantæne

1. Kontrollér, at den foreslåede periode er højst to måneder.
2. Dokumentér hvorfor adfærden kræver sanktion, men ikke vurderes alvorlig nok til eksklusion.
3. Fastslå hvilket afdelingsudvalg der har kompetencen efter afdelingens forretningsorden.
4. Brug høring, proportionalitet, begrundelse og tydelig start/slutdato som anbefalet praksis.
5. Forelæg sagen for menneskelig beslutning i det kompetente udvalg.

Automatisér aldrig selve sanktionsafgørelsen. Automatisér kun kontrol, udkast, påmindelser og godkendt systemregistrering.

## Regnskab, budget og revision

### Årsregnskab

1. Afgræns kalenderåret (§ 12).
2. Saml og afstem forenings- og afdelingsregnskaber gennem godkendte systemer.
3. Lad foreningskassereren færdiggøre driftsregnskab og status.
4. Indhent revisorernes påtegning.
5. Forelæg materialet for generalforsamlingen til godkendelse.
6. Dokumentér godkendelsen i referatet.

### Budget

1. Lad hver afdeling udarbejde handlingsplan, budgetforslag og kontingentforslag (§ 15).
2. Brug `bredballeif-oekonomi` til beregning, scenarier og budgetopfølgning.
3. Saml fælles poster, forudsætninger og åbne beslutninger.
4. Forelæg det samlede budget for bestyrelsens endelige budgetlægning.
5. Sæt budgettet på generalforsamlingens dagsorden som orientering, ikke godkendelse (§ 7).

### Løbende opfølgning

1. Lad afdelingskassereren følge plan og budget.
2. Brug et regelmæssigt rapportinterval fastsat af bestyrelsen/økonomiprocessen; mærk det som intern regel, fordi § 15 ikke angiver intervallet.
3. Eskalér afvigelser efter dokumenterede BIF-regler; opfind ikke beløbsgrænser.

## Tegningsret og fast ejendom

### Almindelig tegningshandling

1. Identificér den bagvedliggende beslutning og dokumentér mandatet.
2. Kontrollér, at formanden og to andre medlemmer af forretningsudvalget underskriver (§ 11).
3. Kontrollér aktuelle roller og eventuelle fuldmagter; antag ikke, at en systemadgang ændrer tegningsretten.

### Køb eller salg af fast ejendom

1. Indhent juridisk og økonomisk rådgivning samt et formelt beslutningsgrundlag.
2. Afklar den interne beslutningsregel i bestyrelsens forretningsorden eller hos rådgiver; § 11 angiver tegningsret, ikke klart afstemningskrav.
3. Kontrollér ordlydens krav om den samlede bestyrelse ved tegningshandlingen.
4. Udfør ingen underskrift, betaling, tinglysning eller bindende meddelelse uden udtrykkelig menneskelig godkendelse.

## Vedtægtsændring og opløsning

### Vedtægtsændring

1. Udarbejd ændringsforslag med gældende tekst, foreslået tekst, begrundelse, konsekvens og ikrafttrædelse.
2. Følg generalforsamlingens indkaldelses- og forslagsproces.
3. Kontrollér mindst to tredjedele af de afgivne stemmer (§ 16).
4. Dokumentér stemmetal og vedtaget ordlyd i referatet.
5. Opdatér først den officielle vedtægtstekst efter dokumenteret vedtagelse og menneskelig godkendelse af den konsoliderede version.
6. Opdatér denne skills snapshot i en særskilt, reviewet kodeændring.

### Opløsning

1. Planlæg to generalforsamlinger med mindst én måned imellem.
2. Udsend tydeligt opløsningsforslag og afviklingsgrundlag efter gældende proces.
3. Gennemfør skriftlig afstemning med mindst 2/3 for på begge møder.
4. Træf særskilte beslutninger ved simpelt flertal om nødvendige ejendomssalg, forpligtelser og formueanvendelse.
5. Sørg for, at restformuen går til idrætslige eller andre almennyttige formål.
6. Brug juridisk/regnskabsmæssig rådgivning og udfør først afviklingshandlinger efter begge gyldige beslutninger.

## Årshjul

Lav årshjulet baglæns fra den valgte ordinære generalforsamlingsdato. Brug disse vedtægtsbundne ankere:

| Periode/frist | Opgave | Ejer | Hjemmel |
|---|---|---|---|
| Kalenderårets afslutning | Afslut regnskabsåret | Foreningskasserer | § 12 |
| Årligt, intern frist | Afdelingsberetning, handlingsplan, budget- og kontingentforslag | Afdelingen | § 15 |
| Årligt, lokal frist | Afdelingens medlemsmøde | Afdelingsledelsen | § 15 + forretningsorden |
| Før generalforsamlingen | Revision/påtegning af driftsregnskab og status | Revisorer | §§ 12, 14 |
| Første kvartal | Ordinær generalforsamling | Bestyrelsen/generalforsamlingen | §§ 6–7 |
| M − 14 dage | Seneste indkaldelse | Bestyrelsen/delegeret udfører | § 6 |
| M − 7 dage | Seneste medlemsforslag | Medlemmer/bestyrelsen modtager | § 6 |
| M − 4 dage | Seneste dagsorden og forslag til alle medlemmer | Bestyrelsen/delegeret udfører | § 6 |
| Efter generalforsamlingen | Konstituering, beslutningsopfølgning og publicering | Kompetent organ/rolle | §§ 7, 9 |
| Regelmæssigt | Afdelingsøkonomi til foreningskassereren | Afdelingskasserer | § 15 |

Tilføj interne datoer for dataudtræk, afdelingsleverancer, bestyrelsesbehandling og kvalitetssikring. Vis dem som `anbefalet/intern`, ikke som vedtægtsfrister.

## Genbrugelige leveranceformater

### Beslutningsoplæg

```markdown
# Beslutningsoplæg: [titel]

## Indstilling
[Præcis beslutning, organet anmodes om at træffe]

## Hjemmel og kompetence
- Vedtægt: [§]
- Besluttende organ: [organ]
- Quorum/flertal/form: [krav eller manglende supplerende regel]

## Baggrund og fakta
[Dokumenterede oplysninger]

## Muligheder og konsekvenser
[Økonomi, medlemmer, aktiviteter, aftaler, data og risici]

## Gennemførelse
- Ansvarlig: [rolle]
- Frist: [dato]
- Godkendelsesport: [beslutning/underskrift]
- Dokumentation: [referat/systemspor]

## Åbne punkter
[Manglende data, fortolkning eller rådgivning]
```

### Kontrolrapport

```markdown
## Resultat
[Opfyldt / ikke opfyldt / kan ikke afgøres]

## Vedtægtskrav
| Krav | Faktisk forhold | Status | Kilde |
|---|---|---|---|

## Fortolkningspunkter
[Hvad vedtægterne ikke afgør]

## Næste handling
[Handling, ansvarlig, frist og godkendelse]
```

### Referatets beslutningspost

```markdown
### [Dagsordenspunkt]
- Beslutningskompetence og hjemmel: [organ, §]
- Beslutningsdygtighed: [samlet antal, til stede, krav]
- Forslagets ordlyd: [præcis tekst]
- Afstemningsform: [åben/skriftlig/hemmelig]
- Stemmetal: [for/imod/blank/ugyldig efter dirigentens opgørelse]
- Beslutning: [vedtaget/forkastet/kan ikke afgøres]
- Ansvarlig for opfølgning: [rolle]
- Frist og dokumentation: [dato/systemspor]
```
