# Register over leverandører/databehandlere

Rolleangivelser er foreløbige. Kontrakt, behandlingslokation og underdatabehandlere ligger ikke i
repoet og må ikke opfindes. Alle rækker kræver organisatorisk/juridisk verifikation.

**Fælles status for alle ikke-dokumenterede felter: SKAL VERIFICERES ORGANISATORISK.**

| Navn | Foreløbig rolle | Formål | Datakategorier | Region | DPA | Retention | Træning | Underdatabehandlere | Overførselsgrundlag | Godkendelsesstatus | Manglende dokumentation |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Hostinger | Hosting/databehandler | OpenClaw VPS | Alle runtimeklasser efter tool | Tyskland oplyst; storage/backup/support ukendt | Skal verificeres | Skal verificeres | Ikke relevant/ukendt telemetry | Skal verificeres | Skal verificeres for adgang uden for EØS | Ikke godkendt | DPA, lokationer, support, backup, sletning, subprocessors |
| TensorX | LLM-databehandler, hvis godkendt | Minimeret PERSONAL-inference | Nødvendig prompt/kontekst; aldrig SENSITIVE/SECRET | EU krævet; faktisk inference/support ukendt | Skal verificeres | Zero retention skal verificeres | Træningsfravalg skal verificeres | Skal verificeres | Skal verificeres | Blokeret for PERSONAL | Konto, DPA, endpoint/model/lande, zero retention, træning, kæde |
| OpenAI/Codex | Udviklingsleverandør; ikke prod-runtime | Kode/docs/syntetiske tests | PUBLIC/syntetisk | Organisationskonto/region skal verificeres hvis relevant | Skal verificeres hvis relevant | Skal verificeres | Skal verificeres | Skal verificeres | Skal verificeres | Kun udvikling; ingen proddata | Kontoindstillinger, DPA og leverandørevidens hvis organisatorisk krævet |
| GitHub | Kodehosting/CI; mulig databehandler | Versionsstyring/test | Public-egnet kode; ingen proddata/secrets | Skal verificeres | Skal verificeres | Git/artifact/logfrister skal fastsættes | Ikke relevant | Skal verificeres | Skal verificeres | Kun public-egnet repoindhold | Org-aftale, region, subprocessors, CI/artifactretention |
| Telegram | Platform; rolle afhænger af setup | Brugerkanal | Bruger-id, besked, metadata, mulig PERSONAL | Skal verificeres | Skal verificeres | Skal verificeres | Misbrugs-/modelbrug skal verificeres | Skal verificeres | Skal verificeres | Ikke godkendt til medlemsbrug | Rolle, DPA/vilkår, lande, retention/deletion, supportadgang |
| Conventus | Medlems-/økonomisystem; rolle ukendt | Medlemsadministration | PERSONAL, økonomi, atteststatus | Skal verificeres | Skal verificeres | Skal verificeres | Ikke relevant | Skal verificeres | Skal verificeres | Prod; automation ikke endeligt godkendt | Rolle/DPA, APIvilkår, lande, backup/sletning, read/write scopes |
| HalBooking | Booking-/medlemssystem; rolle ukendt | Booking/onboarding | PERSONAL, booking, e-mail, SECRET | Skal verificeres | Skal verificeres | Skal verificeres | Ikke relevant | Mail/supportkæde skal verificeres | Skal verificeres | Ikke godkendt til automation | Rolle/DPA, region, retention, maillevering, subprocessors |
| Google/Gmail | Databehandler/selvstændig rolle skal fastslås | Onboarding-mail/OAuth | Mail, navn, medlems-/gruppe-id, status | Skal verificeres | Skal verificeres | Mail/logfrister skal fastsættes | Scanning/træning skal verificeres | Skal verificeres | Skal verificeres | Blokerer auto-onboarding | Workspace/consumer-konto, DPA, region, retention, kæde |
| Fundraising Club | Privat datakilde/licenspart | Fondsresearch | Licenserede metadata, login SECRET | Skal verificeres | Ved persondata: skal verificeres | Skal verificeres | Ikke relevant | Skal verificeres | Skal verificeres | Kun bekræftet authorized use | Skriftlig automatiseringsret, region, retention, subprocessors |
| Microsoft OneDrive/SharePoint | Valgfri cloudleverandør | Historikdownload | Ansøgningshistorik, mulig PERSONAL | Tenantregion skal verificeres | Skal verificeres | Skal verificeres | Skal verificeres | Skal verificeres | Skal verificeres | Kun allowlistet direkte XLSX-link | Tenant, DPA, region, retention, subprocessors |
| Offentlige websites/API'er | Typisk selvstændige dataansvarlige | Fonds-/vedtægtskilder | PUBLIC + IP/user-agent | Varierer | Normalt ikke relevant for ren public fetch | Kildens logs ukendt | Ikke relevant | Varierer | Afhænger af kilde; intet personpayload | Kun PUBLIC | Vilkår, robots/rate limit, kildeproveniens |
| OpenClaw-projekt/runtime | Software/supportrolle afhænger af drift | Agent, tools, sessions, routing | Prompts, toolcalls, sessioner | Self-hosted DE; support/telemetry ukendt | Skal verificeres hvis leverandør behandler | Skal verificeres | Telemetry/modelbrug skal verificeres | Plugins/support skal verificeres | Skal verificeres | P0 review mangler | Version, config, telemetry, plugins, retention, support/subprocessors |
| Reverse proxy/backup/monitorering | Ukendte driftssubprocessorer | Net/log/backup | Requestmetadata, logs, backups | Skal verificeres | Skal verificeres | Skal fastsættes | Ikke relevant | Skal identificeres | Skal verificeres | Ikke godkendt | Navne, aftaler, lokation, adgang, kryptering, retention/sletning |

## Godkendelseskrav

For hver leverandør arkiveres: aftale/DPA-version, ejer, behandlingsformål, dataklasser, konkrete lande,
support-/myndighedsadgang, underdatabehandlere, kapitel V-grundlag, retention/sletning, træningsbrug,
sikkerhedsdokumentation, change-notifikation og reviewdato. Den dataansvarlige skal føre tilsyn; en DPA
alene er ikke bevis for faktisk overholdelse.

Se Datatilsynets vejledning om
[dataansvarlig/databehandler](https://www.datatilsynet.dk/regler-og-vejledning/grundlaeggende-begreber/rollefordeling-dataansvarlig-og-databehandler)
og [cloud](https://www.datatilsynet.dk/hvad-siger-reglerne/vejledning/cloud).
