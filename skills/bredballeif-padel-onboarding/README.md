# Bredballe IF Padel – onboarding

Agent-neutral skill til fuld onboarding af Bredballe IF Padel-medlemmer på tværs af Conventus, HalBooking og Gmail.

## Test

```powershell
$env:PYTHONPATH = ".\scripts"
python -m agent preflight --name "Navn"
python -m agent onboard --name "Navn" --type prime --end-date 31-12-2026
python -m agent process-emails
```

Credentials læses fra miljøvariabler eller en lokal gitignored `.env`.
