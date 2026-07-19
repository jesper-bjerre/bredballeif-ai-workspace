# Åbne punkter og prioriteret handlingsplan

Prioritet: P0 før medlems-/produktionsbrug, P1 snarest, P2 bør løses, P3 forbedring. Ejer og deadline
skal erstattes med navngiven person/dato ved bestyrelsens behandling.

| ID | Titel / beskrivelse | Risiko | Berørte skills | Type | Handling | Prioritet | Ejer / deadline | Blokerer produktion |
|---|---|---|---|---|---|:---:|---|:---:|
| OI-001 | OpenClaw provider/model/region/fallback er ikke i repo | Tredjeland/ukendt route | Alle med model | Teknisk/org | Integrér policy, lever redigeret config og failovertest | P0 | Teknisk ejer / før go-live | Ja |
| OI-002 | TensorX DPA, EU-inference, zero retention og subprocessors ikke verificeret | Ulovlig/ukendt behandling | PERSONAL skills | Juridisk/org | Vendor due diligence og arkivér evidens | P0 | Dataansvarlig / før go-live | Ja |
| OI-003 | Gateway kalder ikke dokumenteret `gdpr_controls` | Kontroller kan omgås | Conventus/HalBooking/onboarding/børneattest | Teknisk | Gør policy obligatorisk før tools/model; bypass-test | P0 | OpenClaw-ejer / før go-live | Ja |
| OI-004 | Approval-controller mangler | Writes kan være blokeret eller forkert autoriseret | Alle write-tools | Teknisk | Ikke-modelstyret approval med nonce/replaystore, preview og audit | P0 | OpenClaw-ejer / før writes | Ja |
| OI-005 | Børneattest end-to-end local-only ikke bevist | SENSITIVE til LLM/session | Børneattest | Teknisk/juridisk | Lokal renderer, ingen model/session, DPIA-vurdering | P0 | Data-/systemejer / før brug | Ja |
| OI-006 | Telegram identitetskontrol/RBAC ukendt | Uautoriseret adgang | OpenClaw agents | Teknisk/org | User-id allowlist, MFA, offboarding, access review | P0 | Systemejer / før go-live | Ja |
| OI-007 | Read/admin-wrapperne er opdelt i repoet, men deployment er ikke verificeret | Forkert whitelist/servicekonto kan genåbne writeflade | Baner/Conventus/HalBooking/onboarding | Teknisk | Verificér kun relevante wrappers, separate credentials og deny-test i OpenClaw | P0 | Systemejer / før go-live | Ja |
| OI-008 | Onboarding mangler eksakt member-id | Flere substringmatches afbrydes nu, men entydigt id-input mangler | Onboarding/HalBooking | Teknisk | Kræv eksakt Conventus member-id og confirmation | P0 | Onboardingejer / før writes | Ja |
| OI-009 | Conventus returnerer hele member object | Overbehandling/eksfiltration | Conventus/onboarding/børneattest | Teknisk | Gateway projection straks; undersøg server-side felter | P0 | Integrationsejer / før PERSONAL LLM | Ja |
| OI-010 | Screenshots er default off og rå HTML-persistens fjernet, men sikker opt-in-retention mangler | Diagnostic data kan ligge på disk ved aktivering | Browser-skills | Teknisk | Secure temp root, særskilt approval, TTL/delete test | P1 | Teknisk ejer / før diagnostik | Nej ved default-off |
| OI-011 | Testmode/testscope ikke integreret i prodtools | Test rammer rigtigt medlem | Onboarding/Conventus | Teknisk/org | Syntetiske testposter og private id/department allowlist | P0 | Testejer / før integrationstest | Ja |
| OI-012 | DPA/rolle/region ukendt for leverandørkæden | Manglende ansvar/overførsel | Alle eksterne systemer | Juridisk/org | Udfyld processorregister og behandlingsfortegnelse | P0 | Dataansvarlig / før PERSONAL | Ja |
| OI-013 | Retention/deletion/backups/sessioner ukendt | For lang opbevaring | Alle | Org/teknisk | Godkend frister, konfigurer jobs, deletion/restoretest | P0 | Data-/teknisk ejer / før PERSONAL | Ja |
| OI-014 | Central logpipeline/audit sink mangler | Læk/manglende spor | Alle runtime skills | Teknisk | Structured logger, append-only sink, alerting, logscan | P1 | Sikkerhedsejer / 30 dage | Nej for public-only; ja for writes |
| OI-015 | Secret/history scan og CI mangler | Skjulte credentials | Repo | Teknisk | Gitleaks full history + required CI; rotér ved fund | P1 | Repoejer / 14 dage | Ja ved fund |
| OI-016 | API-key ligger i Conventus query URL | Proxy/errorlog-læk | Conventus/børneattest | Teknisk/vendor | Undersøg header/POST; query-log off; rotation | P1 | Integrationsejer / 30 dage | Ja hvis logs URL |
| OI-017 | Eksportfil har fri sti, ingen kryptering/TTL | Lokal medlemsliste | HalBooking/compare | Teknisk | Privat allowlisted root, permissions, encryption, auto-delete | P1 | Teknisk ejer / 30 dage | Ja for export |
| OI-018 | Gmail statusmail kan indeholde navn/hold/fejl | Forkert modtager/mailretention | Onboarding | Teknisk/org | Minimer summary, recipient allowlist, DPA/retention | P1 | Procesejer / 30 dage | Nej hvis flow lukket |
| OI-019 | Servicekonti/read-write scopes ikke verificeret | For brede rettigheder | Conventus/HalBooking/Gmail | Teknisk/org | Separate accounts og dokumenteret rettighedstest | P1 | Systemejer / 30 dage | Ja for writes |
| OI-020 | Prompt injection kun instruktion, ikke gatewaytest | Tool/egress manipulation | Mail/web/API skills | Teknisk | Typed untrusted content, adversarial tests, egress allowlist | P1 | AI-systemejer / 30 dage | Ja for agentiske writes |
| OI-021 | Fondsdata retention/kryptering ukendt | Projekt/persondata læk | Fondsansøgning | Org/teknisk | Datakategori-frister, private volume encryption | P2 | Fonds-/teknisk ejer / 60 dage | Nej for public research |
| OI-022 | Økonomirapport kan indeholde identifikatorer | PERSONAL i analyse | Økonomi/Conventus | Teknisk | Local scrub/field allowlist før model | P1 | Økonomi-/teknisk ejer / før prod | Ja for rapport med persontekst |
| OI-023 | Hardcodede gruppe-/år-id'er vedligeholdes manuelt | Forkert scope/udtræk | Padel Conventus/onboarding | Teknisk/org | Versioneret registry, owner/reviewdate og deny unknown | P2 | Padel-systemejer / kvartal | Nej |
| OI-024 | Policytests ikke i CI | Regression | Alle | Teknisk | Kør compile/unit/policy/secret tests pr. PR | P1 | Repoejer / 14 dage | Nej |
| OI-025 | Managementcheckliste mangler formel sign-off | Ingen ansvarlig accept | Alle | Org | Bestyrelsesbeslutning med evidenslinks | P0 | Dataansvarlig / før go-live | Ja |

## Faseplan

- **P0:** Isolér PUBLIC-only drift eller hold alt lukket; etabler providerlock, RBAC, approvals,
  local-only SENSITIVE, vendor/DPA, retention og testscope.
- **P1:** Central audit/log, secret CI, injectiontests og sikre eksport/logflader.
- **P2:** Fonds-/økonomiretention, vedligeholdelsesregistries og kvalitetsforbedringer.
- **P3:** Automatiser dokumentationsgenerering og kvartalsrapporter, når P0/P1 er stabile.
