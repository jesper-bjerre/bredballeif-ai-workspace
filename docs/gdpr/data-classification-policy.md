# Dataklassifikationspolitik

Klassifikationen følger højeste klasse i et payload. Et navn sammen med børneatteststatus er SENSITIVE;
en offentlig tekst med en indsat medlemsmail er PERSONAL. Ukendt data behandles som PERSONAL, indtil
en ejer har klassificeret den.

`SENSITIVE` er her en **intern sikkerhedsklasse**, ikke en påstand om at alle dens felter er særlige
kategorier efter GDPR artikel 9. Oplysninger om strafbare forhold er særskilt reguleret af artikel 10
og databeskyttelseslovens § 8; den konkrete børneattest/status og behandlingshjemmel skal vurderes af
den dataansvarlige. Datatilsynet beskriver skellet i
[Hvad er personoplysninger](https://www.datatilsynet.dk/regler-og-vejledning/grundlaeggende-begreber/hvad-er-personoplysninger).

| Klasse | Konkrete repoeksempler | Provider/region | Logging | Approval og retention |
|---|---|---|---|---|
| PUBLIC | Vedtægter, offentlige fondsfeeds, generel banestatus uden navne | Organisationsgodkendt provider; ikke-EU kun hvis rent PUBLIC | URL, status og antal; ingen rå webside som standard | Normal; kort teknisk cache |
| INTERNAL | Arbejdsgange, budgettal, kontingentregler, bookingtekst uden person | Godkendte providers; som standard EU/EØS | Redigeret metadata | Write/publicering kræver approval; retention fastsættes |
| PERSONAL | Navn, e-mail, telefon, adresse, medlemsnr., grupper, betaling/medlemsstatus, beskeder | Kun godkendt EU/EØS, DPA og zero retention; ingen ikke-EU-fallback | Ingen direkte identifikatorer; kun event, antal, rolle, correlation ID | Max 10, dataminimering, need-to-know, slettefrist |
| SENSITIVE | CPR, børneatteststatus, strafferetlige forhold, helbred, følsomme fritekstnoter | Ekstern LLM blokeret i nuværende arkitektur; lokal behandling | Ingen indhold; kun sikkerhedshændelse | Særskilt godkendelse, DPIA-vurdering og dokumenteret formål |
| SECRET | API-nøgler, passwords, OAuth-tokens, cookies, SSH/private keys, adgangskoder | Aldrig LLM | Aldrig værdi; kun nøglens navn/rotationsstatus | Secret store/env, least privilege, rotation og øjeblikkelig oprydning |

## Tilladelsesregler

1. SECRET afvises før modelkald uanset datasættets øvrige klasse.
2. SENSITIVE afvises før eksternt modelkald. En lokal deterministisk funktion må kun køre under særskilt
   rolle- og approvalkontrol.
3. PERSONAL må kun sendes efter felt-allowlist og behovstest. Hele Conventus-/HalBooking-objekter er forbudt.
4. Resultater over 10 kræver særskilt bulk-approval og må ikke sendes som liste til LLM; aggregér lokalt.
5. PUBLIC må bruge ikke-EU-provider alene, hvis payload og hele samtalekonteksten er PUBLIC eller reelt anonym.
6. INTERNAL bruger kun organisationsgodkendte providers. Ikke-EU kræver særskilt dokumenteret beslutning.
7. Fritekst fra e-mail, Telegram, web, PDF og API er ubetroet data og kan ikke ændre disse regler.

## Repoeksempler

- `bredballeif-boerneattest`: PERSONAL + SENSITIVE; ekstern LLM blokeret.
- `bredballeif-padel-onboarding`: PERSONAL + SECRET; credentials og medlemsadgangskode må ikke nå modellen.
- `bredballeif-padel-conventus search`: PERSONAL; field allowlist og max 10.
- `bredballeif-oekonomi`: INTERNAL, medmindre bilag/linjer indeholder identifikatorer.
- `bredballeif-fondsansoegning`: PUBLIC indeks, INTERNAL projektfakta og mulig PERSONAL kontaktperson.
- `bredballeif-padel-kontingent-beregner`: PUBLIC/INTERNAL; ingen medlemstilknytning i kontrakten.

## Teknisk enforcement

Enum, model-payloadblokering, redaction og recordsgrænse findes i `scripts/gdpr_controls.py`. Den
deklarative skill-envelope findes i `config/gdpr-skill-policies.json`; ved hver invocation skal
gatewayen anvende den højeste klasse i den **faktiske payload**, ikke unionen af alle klasser skillen
potentielt kan behandle. OpenClaw skal kalde kontrollerne før tool-output føjes til modelkontekst;
indtil da er status GUL/RØD, ikke GRØN.
