# GDPR-dokumentation for Bredballe IFs OpenClaw-skills

## Formål og scope

Denne mappe er den tekniske og organisatoriske vurdering af de ni skills i
`skills.manifest.json`, deres Python-entrypoints, wrappers, eksterne systemer og det dokumenterede
OpenClaw-setup. Revisionen er udført 19. juli 2026 uden produktionskald, uden læsning af lokal `.env`,
`data/`, screenshots, caches eller produktionslogs.

Dokumentationen er **ikke en juridisk GDPR-godkendelse**. Den gør løsningen klar til dataansvarliges,
bestyrelsens og eventuel rådgivers vurdering. Hostinger-lokation i Tyskland og ønsket brug af TensorX
er oplyst i opgaven; de kan ikke verificeres fra repositoryet.

## Kritiske fund

1. **LLM-routing kan ikke verificeres.** Ingen tracket OpenClaw-provider-, model-, region-, retry- eller
   fallbackkonfiguration findes. Policyfilen markerer selv status
   `REQUIRES_OPENCLAW_INTEGRATION` (`config/gdpr-skill-policies.json:3`).
2. **Kontrolkernen er ikke bevist obligatorisk.** `scripts/gdpr_controls.py` og dens tests fejler
   lukket, men gatewaykaldet og bypass-beskyttelsen ligger uden for repoet.
3. **Conventus henter brede objekter før lokal filtrering.** Medlemsendpointet kaldes pr. gruppe i
   `skills/bredballeif-padel-conventus/scripts/agent.py:113-130`, og søgning filtrerer først efter
   fuldt lokalt udtræk (`:222`). TensorX må ikke få dette rå resultat.
4. **SENSITIVE isolation er ikke end-to-end bevist.** Børneatteststatus beregnes og udskrives lokalt
   (`skills/bredballeif-boerneattest/scripts/agent.py:411-412`, `:594-609`), men OpenClaw-session- og
   modeludelukkelse kan ikke verificeres.
5. **Telegram-RBAC og retention er ukendt.** Repoet beskriver målgrupper, men ikke user-id allowlist,
   offboarding, faktisk agentkonfiguration, sessionfrister eller sletning.
6. **Conventus API-nøglen transporteres i query-string.** Koden logger ikke værdien, men URL-, proxy-
   eller leverandørlogs kan gøre det (`padel-conventus/scripts/agent.py:124` og
   `boerneattest/scripts/agent.py:138-142`). Leverandørens mulighed for header/POST skal undersøges.

Den maskerede current-tree-scan fandt ingen literal-hardcodede secrets og ingen tracket `.env`-sti.
`gitleaks` var ikke installeret; fuld historik-/entropy-scan er derfor fortsat påkrævet.

## Systemoverblik

Brugere kommunikerer ifølge [OpenClaw-setup](../openclaw-setup.md) via Telegram med to OpenClaw-agenter.
De whitelister skill-wrappers, som kan kalde Conventus, HalBooking, Gmail og offentlige webkilder.
LLM-routing, modeller, region, fallback, OpenClaw-sessionlagring, reverse proxy, backups og deployment er
ikke tracket. Derfor kan repoet ikke bevise, at PERSONAL-data kun behandles hos en EU-provider.

## Dokumenter

| Dokument | Formål |
|---|---|
| [Ledelsesopsummering](management-summary.md) | Beslutningsgrundlag i ikke-teknisk sprog |
| [Systemarkitektur](system-architecture.md) | Komponenter, trust boundaries og diagrammer |
| [Skill-inventar](skill-inventory.md) | Samtlige ni skills og deres klassifikation |
| [Dataflowregister](data-flow-register.md) | Konkrete overførsler, lagring og risici |
| [Dataklassifikation](data-classification-policy.md) | PUBLIC, INTERNAL, PERSONAL, SENSITIVE og SECRET |
| [LLM-providerpolitik](llm-provider-policy.md) | EU-lock, providerkrav og fail-closed-regler |
| [Conventus-behandling](conventus-processing.md) | Tool-design, test og produktionsinstans |
| [Udvikling og test](development-and-testing-policy.md) | Codex, fixtures, testposter, PR og CI |
| [Logging og retention](logging-and-retention-policy.md) | Logs, redaction, sletning og backups |
| [Adgangsmatrix](access-control-matrix.md) | Roller, systemer, read/write og approvals |
| [Risikovurdering](risk-assessment.md) | Scoret risikoregister og ejerskab |
| [Tekniske kontroller](technical-controls.md) | Krav, evidens, status og mangler |
| [Databehandlerregister](processor-register.md) | Kendte leverandører og verificeringsbehov |
| [Godkendelsescheckliste](approval-checklist.md) | Afkrydsning før dataansvarliges godkendelse |
| [Åbne punkter](open-issues.md) | P0–P3 backlog med produktionsblokering |

Runtime-policyens deklarative udgangspunkt ligger i
[`config/gdpr-skill-policies.json`](../../config/gdpr-skill-policies.json), og den testede
kontrolkerne ligger i [`scripts/gdpr_controls.py`](../../scripts/gdpr_controls.py). OpenClaw anvender
dem ikke automatisk; integrationen er et åbent P0-punkt.

## Samlet status

| Område | Status | Konklusion |
|---|---|---|
| Repo-secrets | GUL | Ingen hardcodet secret-streng fundet i trackede Python-filer; gitleaks og historikscan mangler |
| Dataminimering | GUL | Outputfelter, bulkgrænse og eksport er strammet, men Conventus API henter stadig hele objekter lokalt |
| Provider/region | RØD | Ingen tracket runtime-routing, model, region-lock eller fallbackkonfiguration |
| Write approval | GUL | Fail-closed kode er tilføjet; gateway-injektion og organisatorisk flow mangler |
| SENSITIVE | RØD | Børneattest er gated til lokal behandling, men end-to-end isolation fra LLM er ikke bevist |
| Logging/retention | RØD | Kodelogs er forbedret; VPS-, Telegram-, proxy-, provider- og backupretention er ukendt |
| Adgangskontrol | RØD | Roller er beskrevet, men Telegram-identiteter og OpenClaw-RBAC kan ikke verificeres |

**Teknisk status: RØD.** Den nuværende dokumenterede løsning må ikke godkendes til behandling af
medlems- eller børneattestdata, før alle P0-punkter er lukket og kontrolleret i deploymentet.

## Vigtigste konklusioner

1. Repoet indeholder ingen LLM-klient; providerbeslutningen ligger i den manglende OpenClaw-konfiguration.
2. Conventus-, HalBooking- og onboardingkode behandler almindelige personoplysninger. Børneatteststatus
   er klassificeret SENSITIVE i denne løsning.
3. Browserautomation kan oprette grupper, medlemmer, medlemskaber, bookinger og sende e-mail.
4. Kontrolkernen afviser ukendt/non-EU provider for PERSONAL, alle eksterne SENSITIVE-/SECRET-payloads,
   brede queries, for store resultater og writes uden tidsbegrænset approval.
5. Kontrollerne er kun fuldt virksomme, når OpenClaw gatewayen registrerer skills, kalder providercheck
   før modelkald og injicerer approval-metadata uden at modellen kan ændre dem.

## Ansvar og godkendelse

Bredballe IF er forventet dataansvarlig, men rollen og behandlingsgrundlag skal bekræftes. Bestyrelsen
udpeger systemejer og GDPR-ejer, godkender dataklasser og rollemodel og arkiverer den underskrevne
checkliste. Teknisk ejer leverer deployment-evidens. Databehandleraftaler, underdatabehandlere,
overførselsgrundlag og privatlivsinformation godkendes organisatorisk/juridisk.

Officielt grundlag: Datatilsynets vejledninger om
[privacy by design](https://www.datatilsynet.dk/regler-og-vejledning/behandlingssikkerhed/databeskyttelse-gennem-design-og-standardindstillinger),
[testdata](https://datatilsynet.dk/regler-og-vejledning/behandlingssikkerhed/testdata-anvendelse-af-personoplysninger-ved-udvikling-og-test-af-it-systemer),
[behandlingssikkerhed](https://www.datatilsynet.dk/regler-og-vejledning/behandlingssikkerhed) og
[rollefordeling](https://www.datatilsynet.dk/regler-og-vejledning/grundlaeggende-begreber/rollefordeling-dataansvarlig-og-databehandler).

## Endelig status

```text
Teknisk status:
RØD

Klar til begrænset produktion:
NEJ for den beskrevne samlede løsning. En teknisk isoleret PUBLIC-only fase kan vurderes særskilt.

Klar til behandling af almindelige personoplysninger:
NEJ

Klar til behandling af følsomme oplysninger:
NEJ som udgangspunkt; kræver særskilt dokumenteret lokal løsning, hjemmel og risikovurdering.

Åbne juridiske og organisatoriske beslutninger:
Dataansvar/behandlingsgrundlag, DPIA-behov, DPA'er og underdatabehandlere, TensorX EU/zero-retention,
Telegram-adgang, retention/sletning/backups, servicekonti, incidentprocedure og formel sign-off.
```
