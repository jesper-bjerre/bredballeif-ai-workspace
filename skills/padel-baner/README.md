# bredballeif-skill-padel-baner

Agent-neutral skill til read-only tjek af Bredballe IF Padels baner i HalBooking.

## Test

```powershell
$env:PYTHONPATH = ".\scripts"
python -m agent availability --date 05-07-2026 --time-from 18:00 --time-to 20:00
```

Windows wrapper:

```powershell
.\bin\padel-baner.ps1 05-07-2026 18:00 20:00
```

Linux/OpenClaw wrapper:

```bash
./bin/padel-baner.sh 05-07-2026 18:00 20:00
```

Credentials læses fra miljøvariabler eller en lokal gitignored `.env`.
