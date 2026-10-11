# Bredballe IF Padel – Conventus

Agent-neutral skill til read-only opslag og statistik for Bredballe IF Padel-medlemmer i Conventus.

## Test

```powershell
$env:PYTHONPATH = ".\scripts"
python -m agent search --name "Jensen"
python -m agent list --group all
python -m agent stats
python -m agent budget-report --department Esport --year 2026
```

Credentials læses fra miljøvariabler eller en lokal gitignored `.env`.

Budgetrapporter kræver browsercredentials (`CONVENTUS_USERNAME`/`CONVENTUS_PASSWORD`) og
Playwright Chromium. Installer via workspace `.venv`:

```bash
python -m pip install -r skills/bredballeif-padel-conventus/requirements.txt
python -m playwright install chromium
```

Read-only wrapperen vælger selv workspace `.venv` uden aktivering. På OpenClaw kan den
tværgående administrator bruge `bredballeif-oekonomi`-wrapperen, som kun tillader budgetrapporter.
Se [OpenClaw-opsætning](../../docs/openclaw-setup.md) for import og smoke-test.
