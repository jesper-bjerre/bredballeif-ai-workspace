# Budget og budgetopfølgning i Bredballe IF

## Status for BIF-specifikke regler

Repoet dokumenterer endnu ikke Bredballe IF's formelle budgetkalender, godkendelsesflow, beløbsgrænser, kontoplan, momsbehandling eller fordelingsnøgler for fællesomkostninger. Indhent og verificér disse oplysninger hos den økonomiansvarlige eller i godkendte BIF-dokumenter, før de bruges som krav.

Registrér som minimum:

- hvem der udarbejder, godkender og følger op på afdelingens budget
- frister og budgetversioner
- krav til årets resultat, likviditet og eventuelle reserver
- regler for investeringer, periodisering, moms og fællesomkostninger
- grænser for afvigelser, der skal eskaleres
- hvilket Conventus-år og hvilke konti der er den officielle rapporteringskilde

Hold verificerede regler adskilt fra arbejdshypoteser. Angiv ejer og dato for hver regel, når oplysningerne bliver tilgængelige.

## Budgetmodel

Brug den eksisterende Conventus-kontostruktur, så budget og opfølgning kan sammenholdes direkte. Opstil for hver linje:

| Felt | Indhold |
|---|---|
| Konto/post | Betegnelse fra Conventus |
| Historik | Realiseret for som udgangspunkt tre seneste år |
| Basis | Normaliseret udgangspunkt uden dokumenterede engangsposter |
| Driver | Fx antal medlemmer, pris, antal aktiviteter eller kontrakt |
| Ændring | Vedtaget pris-, volumen- eller aktivitetsændring |
| Budget | Basis plus dokumenterede ændringer |
| Forudsætning/kilde | Kort forklaring og kilde |
| Usikkerhed | Lav, mellem eller høj med begrundelse |

Undgå at bruge et simpelt historisk gennemsnit, hvis sæson, kapacitet, kontingentstruktur eller aktiviteter har ændret sig. Lav scenarier ved væsentlig usikkerhed: basis, forsigtig og ambitiøs.

## Beregninger

Anvend konsekvent:

- `afvigelse = realiseret - periodebudget`
- `afvigelse_pct = afvigelse / abs(periodebudget) * 100`
- `forventet_helår = realiseret_til_dato + forventet_resten_af_året`
- `prognoseafvigelse = forventet_helår - helårsbudget`

Fortolkningsretningen afhænger af posttypen:

- Indtægt: positiv afvigelse er normalt gunstig.
- Omkostning: positiv afvigelse er normalt ugunstig, hvis omkostninger vises som positive tal.
- Resultat: positiv afvigelse er normalt gunstig.

Kontrollér Conventus' fortegnskonvention i rapporten og deklarér den i leverancen. Beregn ikke en procentafvigelse, hvis budgettet er nul; vis i stedet beløbet og forklar, at procenten ikke er meningsfuld.

## Væsentlighed og årsagsanalyse

Brug kun en fast væsentlighedsgrænse, hvis BIF har godkendt den. Indtil da skal du rangere afvigelser efter beløb og konsekvens og tydeligt kalde udvælgelsen analytisk, ikke en officiel BIF-regel.

Klassificér årsagen:

- **Timing:** posten forventes senere i året.
- **Permanent:** afvigelsen forventes ikke indhentet.
- **Volumen:** flere/færre medlemmer, hold eller aktiviteter.
- **Pris:** ændret kontingent, sats eller leverandørpris.
- **Engangspost:** ikke en del af normal drift.
- **Datakvalitet:** forkert afdeling, periode, kontering eller manglende postering.

Adskil årsag fra handling. Eksempel: Årsag = lavere medlemstal; handling = opdatér helårsprognosen og beslut rekrutteringstiltag.

## Opfølgningsformat

Brug denne kompakte tabel til ledelsesopfølgning:

| Post | Budget til dato | Realiseret | Afvigelse | G/U | Helårsprognose | Forklaring | Handling |
|---|---:|---:|---:|:---:|---:|---|---|

Supplér med:

1. samlet forventet årsresultat og forskel til helårsbudget
2. tre til fem væsentligste afvigelser
3. risici og muligheder, som endnu ikke er indregnet
4. åbne beslutninger med ansvarlig og frist, hvis kendt
5. datamangler og nødvendige afstemninger

## Kontroller før aflevering

- Matcher afdeling og år brugerens bestilling?
- Er de valgte år de seneste relevante regnskabsår?
- Stemmer summer med Conventus-resultatopgørelsen?
- Er periodebudget sammenlignet med samme periode, ikke ukritisk med helårsbudget?
- Er engangsposter og omklassifikationer dokumenteret?
- Er fortegn, DKK-enhed og afrunding forklaret?
- Er prognoseforudsætninger synlige og sæsonudsving håndteret?
- Er ubekræftede BIF-regler tydeligt markeret?
