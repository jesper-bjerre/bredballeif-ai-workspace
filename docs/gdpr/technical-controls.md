# Tekniske kontroller

Status: **I** implementeret i repo, **D** delvist, **M** mangler, **U** ukendt eksternt.

| ID | Krav og begrundelse | Implementeringssted / evidens | Status | Mangel / anbefalet ændring |
|---|---|---|:---:|---|
| GDPR-TECH-001 | PERSONAL kun EU/EØS-provider og alle klasser følger allowed regions | `gdpr_controls.validate_provider_route`; provider/region tests | I/D | Integrér før hvert OpenClaw modelkald |
| GDPR-TECH-002 | Ingen ikke-EU-fallback; fail closed | Policy default + route test | I/D | Verificér faktisk config/retry/aliases |
| GDPR-TECH-003 | Ukendt provider afvises | Validator + test | I/D | Gateway må ikke have anden route |
| GDPR-TECH-004 | SENSITIVE ekstern LLM blokeret | `assert_model_payload_allowed`; børneattest approval | I/D | Bevis local-only/session-off i deployment |
| GDPR-TECH-005 | SECRET før model afvises | Key/payload scanner + tests | I/D | Kald kontrollen på prompt+historik+tool-output |
| GDPR-TECH-006 | Dataminimering/field allowlist | `minimize_member`; Conventus search allowlist | D | Domænetools/gateway skal kassere råobjekt straks |
| GDPR-TECH-007 | Standard max 10 | `enforce_record_limit` afviser også brugerhævet limit uden bulk-approval; Conventus/HalBooking/Gmail | D | Håndhæv samme kontrakt i gateway og resterende listtools |
| GDPR-TECH-008 | Brede/tomme queries afvises | `reject_broad_query`; Conventus/HalBooking navn | D | Server-/gatewayvalidering for alle querytools |
| GDPR-TECH-009 | Masseudtræk særskilt approval | `*.bulk-read`; export stdout blok | D | Krypteret outputroot, lokal aggregate, bulk-role |
| GDPR-TECH-010 | Write kræver menneskelig approval | `ApprovalContext`, action maps, gruppe/booking/onboarding gates | D | OpenClaw approval-controller skal injicere ikke-modelkontrolleret env |
| GDPR-TECH-011 | Approval kort/scoped | ≤15 min, exact action, actor role, correlation | I/D | Engangsnonce/signatur og replaystore i gateway |
| GDPR-TECH-012 | Struktureret audit uden payload | `audit_event`, `emit_audit_event` | D | Append-only central sink og monitorering mangler |
| GDPR-TECH-013 | Logredaction | recursive redact + tests; rå subprocess/password fjernet | D | Centralisér alle print/logger; produktionstest med syntetisk data |
| GDPR-TECH-014 | Screenshots private og kortlivede; rå HTML ikke lagret | Rå HTML-persistens fjernet; screenshots default off via `BIF_ALLOW_DIAGNOSTIC_SCREENSHOTS`; gitignore | D | Secure temp root, diagnostic approval, TTL deletion og no-session-evidens |
| GDPR-TECH-015 | Credentials kun secret store/env | `.env` ignored; env readers; placeholders | D | VPS secret store, separate identities, rotation; ingen root-readable env |
| GDPR-TECH-016 | Secret scan | Manuel redacted scan fandt ingen hardcoded Python-secret constants | M | Gitleaks current+history som required CI check |
| GDPR-TECH-017 | Snævre tools; ingen rå HTTP | Ingen generisk raw API wrapper fundet | D | Erstat list/export/discover med formålsbestemte contracts |
| GDPR-TECH-018 | TensorX ingen systemcredentials | Arkitektur/policy | M | Netværkssegmentering og egressbevis; model kun minimeret payload |
| GDPR-TECH-019 | Prompt-injection isolation | Instruktioner i AGENTS/SKILL | D | Typed content boundary, egress/tool policy og tests |
| GDPR-TECH-020 | Rollebaseret adgang | Separate OpenClaw-agenter dokumenteret | U | Telegram ID allowlist, RBAC, MFA/offboarding evidens |
| GDPR-TECH-021 | Read/write serviceaccounts | Read-only anbefalet | U | Separate Conventus/HalBooking credentials og rettighedstest |
| GDPR-TECH-022 | Testscope i én prodinstans | `TestScope` + test | D | Privat allowlist, syntetiske testposter og integration i tools |
| GDPR-TECH-023 | Ingen produktionsdata til Codex/CI | AGENTS + udviklingspolicy | D | Teknisk netværks-/secretadskillelse og CI-evidens |
| GDPR-TECH-024 | Retention og deletion | Enkelte tempfiler slettes | M | Frister, jobs, backups, sessioner og deletiontest |
| GDPR-TECH-025 | Kryptering transit/hvile | HTTPS URLs i kode | U | TLS/cert, disk/backup/log encryption og key management |
| GDPR-TECH-026 | Idempotency/eksakt record | HalBooking abort ved søgefejl og flere navnematches | D | Eksakt member-id, idempotency key, dry-run/rollback |
| GDPR-TECH-027 | Forkert modtager forebygges | Fast admin env | D | Modtagerallowlist, preview/approval og maskeret statusmail |
| GDPR-TECH-028 | Provider-/vendorændring gate | Policy registrystruktur | M | Periodisk revalidation og automatisk stop ved change |
| GDPR-TECH-029 | Policy dækker alle manifestskills | JSON policy + manifesttest | I | CI skal køre testen ved hver PR |
| GDPR-TECH-030 | Wrapper er least privilege | Separate read/admin action-allowlists for baner, Conventus, HalBooking og onboarding | I/D | Verificér runtime-whitelist og separate read/write-servicekonti |

## Testevidens

`python -m unittest tests.test_gdpr_controls -v` dækker EU/non-EU/ukendt provider, fallback,
SECRET/SENSITIVE, minimization, forbidden fields, e-mail/telefon/API-key/Authorization redaction,
raw member log, max records, bulk, broad query, write/mass-write approval, audit og testscope samt
policy-manifestdækning samt forsøg på at hæve record-limit uden bulk-approval. Testene er syntetiske
og foretager ingen netværkskald.

GRØN kræver både bestået repo-test og deployment-evidens for alle D/U/M P0-kontroller.
