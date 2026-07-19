# GDPR-analyse: `skills/bredballeif-boerneattest`

Dato: 06-07-2026  
Status: Foreløbig GDPR-/risikovurdering, ikke juridisk rådgivning  
Scope: Telegram-botten `BIF Administrator`, OpenClaw-agenten `bredballeif-administrator` og skillen `skills/bredballeif-boerneattest`

## Konklusion

Arbejdsgangen kan sandsynligvis etableres på en GDPR-forsvarlig måde, men den bør ikke betragtes som
"grøn" uden ekstra kontroller.

De største forhold er:

1. Børneattest-status er følsom i praksis og kan være omfattet af GDPR artikel 10 om oplysninger
   vedrørende straffedomme/lovovertrædelser, især ved `IKKE godkendt`.
2. Bestyrelsesmedlemmer må ikke indtaste CPR-numre eller andre følsomme oplysninger i Telegram.
3. Telegram-svar med navne og atteststatus er stadig personoplysninger og skal minimeres.
4. OpenClaw kører i Frankfurt, hvilket er EU-behandling, men Claude API kan indebære behandling hos
   Anthropic og mulig tredjelandsoverførsel.
5. Der bør gennemføres en egentlig DPIA/konsekvensanalyse før produktionsbrug med fulde lister over
   ca. 300 frivillige.

Anbefalet beslutning:

- Fortsæt kun med `bredballeif-boerneattest` i OpenClaw, hvis dataflow, databehandleraftaler, adgangsstyring,
  logning, retention og Claude API-forhold er dokumenteret.
- Brug "minimum nødvendigt output" som standard: helst antal, statusgrupper og navne kun på personer
  der kræver handling.
- Send aldrig CPR, rå børneattester, virk.dk-svar eller fulde Conventus-udtræk gennem Telegram eller Claude.

## Beskrevet arbejdsgang

1. Et bestyrelsesmedlem skriver til Telegram-botten `BIF Administrator`.
2. Telegram sender beskeden til OpenClaw.
3. OpenClaw kører agenten `bredballeif-administrator`.
4. Agenten bruger `skills/bredballeif-boerneattest`.
5. Skillen henter data fra Conventus via API.
6. OpenClaw/agenten returnerer status eller handlingsliste til Telegram.

Afgrænsning:

- Bestyrelsesmedlemmet må aldrig indtaste CPR-nummer eller andre sensitive oplysninger om frivillige i
  Telegram.
- Agenten er read-only mod Conventus.
- Den autoritative status gemmes i Conventus.
- OpenClaw kører på VPS i Frankfurt.
- OpenClaw bruger API til Claude.

## Data der behandles

### Data fra Telegram

- Telegram-bruger, chat-id, beskedtekst og metadata.
- Eksempel: "Lav kontrol af børneattester for Padel".

Risiko:

- Hvis brugeren alligevel skriver CPR, helbredsoplysninger, private forklaringer eller andre følsomme
  oplysninger, vil de kunne ende hos Telegram, OpenClaw og Claude.

Kontrol:

- Botten skal instruere brugeren i aldrig at skrive CPR eller følsomme oplysninger.
- Hvis CPR eller følsomme oplysninger modtages, skal agenten stoppe, bede brugeren slette beskeden,
  undlade videre behandling og hændelsen vurderes som mulig persondatasikkerhedshændelse.

### Data fra Conventus

Skillen kan hente:

- Navn
- Conventus-id
- Email
- Mobil
- Fødselsdato
- Afdeling/gruppe/hold
- Rolle som træner/leder/frivillig
- Børneattest-status og dato, fx `Ansøgt`, `Godkendt`, `Afvist`, `IKKE godkendt`, forældet dato

Vurdering:

- Navn, kontaktoplysninger, fødselsdato, roller og gruppetilhørsforhold er personoplysninger.
- Børneattest-status er særligt beskyttelseskrævende. `IKKE godkendt` og `Afvist` kan være meget
  indgribende for den frivillige.
- Der bør ikke sendes email, mobil eller fødselsdato til Telegram, medmindre det er strengt nødvendigt.

### Data til Claude API

Hvis OpenClaw sender brugerprompt, tool-output eller Conventus-resultater til Claude API, kan Anthropic
modtage personoplysninger.

Vurdering:

- Dette er den vigtigste eksterne risikofaktor.
- Hvis Claude kun bruges til at forstå en generel kommando uden persondata, er risikoen lavere.
- Hvis Claude modtager navne, status, email, fødselsdato eller fulde lister, er risikoen væsentligt højere.

Anbefaling:

- Design OpenClaw-flowet så Claude ikke modtager rå Conventus-data, hvis det kan undgås.
- Lad helst `bredballeif-boerneattest`-scriptet danne et færdigt, dataminimeret svar, som sendes direkte tilbage.
- Hvis Claude skal formulere svaret, send kun minimalt tool-output: fx antal og navne på personer der kræver
  handling, ikke email/mobil/fødselsdato/Conventus-id.

## Roller

| Part | Sandsynlig rolle | Kommentar |
|---|---|---|
| Bredballe IF | Dataansvarlig | Bestemmer formål og midler for børneattest-kontrollen |
| Bestyrelsen | Autoriserede brugere/personer under den dataansvarlige | Tavshedspligt og adgang efter need-to-know |
| Conventus | Databehandler eller selvstændig leverandør afhængigt af aftale | Skal være dækket af aftale og sikkerhedsforanstaltninger |
| OpenClaw-operatør/VPS | Databehandler/underdatabehandler hvis ekstern | Kræver databehandleraftale og EU-hosting/audit |
| Anthropic/Claude API | Databehandler eller underdatabehandler afhængigt af aftale | Kræver commercial DPA/SCC og dokumenteret retention/træningsopsætning |
| Telegram | Separat platform/ekstern tredjepart | Telegram er ikke et BIF-system; brugen kræver tydelig dataminimering og brugeradgangskontrol |

## Lovligt grundlag

Foreløbig vurdering:

- Selve indhentningen og kontrollen af børneattester sker for at overholde danske krav om børneattester
  for faste frivillige med kontakt til børn under 15 år.
- Behandling af almindelige personoplysninger kan sandsynligvis støttes på retlig forpligtelse og/eller
  legitim interesse i at beskytte børn og drive foreningen forsvarligt.
- Oplysninger knyttet til børneattester bør vurderes efter GDPR artikel 10, da de relaterer sig til
  strafferetlige forhold eller fravær af relevante strafferetlige forhold. Det kræver hjemmel i EU- eller
  medlemsstatsret og passende garantier.

Praktisk konsekvens:

- BIF bør dokumentere hjemlen i foreningens GDPR-fortegnelse.
- Der bør beskrives særskilte passende garantier: adgangsbegrænsning, logning, kort retention,
  dataminimering, tavshedspligt og klare procedurer for `IKKE godkendt`.

## Vurdering mod BIF-proceduren

PDF-proceduren siger blandt andet:

- Bestyrelsen har ansvar for retningslinjer og politikker for beskyttelse af børn.
- Afdelingerne udpeger ansvarlige for børneattester og bruger erhvervs MitID.
- Børneattester skal indhentes før relevante frivillige starter.
- BIF følger anbefalingen om fornyelse hvert andet år.
- Børneattesten er omfattet af persondataforordningen og skal destrueres efter modtagelse eller gemmes i
  foreningens digitale postkasse.
- CPR-mail slettes permanent.
- Positive/ikke-godkendte attester kræver afbrydelse af samarbejde og information til udvalg/HB.

OpenClaw-flowet er kun foreneligt med proceduren hvis:

- CPR ikke sendes i Telegram.
- Agenten ikke modtager eller lagrer selve børneattesten.
- Agenten kun viser status fra Conventus og ikke rå dokumenter.
- `IKKE godkendt` håndteres ekstremt snævert og ikke som almindelig bot-chat i større grupper.
- Bestyrelsens adgang er dokumenteret og løbende ajourført.

## Risikovurdering

| Risiko | Niveau | Hvorfor | Anbefalet kontrol |
|---|---|---|---|
| CPR indtastes i Telegram | Høj | CPR kan spredes til Telegram, OpenClaw, logs og Claude | Hard rule i bot/skill: afvis CPR, stop behandling, slet/eskaler hændelse |
| Fulde lister over 300 frivillige sendes til Claude | Høj | Stor mængde persondata og atteststatus til ekstern AI-leverandør | Minimer/pseudonymiser tool-output; brug Claude kun til intent eller med DPA/DPIA |
| `IKKE godkendt` vises i Telegram | Høj | Meget indgribende oplysning med høj skadevirkning | Send kun "kontakt daglig leder/HB"; håndter detaljer uden for Telegram |
| Telegram-bot i gruppechat | Høj | Risiko for for mange modtagere, videresendelser og screenshots | Brug private chats eller stramt kontrollerede grupper; gennemgå medlemmer løbende |
| OpenClaw logs gemmer tool-output | Høj | Logs kan indeholde navne/status og blive glemt | Redaction, kort retention, adgangsbegrænset drift, ingen debug-logs i prod |
| Claude API retention/træning ikke afklaret | Høj | Persondata kan behandles uden korrekt aftale/retention | Brug commercial API, DPA/SCC, ingen training opt-in, helst ZDR hvis muligt |
| Conventus API key misbruges | Høj | Uautoriseret adgang til medlemsdata | Secret manager, rotation, least privilege, ingen `.env` i git |
| Forkert status pga. hallucination/fortolkning | Middel/høj | Forkert opfølgning kan skade frivillige | Script-output er facit; menneskelig kontrol før handling |
| Manglende information til frivillige | Middel | Frivillige skal kunne forstå behandling og modtagere | Opdater privatlivsinformation til frivillige |
| Manglende sletning af rapporter | Middel/høj | Persondata i lokale filer kan blive liggende | Rapporter kun i gitignored `data/`; fast slettefrist |

## Anbefalede tekniske ændringer

1. Tilføj eksplicit CPR-værn i `skills/bredballeif-boerneattest/SKILL.md`:
   - Spørg aldrig efter CPR i Telegram.
   - Hvis brugeren indtaster CPR eller sidste 4 cifre, må agenten ikke gentage dem.
   - Agenten skal bede brugeren slette beskeden og bruge fysisk fremmøde, telefon, post eller anden godkendt kanal.

2. Tilføj "Telegram-safe output" i `skills/bredballeif-boerneattest/scripts/agent.py`:
   - Skjul email, mobil, fødselsdato og Conventus-id som standard.
   - Vis navne kun når de kræver handling.
   - Vis `IKKE godkendt` som "kritisk status - kontakt daglig leder/HB" i Telegram-output.

3. Indfør output-profiler:
   - `summary`: antal OK/forældet/mangler, ingen navne.
   - `action-list`: kun navne og handlinger.
   - `internal-full`: kun for lokal autoriseret drift, ikke Telegram/Claude.

4. Undgå at sende rå tool-output til Claude:
   - Lad scriptet generere sluttekst til Telegram.
   - Hvis OpenClaw kræver LLM-formulering, send et allerede minimeret resumé.

5. Logning:
   - Slå debug-logs fra i produktion.
   - Redact prompts/tool-output med navne/status hvor muligt.
   - Definér retention, fx 7-30 dage for tekniske logs uden personindhold.

## Anbefalede organisatoriske kontroller

1. Lav en egentlig DPIA for `BIF Administrator` før fuld produktionsbrug.
2. Opdater BIFs fortegnelse over behandlingsaktiviteter.
3. Dokumentér behandlingsgrundlag, artikel 10-vurdering og passende garantier.
4. Indgå/arkivér databehandleraftaler med relevante leverandører:
   - Conventus
   - VPS/OpenClaw-operatør
   - Anthropic/Claude API eller den platform som reelt leverer Claude
5. Dokumentér Claude API-konfiguration:
   - Commercial API, ikke consumer Claude.
   - DPA accepteret.
   - SCC/tredjelandsoverførsel vurderet.
   - Retention og model-training slået fra/afklaret.
   - Zero Data Retention vurderet eller aktiveret hvis muligt.
6. Fastlæg adgangsprocedure:
   - Kun BIF-bestyrelse har adgang til `BIF Administrator`.
   - Medlemskab gennemgås ved ændringer i bestyrelsen.
   - Ingen deling af bot-adgang.
7. Lav hændelsesprocedure:
   - CPR i Telegram.
   - Forkert modtager.
   - Eksponeret API key.
   - Fejlagtig udsendelse af atteststatus.
8. Opdater privatlivsinformation til frivillige:
   - At BIF behandler børneattest-status i Conventus.
   - At autoriserede bestyrelsesmedlemmer kan få status via en intern bot.
   - Hvilke leverandører/kategorier af leverandører der indgår.
   - Hvor længe status og rapporter opbevares.

## Vurdering af Claude API

Claude API er ikke automatisk udelukket, men det er det punkt der kræver mest dokumentation.

Minimum før brug med persondata:

- Brug kun Anthropic commercial/API-vilkår, ikke privat/consumer Claude.
- Bekræft at DPA og SCC er en del af aftalen.
- Bekræft at prompts og outputs ikke bruges til modeltræning uden udtrykkelig tilladelse.
- Bekræft retention for den konkrete API/model/funktion.
- Vurder om Zero Data Retention kan aktiveres.
- Hvis Claude tilgås via tredjepartsplatform, brug tredjepartens aftaler og databehandlerkæde, ikke kun
  Anthropics dokumentation.

Hvis dette ikke kan dokumenteres, bør OpenClaw-flowet designes så Claude ikke modtager persondata fra
Conventus.

## Vurdering af Telegram

Telegram er praktisk til bestyrelsesdialog, men er ikke et klassisk BIF-fagsystem.

Minimum:

- Brug kun botten til autoriserede brugere.
- Undgå CPR og rå dokumenter helt.
- Undgå fulde lister hvis et resumé eller en handlingsliste er nok.
- Undgå større gruppechats til følsomme svar.
- Skriv i botten at følsomme oplysninger ikke må indtastes.
- Lav kort retention på OpenClaw-siden; vær opmærksom på at Telegram-brugere stadig kan have chat-historik.

## Praktisk anbefalet standardflow

Godt flow:

1. Bestyrelsesmedlem skriver: "Lav børneattestkontrol for Padel".
2. Claude/OpenClaw fortolker kun kommandoen.
3. `bredballeif-boerneattest` henter data i Conventus.
4. Scriptet beregner status lokalt.
5. Scriptet returnerer et minimeret svar:
   - "5 relevante frivillige; 3 OK; 2 kræver fornyelse: [navne]. Ingen mangler i fællesgruppen."
6. Detaljer som email, mobil, fødselsdato, Conventus-id og rå API-data holdes ude af Telegram.

Dårligt flow:

1. Bestyrelsesmedlem skriver CPR eller personfølsomme forklaringer i Telegram.
2. OpenClaw sender fuld besked og fuldt Conventus-output til Claude.
3. Claude formulerer en rapport med navn, email, fødselsdato, ID og `IKKE godkendt`.
4. Rapporten sendes i Telegram-gruppe og gemmes i logs.

Det dårlige flow bør blokeres teknisk og organisatorisk.

## Actionliste før produktionsbrug

| Prioritet | Handling | Status |
|---|---|---|
| 1 | Opdatér `bredballeif-boerneattest` skill med eksplicit CPR-forbud i Telegram | Åben |
| 1 | Lav Telegram-safe output uden email/mobil/fødselsdato/Conventus-id | Åben |
| 1 | Beslut om Claude må modtage navne/status; hvis ja, dokumentér DPA/SCC/retention/DPIA | Åben |
| 1 | Gennemfør DPIA/konsekvensanalyse | Åben |
| 1 | Dokumentér databehandleraftaler med Conventus, VPS/OpenClaw og Claude-leverandør | Åben |
| 2 | Definér log-retention og redaction i OpenClaw | Åben |
| 2 | Opdatér privatlivsinformation til frivillige | Åben |
| 2 | Lav adgangsreview for bestyrelsens Telegram-bot | Åben |
| 3 | Lav årlig revision af børneattest-flow, adgang og logs | Åben |

## Kilder

- Lokal guideline: `docs/guidelines/Procedure for indhentning af børneattester 03.12.25.pdf`
- Lokal OpenClaw-beskrivelse: `docs/openclaw-setup.md`
- Lokal skill: `skills/bredballeif-boerneattest/SKILL.md`
- GDPR artikel 10, 28, 32 og 35: https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng
- Datatilsynet om behandlingssikkerhed og risiko: https://www.datatilsynet.dk/regler-og-vejledning/grundlaeggende-begreber/hvordan-beskytter-du-personoplysninger
- Datatilsynet om privacy by design: https://www.datatilsynet.dk/regler-og-vejledning/behandlingssikkerhed/databeskyttelse-gennem-design-og-standardindstillinger
- Datatilsynet om konsekvensanalyse: https://www.datatilsynet.dk/regler-og-vejledning/behandlingssikkerhed/konsekvensanalyse
- Datatilsynet om tredjelandsoverførsler: https://www.datatilsynet.dk/Media/638478180234447566/Vejledning%20om%20overf%C3%B8rsel%20til%20tredjelande.pdf
- Anthropic Claude API data retention: https://platform.claude.com/docs/en/manage-claude/api-and-data-retention
- Anthropic DPA/SCC for commercial products: https://privacy.claude.com/en/articles/7996862-how-do-i-view-and-sign-your-data-processing-addendum-dpa
- Telegram Privacy Policy: https://telegram.org/privacy
- Telegram standard bot privacy policy: https://telegram.org/privacy-tpa
