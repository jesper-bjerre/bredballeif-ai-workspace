# Ledelsesopsummering

## Hvad løsningen gør

Bredballe IF har et workspace med ni AI-skills. De kan hjælpe med vedtægter, økonomi,
fondsansøgninger og kontingentberegning samt administrere padelbaner, Conventus-medlemmer,
HalBooking-onboarding, Gmail-notifikationer og børneattester. OpenClaw kører efter det oplyste på en
Hostinger VPS i Tyskland, og bestyrelse/Padel-udvalg bruger Telegram-bots som brugerflade.

## Hvilke data behandles

De mindst risikofyldte skills bruger offentlige vedtægter, fondsoplysninger og generelle økonomi- eller
produktregler. Medlemsskills kan bruge navn, medlemsnummer, e-mail, telefon, adresse, fødselsdato,
medlemsgruppe, betalings-/medlemsstatus og korrespondance. Børneattest-skillen kan forbinde personer
med atteststatus og må derfor behandles som SENSITIVE. Credentials, OAuth-tokens, sessionscookies og
booking-/medlemsadgangskoder er SECRET.

## Hvor data flyder

Telegram sender brugerens besked til OpenClaw. Agenten vælger et snævert skill-tool. Conventus,
HalBooking eller Gmail kaldes fra VPS'en, og resultatet går tilbage til agenten og Telegram. Den ønskede
model er, at kun et lokalt minimeret resultat må sendes til TensorX i EU. TensorX må aldrig få
Conventus-login, API-nøgle eller direkte endpointadgang. Dette design er dokumenteret, men den faktiske
OpenClaw-providerkonfiguration findes ikke i repoet og kan derfor ikke bevises.

## Hvorfor TensorX og hvordan Codex bruges

TensorX er den foreslåede produktionsprovider for nødvendige almindelige personoplysninger, fordi
behandlingen skal være EU-hostet. Før brug skal konto, DPA, faktisk inferencelokation, zero retention,
træningsfravalg og underdatabehandlere dokumenteres. Navnet eller et EU-endpoint er ikke i sig selv
tilstrækkelig evidens.

Codex bruges til kode, dokumentation og syntetiske fixtures. Codex må ikke have produktionscredentials,
medlemsdata, produktionslogs eller screenshots. Denne revision læste ikke lokal `.env`, `data/` eller
screenshots og kaldte ingen produktion.

## Implementerede sikkerhedsforanstaltninger

- central klassifikation og fail-closed providerkontrol
- afvisning af ukendte og ikke-EU providers for PERSONAL
- blokering af SENSITIVE og SECRET før eksterne modelkald
- standardgrænse på 10 poster og afvisning af brede søgninger
- struktureret redaction af e-mail, telefon, CPR-lignende værdier og secrets
- tidsbegrænset, handlingsafgrænset approval-kontekst for writes
- audit-events uden medlemsindhold
- blokering af HalBooking-masseeksport til stdout
- højst 10 Gmail-beskeder pr. processeringskørsel
- adgangskoder og rå subprocess-output fjernet fra driftsoutput
- 30 syntetiske GDPR- og repositorykontroltests for policy, providerregion, logging, queries,
  approvals, limit-bypass, wrapperadskillelse, screenshot/HTML og manifestdækning; samlet 97 lokale
  tests består

## Vigtigste åbne risici

1. OpenClaw-routing, LLM-model, region, fallback og sessionretention er ukendt.
2. Gatewayen er endnu ikke dokumenteret til at kalde den nye policy før hvert modelkald.
3. Conventus API leverer hele medlemsobjekter til lokal kode; gatewayens minimering er ikke implementeret.
4. Rå HTML-persistens er fjernet, og browser-screenshots er default off. Ved godkendt diagnostisk
   opt-in mangler stadig slettejob og krypteret privat placering.
5. Telegram-brugerallowlist, gruppepolitik, MFA og offboarding kan ikke verificeres.
6. DPA'er, underdatabehandlere, EU-lokation, retention og backup/sletning mangler for leverandørkæden.
7. Børneattest må ikke sendes til ekstern LLM; teknisk isolation skal bevises end-to-end.

## Anbefalet beslutning

Godkend **ikke** den samlede løsning til medlemsdata endnu. Bestyrelsen kan overveje en isoleret fase 0
med PUBLIC-skills og lokale beregninger, hvis de ikke har adgang til medlems-tools eller credentials.
Før PERSONAL åbnes, skal P0-punkterne i [åbne punkter](open-issues.md) lukkes og accepttesten udføres af
en autoriseret person uden at resultater sendes til Codex. SENSITIVE børneattestbehandling forbliver
lukket for ekstern LLM og kræver særskilt beslutning/DPIA-vurdering.

Endelig godkendelse foretages af den dataansvarlige og eventuel rådgiver; denne dokumentation er alene
et teknisk beslutningsgrundlag.
