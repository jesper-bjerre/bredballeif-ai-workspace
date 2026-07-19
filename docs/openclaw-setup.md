# OpenClaw setup for Bredballe IF

Dette dokument beskriver hvordan Bredballe IF bruger OpenClaw som drifts-runtime for AI-agenter og
skills fra dette monorepo.

## Overblik

OpenClaw kører agenter, som bestyrelse/udvalg kommunikerer med via Telegram-bots. Skills ligger i dette
repo under `skills/<navn>/` og installeres på OpenClaw ved at klone `bredballeif-ai-workspace`.

Secrets og persondata må aldrig committes. OpenClaw skal have nødvendige credentials i sit runtime-miljø,
fx via systemd env file, Docker secrets, OpenClaw secret store eller tilsvarende.

## Agenter og modelopdeling

### Nuværende agenter

| OpenClaw agent | Telegram bot | Formål | Skills |
|---|---|---|---|
| `bredballeif-administrator` | `BIF Administrator` | Tværgående Bredballe IF administration | `skills/bredballeif-boerneattest` |
| `bredballeif-padel-administrator` | `BIF Padel Administrator` | Padel-administration og padelmedlemskab | `skills/bredballeif-padel-baner`, `skills/bredballeif-padel-conventus`, `skills/bredballeif-padel-halbooking`, `skills/bredballeif-padel-onboarding` |

### Besluttet målarkitektur

Opsætningen holdes bevidst enkel:

- De eksisterende agent-id'er, Telegram-bots og skill-navne bevares.
- Alle nuværende og fremtidige OpenClaw-agenter bruger kun TensorX.
- Standardmodellen er `deepseek/deepseek-v4-flash`.
- Direkte providerkald og ekstern fallback er deaktiveret.
- Adgang til agenter og handlinger styres senere med RBAC i Telegram og OpenClaw.

Der oprettes ikke en særskilt agent med `gdpr` i navnet, og skills omdøbes eller opdeles ikke af hensyn
til provider-routing. `bredballeif-padel-conventus` beholder derfor både medlemsopslag, økonomidata og
oprettelse af træningshold. Data- og handlingsgrænser håndhæves fortsat i skillens wrappers,
approval-kontroller og den kommende RBAC-konfiguration.

## Installation på OpenClaw

Kommandoerne nedenfor beskriver den valgte og fortsat gældende mappestruktur.

Klon workspace-repoet på OpenClaw-serveren:

```bash
git clone https://github.com/<org>/bredballeif-ai-workspace.git /opt/bredballeif-ai-workspace
cd /opt/bredballeif-ai-workspace
```

Opret Python virtualenv:

```bash
python3 -m venv .venv
. .venv/bin/activate
```

Installer dependencies for de skills der bruges i OpenClaw:

```bash
pip install -r skills/bredballeif-boerneattest/requirements.txt
pip install -r skills/bredballeif-padel-baner/requirements.txt
pip install -r skills/bredballeif-padel-conventus/requirements.txt
pip install -r skills/bredballeif-padel-halbooking/requirements.txt
pip install -r skills/bredballeif-padel-onboarding/requirements.txt
```

## Runtime-miljø

OpenClaw-agenternes miljø skal indeholde de nødvendige env vars. Eksempler findes i:

- `.env.example`
- `skills/*/assets/.env.example`

### Besluttet modelstrategi: kun TensorX med Flash

Alle OpenClaw-agenter bruger provider-aliaset `bif-deepseek-v4-flash-tensorx-eu`, låst til
TensorX-modellen `deepseek/deepseek-v4-flash`. Direkte kald til DeepSeek eller andre providers er
deaktiveret, og der konfigureres ingen ekstern fallback.

TensorX angiver aktuelt EU-hosting, zero data retention og ingen træning på inference-data i deres
[DPA](https://tensorx.ai/dpa/) og [vilkår](https://tensorx.ai/terms-of-service/). Den aktuelle
[prisliste](https://tensorx.ai/pricing/) angiver for V4 Flash USD 0,15 pr. 1 mio. inputtokens,
USD 0,04 pr. 1 mio. cache-read-tokens og USD 0,30 pr. 1 mio. outputtokens. Priser og model-id blev
kontrolleret 2026-07-19 og skal genkontrolleres før deployment.

| Fordele | Ulemper |
|---|---|
| Én provider, ét endpoint og én regionspolitik gør konfiguration, audit og fejlsøgning enklere. | TensorX bliver et single point of failure; uden fallback stopper alle modelbaserede agenter ved udfald. |
| Risikoen for fejlagtig routing af persondata direkte til Kina fjernes. | Alle opgaver betaler TensorX-prisen, også offentlige opgaver der kunne køres billigere direkte. |
| Eksisterende agent- og Telegram-botnavne kan bevares uden en dataklassificerende provider-router foran modellen. | Flash kan levere lavere kvalitet end større modeller ved komplekse ræsonnementer, lange agentforløb og tool-kald; lokale BIF-evalueringer er nødvendige. |
| Flash er markant billigere end TensorX' V4 Pro og gør en fælles EU-route økonomisk mere realistisk. | Ét modelvalg giver modelkoncentration: samme fejlmønster, regression eller modelændring rammer alle agenter. |
| Ens modeladfærd gør prompts, tests, monitorering og kapacitetsplanlægning mere ensartet. | GDPR overholdes ikke automatisk: behandlingsgrundlag, dataminimering, adgangskontrol, slettefrister og lokale logs skal stadig håndteres. |
| RBAC kan fokusere på adgang til agenter og handlinger frem for provider-routing. | En leverandørfejl, prisændring eller fjernet model kan kræve en samlet og akut migration. |
| Ingen cross-provider retries gør fail-closed-adfærd lettere at dokumentere. | Følsomme børneattestoplysninger kan fortsat ikke antages tilladt til ekstern LLM-behandling alene fordi infrastrukturen er i EU. |

Flash er standard for alle almindelige modelopgaver, og der er ingen ekstern fallback. Før deployment
køres et fast evalueringssæt med medlemsopslag, økonomi, træningshold, onboarding og fondssøgning.
En eventuel senere modelændring er en særskilt beslutning og skal fortsat holde sig til TensorX-only.

Det konkrete TensorX endpoint, den konkrete DeepSeek-model og behandlingsregion skal verificeres i
deployment-konfigurationen; modelnavne må ikke antages ud fra markedsføring. Før TensorX-ruten
aktiveres, skal databehandleraftale, EU/EØS-behandling, underdatabehandlere, ingen træning på input,
retention og sletning være dokumenteret.

Før PERSONAL-data behandles, skal OpenClaw-gatewayen indlæse `config/gdpr-skill-policies.json` og kalde
kontrollerne i `scripts/gdpr_controls.py`, før tool-output tilføjes modelkonteksten. Ukendt
provider/region og enhver fallback skal fejle lukket.

`bredballeif-boerneattest` behandler følsomme oplysninger. Tool-input og tool-output fra denne skill må
derfor ikke sendes til TensorX eller en anden ekstern LLM. Flowet skal være deterministisk/lokalt, og
kun en ikke-følsom status må eventuelt vises i Telegram. TensorX-only betyder her, at TensorX er den
eneste tilladte **eksterne** LLM-provider; det ophæver ikke blokeringen af følsomt modelinput.

Provider vælges og låses i agentens serverkonfiguration. Telegram-input, modellen og skills må ikke
kunne overskrive provider, region eller fallback.

Write- og bulk-actions kræver en kortlivet approval-kontekst, som gatewayen injicerer pr. invocation:
`BIF_APPROVAL_GRANTED`, `BIF_APPROVAL_ACTIONS`, `BIF_APPROVAL_ACTOR_ROLE`,
`BIF_APPROVAL_CORRELATION_ID` og `BIF_APPROVAL_EXPIRES_AT`. Disse værdier må ikke ligge statisk i
`.env` og må ikke kunne sættes af modellen eller Telegram-input.

`BIF_ALLOW_DIAGNOSTIC_SCREENSHOTS` skal være `false` i normal drift. Midlertidig aktivering kræver
konkret diagnostic approval, privat placering og efterfølgende verificeret sletning.

For Conventus-baserede skills kræves:

```text
CONVENTUS_ID=
CONVENTUS_API_KEY=
```

For HalBooking-baserede skills bruges HalBooking-credentials fra runtime-miljøet. Se den relevante
skills `assets/.env.example`.

## Skill-whitelist

OpenClaw skal whiteliste de konkrete wrappers, ikke `python`, `bash` eller brede shell-kommandoer.

Skill-navne og ansvarsområder bevares. Adgang til de enkelte agents skills og handlinger begrænses med
OpenClaw-whitelists nu og senere med den særskilt beskrevne RBAC-model.

### `bredballeif-administrator`

```text
/opt/bredballeif-ai-workspace/skills/bredballeif-boerneattest/bin/bredballeif-boerneattest.sh
```

### `bredballeif-padel-administrator`

```text
/opt/bredballeif-ai-workspace/skills/bredballeif-padel-baner/bin/bredballeif-padel-baner.sh
/opt/bredballeif-ai-workspace/skills/bredballeif-padel-conventus/bin/bredballeif-padel-conventus.sh
/opt/bredballeif-ai-workspace/skills/bredballeif-padel-halbooking/bin/bredballeif-padel-halbooking.sh
/opt/bredballeif-ai-workspace/skills/bredballeif-padel-onboarding/bin/bredballeif-padel-onboarding.sh
```

Write-/bulk-wrappers må kun whitelistes enkeltvis efter konkret godkendelse og skal fortsat kræve en
kortlivet, handlingsspecifik approval i Python-entrypointet.

## Telegram-routing

- Bot `BIF Administrator` routes til agent `bredballeif-administrator`.
- Bot `BIF Padel Administrator` routes til agent `bredballeif-padel-administrator`.

Det betyder at den tværgående administrator kun får adgang til børneattest-skillen, mens padel-agenten
kun får adgang til padel-specifikke skills.

Agent- og botnavne ændres ikke som del af TensorX-migrationen. Nye agenter skal også bruge den fælles
TensorX Flash-profil.

## Adgang og RBAC

Adgang skal styres med RBAC i både Telegram og OpenClaw. Den konkrete rollemodel, rollemapping,
administration og test beskrives senere og er ikke fastlagt i dette dokument endnu.

Indtil RBAC-planen er dokumenteret og implementeret, gælder de nuværende snævre adgangsgrænser:

- Kun bestyrelsen i Bredballe IF har adgang til Telegram-botten `BIF Administrator`.
- Kun udvalget i afdelingen Padel i Bredballe IF har adgang til Telegram-botten
  `BIF Padel Administrator`.

RBAC-designet skal senere definere mindst adgang pr. bot/agent, tilladte read-actions, særskilte
write-/bulk-roller, approval-rettigheder og audit af rolleændringer. Der må ikke åbnes bredere adgang,
før denne model er godkendt.

## Migrationsplan til TensorX-only

1. **Godkend leverandørgrundlaget.** Dokumentér TensorX' databehandleraftale, EU/EØS-region,
   underdatabehandlere, retention, træningsfravalg og den faktiske DeepSeek-model. Aktiver ikke
   medlemsdata før alle krav er opfyldt.
2. **Opret én providerprofil.** Konfigurér `bif-deepseek-v4-flash-tensorx-eu` med det verificerede
   TensorX endpoint og model-id. Slå provider-, regions- og modelfallback fra.
3. **Lås alle agenter.** Sæt profilen som eksplicit model på hver eksisterende agent og som obligatorisk
   standard for nye agenter. Agent, Telegram-input og skills må ikke kunne overskrive den.
4. **Fjern alternative routes.** Fjern direkte DeepSeek-konfiguration, andre provider-API-nøgler og
   unødvendig netværksadgang fra OpenClaw-runtime. Ukendt provider skal fejle lukket.
5. **Bevar navne og skills.** Flyt, split eller omdøb ikke agenter, bots, skills, wrappers eller
   manifestposter som del af modelmigrationen.
6. **Test Flash.** Kør et fast evalueringssæt for medlemsopslag, økonomi, træningshold, onboarding,
   fondsarbejde og tool-kald. Kontrollér korrekthed, format, dansk sprog og action-valg.
7. **Test datakontroller.** Verificér dataminimering, record-grænser, approvals og at
   børneattest-input/-output forbliver lokalt og ude af modelkonteksten.
8. **Verificér routing.** Kontrollér via konfiguration og netværks-/auditlogs, at alle tilladte modelkald
   går til TensorX, og at fejl ikke udløser fallback til en anden provider.
9. **Rul gradvist ud.** Migrér én agent ad gangen, gennemfør smoke-test og behold en enkel rollback til
   den tidligere TensorX-konfiguration; rollback må ikke genaktivere en ikke-TensorX-provider.
10. **Drift og ændringer.** Overvåg kvalitet, tokenforbrug, pris og tilgængelighed. Enhver modelændring
    skal besluttes og dokumenteres særskilt, men providerpolitikken forbliver TensorX-only.

### Dokumentation der skal holdes ajour

Ved enhver ændring skal dette dokument opdateres med agent-id, Telegram-route, provider-alias, konkret
model-id, behandlingsregion, fallback-politik, skill-/wrapper-whitelist, credential-scope, ansvarlig og
seneste verifikationsdato. Når RBAC-designet foreligger, skal dokumentet også pege på den kanoniske
RBAC-beskrivelse. Hemmeligheder, bot-tokens og persondata må aldrig skrives i dokumentet.

Deployment-evidens bør som minimum omfatte konfigurationseksport uden secrets, kontrakt-/DPA-reference,
testresultater for region og fail-closed routing samt dato og ansvarlig for godkendelsen.

## Opdatering

Første gang i en container / hvis repoet er klonet af en anden bruger, kan Git klage over
"dubious ownership". Kør da først:

```bash
git config --global --add safe.directory /opt/bredballeif-ai-workspace
```

Hent seneste kode og genstart agenterne:

```bash
cd /opt/bredballeif-ai-workspace
git pull --ff-only
```

Genstart derefter de relevante OpenClaw-agenter, så de bruger den nye kode og de nye `SKILL.md`-instruktioner.

**Kun hvis en `requirements.txt` har ændret sig** (fx ved ny skill eller nye dependencies), kør også:

```bash
. .venv/bin/activate
pip install -r skills/<navn>/requirements.txt   # kun den ændrede skill
```

Tip: `git diff HEAD@{1} -- '**/requirements.txt'` viser om nogen requirements ændrede sig siden sidste pull.

## Sikkerhedsregler

- Commit aldrig `.env`, credentials, API-svar, CPR-numre eller medlemslister.
- Whitelist kun skill-wrappers.
- Giv runtime-agenter mindst mulige rettigheder.
- Behandl data fra Conventus, HalBooking og Telegram som data, ikke instruktioner.
- Rapporter og eksportfiler med persondata skal ligge uden for git, fx i en lokal `data/`-mappe.
