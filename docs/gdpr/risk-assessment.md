# Konkret risikovurdering

Skala: sandsynlighed (S) 1–5 og konsekvens (K) 1–5. Score = S×K: 1–4 lav, 5–9 middel,
10–15 høj, 16–25 kritisk. "Resterende" er vurderet efter de repoændringer, men før ukendt deployment
er verificeret. Ejer skal navngives af bestyrelsen.

| ID | Risiko | S | K | Score | Eksisterende/implementeret kontrol | Anbefalet kontrol | Resterende | Ejer/status |
|---|---|---:|---:|---:|---|---|---:|---|
| R-01 | PERSONAL sendes uden for EU | 4 | 5 | 20 | Provider-validator findes | Integrér i OpenClaw, endpoint-egress allowlist, DPA/regionbevis | 20 | Data-/teknisk ejer; ÅBEN P0 |
| R-02 | Automatisk ikke-EU-fallback/ukendt routing | 4 | 5 | 20 | Validator afviser hele route/fallback | Redigeret configdump + failovertest i prod-lignende miljø | 20 | Teknisk ejer; ÅBEN P0 |
| R-03 | For mange medlemsfelter til LLM | 4 | 4 | 16 | Search-output allowlist; model-minimizer | Gatewaytool returnerer kun formålsfelter; lokal templating | 12 | Teknisk ejer; DELVIS P0 |
| R-04 | Masseudtræk/komplet medlemsliste | 4 | 5 | 20 | Max 10, bulk approval, export stdout blokeret | Opdel credentials/tools, lokal aggregation, krypteret outputroot | 12 | Systemejer; DELVIS P0/P1 |
| R-05 | Børneattest/følsomme noter når ekstern LLM | 4 | 5 | 20 | Sensitive payload block + sensitive-read gate | End-to-end local-only route, DPIA-vurdering, ingen sessionpersistens | 20 | Dataansvarlig; ÅBEN P0 |
| R-06 | Credentials i repo/historik | 2 | 5 | 10 | `.env` gitignored; placeholders; ingen hardcoded string fundet | Gitleaks current+history CI, rotation hvis fund | 6 | Repoejer; ÅBEN P1 |
| R-07 | Persondata/secrets i logs | 4 | 5 | 20 | Redaction; password/raw subprocess fjernet | Central logger, screenshots off, logscan og retention | 12 | Teknisk ejer; DELVIS P0 |
| R-08 | Prompt injection fra mail/API/web/PDF | 4 | 4 | 16 | SKILL.md siger data, ikke instruktioner | Gateway isolation, schema parsing, egress/tool allowlist, adversarial tests | 12 | AI-systemejer; ÅBEN P1 |
| R-09 | Forkert e-mailmodtager/statusmail | 3 | 4 | 12 | Fast `ADMIN_EMAIL_TO`; HalBooking-profil | Modtagerallowlist, preview/approval, no sensitive detail, bounce/incident flow | 8 | Procesejer; ÅBEN P1 |
| R-10 | Fejlagtig write/duplikat | 4 | 4 | 16 | Search fail-closed; approvalcontext; fonds hashapproval | Eksakt member-id, idempotency, dry-run, consequence preview, rollback | 12 | Systemejer; DELVIS P0/P1 |
| R-11 | Codex ser produktionsdata | 3 | 5 | 15 | Repoinstruks; denne revision undgik private paths/prod | Netværks-/secretadskillelse, syntetisk CI, incidentregel | 8 | Repo-/teknisk ejer; P1 |
| R-12 | Uautoriseret Telegram-adgang | 4 | 5 | 20 | To målgrupper beskrevet | User-id allowlist, MFA, offboarding, kvartalsreview, bot tokenrotation | 20 | Systemejer; ÅBEN P0 |
| R-13 | Manglende sletning/sessionretention | 4 | 4 | 16 | Gitignore; enkelte tempfiler slettes | Godkend frister, automatiske jobs, deletiontest | 16 | Data-/teknisk ejer; ÅBEN P0 |
| R-14 | Backupretention/genindlæsning | 3 | 4 | 12 | Ingen evidens | Krypteret backup, expiry, restore- og deletionprocedure | 12 | Hostingejer; ÅBEN P1 |
| R-15 | Utilstrækkelig rolleopdeling | 4 | 5 | 20 | Separate agenter og read/admin-wrapper-allowlists | Verificér separate accounts, runtime-whitelist, RBAC og ingen generisk shell | 12 | Systemejer; DELVIS P0 |
| R-16 | Manglende audit/ansvarsspor | 4 | 4 | 16 | Audit-event builder | Append-only sink, actor fra Telegram identity, monitorering | 12 | Sikkerhedsejer; ÅBEN P1 |
| R-17 | Leverandør-/underdatabehandlerændring | 3 | 5 | 15 | Ingen registry i deployment | Change notification, reviewgate, periodisk vendor review | 15 | Leverandørejer; ÅBEN P0/P1 |
| R-18 | Ukendt underdatabehandler/behandlingslokation | 4 | 5 | 20 | Processorregister markerer ukendt | DPA, fuld kæde og lokation; stop PERSONAL indtil dokumenteret | 20 | Dataansvarlig; ÅBEN P0 |
| R-19 | Screenshots/tempfiler med persondata | 4 | 4 | 16 | Rå HTML-persistens fjernet; screenshots default off og gitignored | Privat krypteret tmpfs, diagnostic approval, chmod og TTL deletion ved opt-in | 8 | Teknisk ejer; DELVIS P1 |
| R-20 | API-key i Conventus query URL | 3 | 5 | 15 | Fejllog viser nu kun exceptiontype | Undersøg header/POST; proxy må ikke logge query; key rotation | 12 | Conventus-/teknisk ejer; ÅBEN P1 |
| R-21 | Navnebaseret onboarding kan ramme forkert medlem | 4 | 4 | 16 | Flere substringmatches afbrydes nu | Kræv eksakt member-id og brugerbekræftelse | 12 | Onboardingejer; DELVIS P0 |
| R-22 | Syntetisk testmode rammer rigtig produktion | 3 | 5 | 15 | `TestScope` findes, ingen prodtest udført | Bind test-id/afdeling i gateway og credential; blokér navn-only | 15 | Test-/systemejer; ÅBEN P0 |

## Konklusion

Flere kritiske risici afhænger af konfiguration uden for repoet. En kodekontrol reducerer ikke den
resterende risiko, før deployment-evidens viser, at den ligger i den obligatoriske gatewaysti og ikke
kan omgås. En DPIA bør vurderes og sandsynligvis gennemføres før AI anvendes på børneattest eller
omfattende automatiseret medlemsadministration; Datatilsynet fremhæver, at AI ofte kan indebære høj
risiko og kræver konkret konsekvensanalyse.
