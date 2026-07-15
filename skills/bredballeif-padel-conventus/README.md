# Bredballe IF Padel – Conventus

Agent-neutral skill til read-only opslag og statistik for Bredballe IF Padel-medlemmer i Conventus.

## Test

```powershell
$env:PYTHONPATH = ".\scripts"
python -m agent search --name "Jensen"
python -m agent list --group all
python -m agent stats
```

Credentials læses fra miljøvariabler eller en lokal gitignored `.env`.
