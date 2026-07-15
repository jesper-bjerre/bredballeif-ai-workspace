# padel-kontingent-beregner

OpenClaw-/agent-neutral skill til at beregne Bredballe IF Padels sæsonvægtede kontingenter.
Skillen skriver ikke til Conventus eller andre eksterne systemer.

Tiltænkt agent: `bredballeif-padel-administrator`.
Python-funktionen hedder `beregn_bif_padel_kontingent`.

## Regler

- Årskontingent: 1600 kr.
- Aktuel måned tæller som fuld måned.
- `padel_until_june` er kun tilgængelig januar-juni.
- `padel_rest_of_year` er tilgængelig hele året.
- Dato uden input beregnes i `Europe/Copenhagen`.

## Kald

```powershell
$env:PYTHONPATH = ".\scripts"
python -m agent beregn --date 2026-05-15 --include-debug
```

Windows wrapper:

```powershell
.\bin\padel-kontingent-beregner.ps1 beregn --date 2026-05-15
```

Linux/OpenClaw wrapper:

```bash
./bin/padel-kontingent-beregner.sh beregn --date 2026-05-15
```

## Eksempel-input

```json
{
  "date": "2026-05-15",
  "include_debug": true,
  "existing_products": [
    {
      "id": "optional-external-id",
      "key": "padel_until_june",
      "name": "Padel kontingent til og med 30. juni",
      "current_price_dkk": 500,
      "active": true
    },
    {
      "id": "optional-external-id",
      "key": "padel_rest_of_year",
      "name": "Padel kontingent resten af året",
      "current_price_dkk": 1350,
      "active": true
    }
  ]
}
```

## Eksempel-output

```json
{
  "success": true,
  "date": "2026-05-15",
  "timezone": "Europe/Copenhagen",
  "current_month": "may",
  "current_month_da": "maj",
  "annual_total_dkk": 1600,
  "products": [
    {
      "key": "padel_until_june",
      "name_da": "Padel kontingent til og med 30. juni",
      "available": true,
      "active_should_be": true,
      "price_dkk": 500,
      "valid_until": "2026-06-30"
    },
    {
      "key": "padel_rest_of_year",
      "name_da": "Padel kontingent resten af året",
      "available": true,
      "active_should_be": true,
      "price_dkk": 1350,
      "valid_until": "2026-12-31"
    }
  ],
  "diff": [],
  "warnings": [],
  "admin_summary_da": "Maj-kontingenterne er beregnet. Kontingent til og med 30. juni skal være 500 kr. Kontingent resten af året skal være 1.350 kr. Begge kontingenter må være aktive."
}
```

Det fulde output indeholder også `included_months` for hvert produkt.

## Tests

```powershell
cd skills\padel-kontingent-beregner
$env:PYTHONPATH = ".\scripts"
python -m unittest discover -s tests
```
