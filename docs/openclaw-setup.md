# OpenClaw setup for Bredballe IF

Dette dokument beskriver hvordan Bredballe IF bruger OpenClaw som drifts-runtime for AI-agenter og
skills fra dette monorepo.

## Overblik

OpenClaw kører agenter, som bestyrelse/udvalg kommunikerer med via Telegram-bots. Skills ligger i dette
repo under `skills/<navn>/` og installeres på OpenClaw ved at klone `bredballeif-ai-workspace`.

Secrets og persondata må aldrig committes. OpenClaw skal have nødvendige credentials i sit runtime-miljø,
fx via systemd env file, Docker secrets, OpenClaw secret store eller tilsvarende.

## Agenter

| OpenClaw agent | Telegram bot | Formål | Skills |
|---|---|---|---|
| `bredballeif-administrator` | `BIF Administrator` | Tværgående Bredballe IF administration | `skills/bredballeif-boerneattest` |
| `bredballeif-padel-administrator` | `BIF Padel Administrator` | Padel-administration og padelmedlemskab | `skills/bredballeif-padel-baner`, `skills/bredballeif-padel-conventus`, `skills/bredballeif-padel-halbooking`, `skills/bredballeif-padel-onboarding` |

## Installation på OpenClaw

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

For Conventus-baserede skills kræves:

```text
CONVENTUS_ID=
CONVENTUS_API_KEY=
```

For HalBooking-baserede skills bruges HalBooking-credentials fra runtime-miljøet. Se den relevante
skills `assets/.env.example`.

## Skill-whitelist

OpenClaw skal whiteliste de konkrete wrappers, ikke `python`, `bash` eller brede shell-kommandoer.

### `bredballeif-administrator`

Whitelist:

```text
/opt/bredballeif-ai-workspace/skills/bredballeif-boerneattest/bin/bredballeif-boerneattest.sh
```

Skill:

```text
/opt/bredballeif-ai-workspace/skills/bredballeif-boerneattest
```

### `bredballeif-padel-administrator`

Whitelist:

```text
/opt/bredballeif-ai-workspace/skills/bredballeif-padel-baner/bin/bredballeif-padel-baner.sh
/opt/bredballeif-ai-workspace/skills/bredballeif-padel-conventus/bin/bredballeif-padel-conventus.sh
/opt/bredballeif-ai-workspace/skills/bredballeif-padel-halbooking/bin/bredballeif-padel-halbooking.sh
/opt/bredballeif-ai-workspace/skills/bredballeif-padel-onboarding/bin/bredballeif-padel-onboarding.sh
```

Skills:

```text
/opt/bredballeif-ai-workspace/skills/bredballeif-padel-baner
/opt/bredballeif-ai-workspace/skills/bredballeif-padel-conventus
/opt/bredballeif-ai-workspace/skills/bredballeif-padel-halbooking
/opt/bredballeif-ai-workspace/skills/bredballeif-padel-onboarding
```

## Telegram routing

Telegram-bots skal routes til hver sin OpenClaw-agent:

- Bot `BIF Administrator` routes til agent `bredballeif-administrator`.
- Bot `BIF Padel Administrator` routes til agent `bredballeif-padel-administrator`.

Det betyder at den tværgående administrator kun får adgang til børneattest-skillen, mens padel-agenten
kun får adgang til padel-specifikke skills.

## Adgang

- Kun bestyrelsen i Bredballe IF har adgang til Telegram-botten `BIF Administrator`.
- Kun udvalget i afdelingen Padel i Bredballe IF har adgang til Telegram-botten
  `BIF Padel Administrator`.

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
