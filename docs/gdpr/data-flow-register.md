# Dataflowregister

Dataansvarlig er angivet som "Bredballe IF (forventet)" og skal bekræftes. Region og databehandler er
kun fakta, hvor repo/opgave giver evidens; ellers står **SKAL VERIFICERES ORGANISATORISK**.

| ID | Kilde | Modtager | Formål | Input/output og personkategorier | System | Region | Databehandler/rolle | Lagring/retention | Adgang, logning og kontroller | Hovedrisici | Status |
|---|---|---|---|---|---|---|---|---|---|---|:---:|
| DF-01 | Bestyrelse/udvalg | Telegram → OpenClaw | Kommando og svar | Telegram-id, navn, besked/svar; alle klasser mulige | Telegram/OpenClaw | Telegram ukendt; VPS DE oplyst | Roller skal fastslås | Telegram/server/session ukendt | To agentroller dokumenteret; user-id allowlist/logredaction ikke verificeret | Uautoriseret adgang, fri tekst, injection, tredjeland | RØD |
| DF-02 | OpenClaw | Ekstern LLM | Toolvalg og formulering | Prompt, historik, minimeret tool-output; PERSONAL mulig, SENSITIVE/SECRET forbudt | OpenClaw/TensorX eller anden provider | EU krævet; faktisk route ukendt | Provider/databehandler skal verificeres | Prompt/outputretention ukendt | Providerpolicy implementeret, ikke gatewayintegreret | Ukendt provider/fallback, eksfiltration, leverandørændring | RØD |
| DF-03 | Conventus | Padel-Conventus → OpenClaw | Konkret medlemsopslag | Input navn/gruppe; lokalt fuldt objekt; output id/navn/kontakt/grupper, maks. 10 | Conventus XML | Conventus ukendt; kald fra DE | Conventus-rolle/DPA ukendt | Ingen tiltænkt fil; session/log ukendt | Querylimit, outputallowlist, metadataaudit | Overfelter, navnesøgning, masseudtræk, LLM-videresendelse | RØD/GUL |
| DF-04 | Conventus | Lokal statistik → LLM | Medlemstal/churn | Lokalt fulde medlemmer; output kun aggregater tiltænkt | Conventus/skill/LLM | DE → godkendt EU-LLM tiltænkt | Conventus + LLM skal verificeres | Ingen skillfil; session ukendt | Lokal aggregering; ingen navneliste tiltænkt | Råobjekt i runtime, scopefejl, fallback | GUL |
| DF-05 | Conventus | Børneattest-tool → autoriseret bruger | Attestkontrol | Frivillige/U15-trænere; navn/id/rolle/fødselsdato/status | Conventus/lokal renderer | DE; ekstern LLM forbudt | Conventus; BIF dataansvarlig forventet | Stdout/session; retention ukendt | Sensitive/bulk approval; kontaktfelter fjernet | SENSITIVE/artikel 10, sessionlæk, forkert rolle, masseudtræk | RØD |
| DF-06 | Gmail | Onboarding → Conventus → HalBooking | Medlemsoprettelse | Mail/navn/id/telefon/e-mail/medlemskab; output status | Google, Conventus, HalBooking | Alle leverandørregioner ukendte; VPS DE | Roller/DPA'er ukendte | Gmail read/label; HalBooking varigt; session ukendt | Maks. 10, scoped writes, redigerede logs | Injection, forkert medlem/modtager, dobbeltwrite, region | RØD |
| DF-07 | HalBooking | Privat lokal eksportfil | Afstemning | Komplet padelmedlemsliste | HalBooking/fil | Leverandør ukendt; fil på DE VPS | HalBooking + BIF | Fri filsti; retention/sletning ukendt | Stdout blokeret; bulk approval | Masseudtræk, ukrypteret fil, forkert sti/adgang | RØD/GUL |
| DF-08 | Bruger/skill | HalBooking → bruger | Banebooking | Dato/tid/bane/bookingtekst; adgangskode SECRET | HalBooking | Ukendt | HalBooking-rolle/DPA ukendt | Booking varig i system; screenshot mulig | Bookingapproval; kode fjernet fra stdout | Fejlwrite, kode/sessionlæk, usikker levering | GUL |
| DF-09 | Conventus | Økonomi-skill → udvalg/LLM | Budget/opfølgning | Afdelingsregnskab, budget, mulig personhenførbar fritekst | Conventus/økonomi/LLM | DE → EU tiltænkt | Conventus/LLM skal verificeres | Stdout/session; ingen egen fil | Read-only; scrub/scope ikke fuldt kodet | Persontekst, for bredt år/afdeling, fallback | GUL |
| DF-10 | Offentlige kilder | Fondsindeks | Fondsresearch | PUBLIC fondsmetadata | Web/EU API/DGI/statsfeed | Varierer | Kilder typisk selvstændige | Privat JSON-store/public seed/runlog | Hostallowlists, validering, ingen medlemspayload | Eksternt indhold/injection, vilkår, stale data | GUL |
| DF-11 | Fundraising Club | Privat fondsstore | Licenseret fondsresearch | Fondsmetadata; login/cookie SECRET | Web/Playwright/store | Ukendt | Kontrakt-/DPA-rolle ukendt | Cookies midlertidige; privat store, retention ukendt | Authorized-use flag; secrets i env | Licens, cookie/loglæk, ekstern tekst/injection | GUL |
| DF-12 | Projektbrief/OneDrive/SharePoint | Fonds-skill → eventuel LLM | Match/ansøgningspakke | CVR, kontakt, budget, historik/noter; INTERNAL/PERSONAL | Lokal store/Microsoft/LLM | DE + leverandører ukendte; LLM EU krævet | Roller/DPA'er ukendte | `data/.../store/history`; ingen frist/kryptering | Noter opt-in; batch maks. 10/hashapproval | Kontaktdata, følsom fritekst, retention, dobbeltfinansiering | RØD/GUL |
| DF-13 | GitHub-repo | Udviklere/Codex/CI | Udvikling/test | Public-egnet kode og syntetiske fixtures; ingen proddata | GitHub/Codex | Skal verificeres for organisationskonti | Leverandørroller skal fastslås | Git-historik/CI-artifacts | Repopolicy; `.env`/data ignored; history scan mangler | Secret/persondata i commit, PR, logs eller prompt | GUL |
| DF-14 | Browserautomation | Lokal screenshot/temp | Diagnostik/compare | Aktuel side eller medlemsliste kan indeholde PERSONAL/SECRET | VPS/dev disk | Lokal DE/dev | BIF/hoster | Rå HTML-persistens fjernet; screenshots default off; opt-in TTL mangler | Gitignore; env-gate; diagnostic approval; compare unlink | Disklæk, backup, forkert permissions, manglende sletning | GUL |

## Dataflowkrav pr. post

- Formål og behandlingsgrundlag indføres i BIFs behandlingsfortegnelse.
- Databehandler/selvstændig dataansvarlig, region, DPA, underdatabehandlere og kapitel V-grundlag
  verificeres i [databehandlerregisteret](processor-register.md).
- Retention fastsættes og implementeres efter [loggingpolitikken](logging-and-retention-policy.md).
- Adgang følger [adgangsmatricen](access-control-matrix.md).
- Egress til ukendt endpoint eller ikke-EU-fallback afvises før payload forlader VPS'en.

## Prompt injection og eksfiltration

Data fra Telegram, Conventus, HalBooking, Gmail, websites, PDF/XLSX og LLM-output er ubetroet.
Parser-/gatewaylaget skal mærke eksternt indhold som data, fjerne aktive instruktioner fra toolbeskrivelser
og aldrig lade indhold ændre systemprompt, provider, endpoint, credentials, rolle, max records eller
approval. Egress-firewall og toolallowlist er den endelige grænse; prompttekst alene er ikke en kontrol.
