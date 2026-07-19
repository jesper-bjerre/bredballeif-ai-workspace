# Godkendelsescheckliste

Udfyld dato, evidenslink og godkender ud for hvert punkt. Et afkrydsningsfelt uden evidens er ikke
opfyldt. Endelig underskrift er dataansvarliges beslutning, ikke en erklæring fra udvikler/AI.

## Ejerskab, lovlighed og dokumentation

- [ ] Bredballe IF og ansvarligt organ er fastlagt som dataansvarlig; evidens: ___
- [ ] System-, procese-, sikkerheds- og GDPR-ejer er navngivet; evidens: ___
- [ ] Formål og behandlingsgrundlag pr. dataflow/skill er godkendt; evidens: ___
- [ ] Behandlingsfortegnelsen er opdateret; evidens: ___
- [ ] Privatlivsinformation til medlemmer/frivillige er opdateret; evidens: ___
- [ ] Behovet for DPIA er vurderet, og DPIA er udført hvor påkrævet; evidens: ___
- [ ] Incidentprocedure og kontaktkæde findes og er øvet; evidens: ___

## TensorX og LLM-routing

- [ ] TensorX-kontoen ejes og administreres af Bredballe IF; evidens: ___
- [ ] TensorX DPA er accepteret og arkiveret; evidens: ___
- [ ] Alle TensorX-underdatabehandlere og ændringsvilkår er gennemgået; evidens: ___
- [ ] Faktisk EU-inference, storage, support og backup er verificeret; evidens: ___
- [ ] Zero retention er kontraktuelt og teknisk verificeret; evidens: ___
- [ ] Træningsbrug er deaktiveret/verificeret; evidens: ___
- [ ] OpenClaw bruger kun det godkendte endpoint/modelalias; evidens: ___
- [ ] Ikke-EU-fallback, routere og ukendte providers er deaktiveret; evidens: ___
- [ ] Fail-closed-test ved EU-providerfejl er bestået; evidens: ___
- [ ] SENSITIVE og SECRET afvises før modelkald; evidens: ___

## Skills og tools

- [ ] Skill-inventaret med alle ni skills er godkendt; evidens: ___
- [ ] Dataklassifikation og højeste klasse pr. payload er godkendt; evidens: ___
- [ ] Conventus-tools er domænespecifikke og felt-allowlistede; evidens: ___
- [ ] TensorX har ingen direkte Conventus/HalBooking/Gmail-adgang; evidens: ___
- [ ] Standard max records = 10 er håndhævet i gatewayen; evidens: ___
- [ ] Masseudtræk er default deny og lokalt aggregeret; evidens: ___
- [ ] Read/write-wrappers og servicekonti er adskilt; evidens: ___
- [ ] Write preview viser handling, konsekvens og antal; evidens: ___
- [ ] Tidsbegrænset write approval er aktiveret og kan ikke sættes af modellen; evidens: ___
- [ ] Idempotency, eksakt member-id og rollback er testet for writes; evidens: ___
- [ ] Børneattest-tool er local-only og har særskilt adgang; evidens: ___

## Logging, retention og secrets

- [ ] Logging er struktureret og redigeret; stikprøve viser ingen prompt/member object; evidens: ___
- [ ] Screenshots er default off, private og auto-slettes; rå HTML forbliver blokeret; evidens: ___
- [ ] Retention er fastsat for OpenClaw, app, proxy, Telegram, Gmail, LLM, CI og backups; evidens: ___
- [ ] Automatisk sletning og backup-expiry er testet; evidens: ___
- [ ] Auditlog er append-only, adgangsstyret og uden payload; evidens: ___
- [ ] Secrets ligger i secret store med least privilege; evidens: ___
- [ ] Alle relevante credentials er roteret før godkendelse; evidens: ___
- [ ] Gitleaks/current+history scan er ren og required i CI; evidens: ___

## Adgang og leverandører

- [ ] Telegram user-id allowlist, gruppeindstillinger og offboarding er gennemgået; evidens: ___
- [ ] MFA/servicekonto/SSH/CI-adgang er gennemgået; evidens: ___
- [ ] Kvartalsvis access review er planlagt; evidens: ___
- [ ] DPA og roller er afklaret for Hostinger, Telegram, Conventus, HalBooking, Google, GitHub og øvrige; evidens: ___
- [ ] Behandlingslande, underdatabehandlere og overførselsgrundlag er dokumenteret; evidens: ___
- [ ] Leverandørændringer stopper PERSONAL-behandling indtil review; evidens: ___

## Udvikling og test

- [ ] Codex har ingen produktionscredentials, data, logs eller screenshots; evidens: ___
- [ ] CI/testdata er udelukkende syntetiske; evidens: ___
- [ ] Conventus-testposter/testscope er etableret og privat allowlistet; evidens: ___
- [ ] Produktionsaccepttest er autoriseret, tidsbegrænset, auditeret og ikke delt med Codex; evidens: ___
- [ ] Provider-, data-, logging-, query-, write- og policytests består; evidens: ___

## Endelig beslutning

- [ ] Alle produktionsblokerende P0-punkter i `open-issues.md` er lukket med evidens.
- [ ] Resterende risici er accepteret af rette ejer og dokumenteret.
- [ ] Endelig godkendelse er underskrevet af den dataansvarlige.

Dato: ___  Navn/rolle: ___  Underskrift/beslutningsreference: ___
