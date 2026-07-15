# Bredballe IF Padel – HalBooking

Agent-neutral skill til Bredballe IF Padel-medlemsadministration i HalBooking.

## Test

```powershell
$env:PYTHONPATH = ".\scripts"
python -m agent search --name "Navn" --detail
python -m agent history --name "Navn"
python -m agent preflight --name "Navn"
```

Credentials læses fra miljøvariabler eller en lokal gitignored `.env`.
