# Fondsindeks og datakilder

## Indhold

1. Filbaseret lager
2. Dækningsdefinition
3. Kildehierarki
4. Datastatus og provenance
5. Kildeadaptere
6. Deduplikering
7. Privat historik og OneDrive
8. Kvalitetskontrol

## 1. Filbaseret lager

Skillen distribuerer `assets/funds-seed.jsonl` som et saniteret startindeks. Når runtime-lageret er
tomt, importerer alle CLI-handlinger automatisk seedet, før handlingen fortsætter. Seedet er ikke
runtime-lageret og indeholder ingen observationer, historik, ansøgninger, licenserede beskrivelser,
krav, noter eller andre fritekstfelter.

Brug runtime-mappen `store/` uden en databaseafhængighed:

```text
store/
  funds/000001.json
  observations/000001.jsonl
  history/000001.json
  index.jsonl
  meta.json
```

- Behandl `funds/*.json` som den kanoniske fondsbeskrivelse og behold stabile numeriske `fund_id`.
- Behandl `observations/*.jsonl` som deduplikeret provenance for den tilsvarende fond.
- Behandl `history/*.json` som privat historik, aldrig som public-egnet skillindhold.
- Behandl `index.jsonl` som et afledt, kompakt søgeindeks. Kør `genopbyg-indeks`, hvis det slettes,
  eller efter en bevidst manuel ændring i en fondsfil.
- Kør kun én skrivende import/synkronisering ad gangen. Atomiske filudskiftninger beskytter den
  enkelte fil, men lageret er ikke en flerbruger-transaktionsdatabase.
- Regenerér seedet på udviklingsmaskinen med `python -m seed_catalog --store <store> --output
  assets/funds-seed.jsonl`. Generatoren medtager kun fonde med mindst én kildeobservation, der ikke
  er privat eller licenseret. Gennemgå diff og kør test før commit.
- Hold Fundraising Club-poster, fondsbeskrivelser og strukturerede katalogafsnit i det private
  runtime-lager. Betalt adgang er ikke i sig selv en tilladelse til at redistribuere databasen.
- Generér ved behov en komplet privat deployment-fil med `python -m seed_catalog --private --store
  <store> --output <privat-sti>/funds-private-seed.jsonl`. Kopiér den gennem den private
  deployment-kanal, og sæt `BREDBALLEIF_FONDS_PRIVATE_SEED` i OpenClaw. Et tomt lager foretrækker
  den eksplicit valgte private fil frem for det committede offentlige seed.

## 2. Dækningsdefinition

Behandl ikke “alle danske fonde” som en endelig, stabil mængde. Private fonde, kommunale puljer og
midlertidige programmer kan åbne, lukke eller ændre formål uden en samlet registreringspligt.
Kald kun indekset dækkende med en samtidig dækningsrapport, som viser:

- alle registrerede kilder og deres type
- tidspunkt og resultat for seneste synkronisering
- antal nye, ændrede, lukkede og fejlede poster
- poster uden officiel URL
- poster, hvis krav aldrig er verificeret eller er blevet for gamle
- kilder, der kræver manuel eksport, login eller særskilt tilladelse

Brug `daekning` til status. Skriv “dokumenteret dækning pr. dato”, ikke “komplet for altid”.

## 3. Kildehierarki

Brug kilder i denne rækkefølge:

1. Fondens eller myndighedens egen aktuelle programside, retningslinjer, FAQ, ansøgningsskema og portal.
2. Officielle feeds og sektor-/kommuneoversigter, fx Statens Tilskudspuljer, Vejle Kommune, DIF og DGI.
3. Discovery-databaser som DGI-listen, Fundraising Club og Legatbogen.
4. Søgemaskiner, artikler og ældre lister som spor til en officiel kilde.

Lad aldrig niveau 2–4 fastlægge et aktuelt ansøgningskrav, hvis niveau 1 findes. Gem URL og kontroldato
for hvert væsentligt krav. Markér en uafklaret konflikt og stop den konkrete ansøgning.

## 4. Datastatus og provenance

Brug maskinstatusserne:

- `verified`: kontrolleret på officiel programside; stadig kun gyldig pr. kontroldato.
- `discovered_official`: fundet i et officielt feed eller på en officiel side, men kravmatrix mangler.
- `directory_only`: fundet i en sekundær/licenseret database; verificér på officiel side.
- `unverified`: importeret fra en liste uden aktuel kontrol.
- `candidate`: automatisk linkfund; gennemgå manuelt.
- `temporary`: midlertidig mulighed.
- `closed`: officielt lukket eller udløbet.
- `unknown`: status kan ikke afgøres.

Bevar en observation pr. kildepost, også når flere poster deduplikeres til samme fond/program. Gem mindst
kildenavn, kildepost-ID, source URL, officiel URL, første/seneste observation og rå normaliserede felter.
Gem ikke komplette licenserede websider.

## 5. Kildeadaptere

Kilderegisteret ligger i [source-registry.json](source-registry.json). Opdatér `reviewed_at`, når registerets
URLs og roller er kontrolleret.

### Statens Tilskudspuljer

Brug det officielle CSV-feed gennem `synkroniser-statens-puljer`. Standardfilteret er bredt rettet mod
idræt, forening, frivillighed, børn/unge, fællesskab, faciliteter, friluftsliv, socialt, kultur og klima.
Bevar aktive poster uden næste frist; de kan være løbende eller ufuldstændigt registreret. Brug
`--include-all-active` ved en dækningsrevision og klassificér derefter relevans.

### DGI-listen og den eksisterende arbejdsbog

Brug `importer-regneark` på det aktuelle DGI-Excel-download eller på arbejdsbogen
`fonds_og_puljestyring_idraetsforening.xlsx`. Importér:

- `02_Aktuelle` som verificerede seed-poster med kontroldato og officiel URL
- `03_Fondsindeks` som discovery-poster med geografi og oprindeligt indeks-ID
- `09_Log` som indsendelseshistorik, hvis rækkerne faktisk er udfyldt

Ignorér tomme standardskabelonrækker og genberegn scorer/formler i Python.

### EU Funding & Tenders

Brug `synkroniser-eu` til det officielle Funding & Tenders Search API. Adapteren henter kun åbne og
kommende engelsksprogede grants/calls, kører sekventielt og gemmer kort normaliseret metadata. Som
standard bruges brede relevanssignaler for en idrætsforening; brug `--include-all-open` ved audit af
filteret. API-kataloget dækker portalens muligheder, ikke alle decentrale EU- eller medlemsstatsmidler.

En API-post får status `discovered_official`, aldrig automatisk `verified`. Før ansøgning skal agenten
åbne den konkrete officielle topicside samt call-/programdokumenter og kontrollere mindst:

- om en dansk lokal idrætsforening kan være ansøger eller partner
- program, action type, partnerskab og geografi
- frist, projektperiode, støtteprocent, minimum/maksimum og medfinansiering
- registrering, portalroller, formularfelter, bedømmelseskriterier og bilag

Brug ikke en gammel portal-API eller HTML-scraping som erstatning for Search API-adapteren.

### Fundraising Club

Brug kun `synkroniser-fundraisingclub`, når Bredballe IF har gyldig adgang, og automatiseret privat
indeksering er tilladt efter leverandørens vilkår eller skriftlige accept. Et abonnement er ikke i sig selv
bevis for ret til masseudtræk.

- Læs brugernavn og adgangskode fra miljøvariabler; send dem aldrig som CLI-argumenter.
- Hent frisk login-nonce og brug kun en midlertidig cookie-session.
- Kør sekventielt med mindst ét sekund mellem requests og en fast sidegrænse.
- Enumerér FacetWP-katalogets sider med `?_paged=N`; stol ikke på almindelige pagination-links,
  da de ikke findes i den serverrenderede fondsoversigt.
- Sammenhold katalogets `total_rows` med antal unikke `/fonde/<slug>/`-links. En afvigelse gør
  kørslen `incomplete` og må ikke præsenteres som fuld dækning.
- Stop ved MFA, CAPTCHA, botkontrol, ændret login eller uklar tilladelse; omgå intet.
- Gem kun normaliseret metadata lokalt under `data/`; commit aldrig udtrækket.
- Brug Fundraising Club som discovery. Verificér hvert krav på fondens egen side.

Bed helst leverandøren om eksport/API eller skriftlig tilladelse før første fulde synkronisering.

### Offentlige og officielle websider

Brug `synkroniser-kilder` til lette, sekventielle monitors. Respektér `robots.txt`, sidegrænser og fejl.
En automatisk fundet side får ikke status `verified`; den bliver først ansøgningsklar efter kravresearch.
Redirects genvalideres, og private/lokale IP-adresser, URL-credentials og ikke-HTTPS kilder afvises.
Et alternativt `--registry` er deaktiveret i normal drift og kræver eksplicit udviklermiljø-flag.
Et robots-fravalg, en hentefejl eller relevante, ikke-besøgte links ved `crawl_depth`/`max_pages` gør
kørslen `incomplete`; behold posterne som discovery, men kald ikke kilden aktuelt dækket.

## 6. Deduplikering

Brug normaliseret navn plus officielt domæne som startnøgle. Bevar særskilte programmer under samme
fond, når formål, frist eller ansøgningsskema er forskelligt. Understøt aliaser og redirects, fx et tidligere
fondsnavn, uden at slette kildehistorikken. Sammenlæg ikke alene på domæne.

Ved feltkonflikt:

1. Vælg den nyeste officielle observation.
2. Bevar den tabende værdi og kilde i observationerne.
3. Markér felter, der kræver manuel afklaring.
4. Lad en gammel eller sekundær post aldrig overskrive nyere officiel evidens.

## 7. Privat historik og OneDrive

Behandl listen over allerede indsendte ansøgninger som et separat, privat historikregister. Brug den til
dubletkontrol og læring, ikke som discovery-kilde.

- Brug SharePoint/OneDrive-connectoren til at læse den aktuelle fil, hvis connectoren er installeret og
  autoriseret.
- Ellers eksportér filen som `.xlsx` eller `.csv` til en gitignored placering og kør `importer-historik`.
- Brug kun `--url` til et direkte offentligt XLSX-download på den tilladte host. Et almindeligt
  `1drv.ms`-link, der ender på en HTML-visning eller ekstern Office-host, afvises bevidst.
- Hardcod ikke delingslink, tokens, ansvarlige personer, kvitteringer eller beslutningsbreve i skillen.
- Importér ikke tomme skabelonrækker.
- Udelad fritekstnoter som standard. `--include-notes` er et bevidst privat opt-in efter gennemgang
  for persondata; kommandoen `historik` kan vise de importerede noter igen.
- Match tidligere indsendelser på normaliseret fond/program og projekt; markér genansøgning eksplicit.
  Historik uden projekt-id må ikke give et automatisk dubletstop, men skal udløse manuel kontrol.

## 8. Kvalitetskontrol

Kontrollér løbende:

- ugyldige, omdirigerede eller sekundære URLs
- dubletter og aliaser
- udløbne frister og lukkede programmer
- geografiske hard blockers
- manglende CVR/NemKonto/foreningsstatus, når det kræves
- projektstart før tilladt tilsagnsdato
- samme projekt allerede indsendt
- licenserede data uden dokumenteret brugsgrundlag
- CSV/XLSX-formelinjektion ved eksport; præfiksér celler, der starter med `=`, `+`, `-` eller `@`
