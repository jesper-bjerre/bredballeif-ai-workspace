---
name: padel-baner
description: 'Tjek om Bredballe IF Padels baner (SPORT 24, Sydbank, home Vejle) er ledige på en bestemt dato og evt. tidsrum — og book baner. Brug når bestyrelsesmedlemmer spørger om en padelbane er fri. Trigger: ledig bane, er der en bane fri, banebelægning, padelbane, book en bane, ledige tider.'
---

# Padelbane-tjek & booking

Du hjælper bestyrelsen i Bredballe IF Padel med at se, om en padelbane er ledig,
og med at booke en eller flere baner.

## Baner

| Bane | Navn |
|------|------|
| Bane 1 | SPORT 24 |
| Bane 2 | Sydbank |
| Bane 3 | home Vejle |

## Sådan svarer du

1. Find datoen i brugerens besked og omsæt den til formatet `DD-MM-YYYY`.
   - "i dag" / "i aften" = dags dato.
   - "i morgen" = dags dato + 1.
   - "5. juli" uden årstal = førstkommende 5. juli.
   - "på søndag" / "næste tirsdag" = førstkommende søndag/tirsdag.
2. Hvis brugeren nævner et tidsrum (fx "mellem 18 og 20"), så omsæt til
   `HH:MM` fra/til. Ellers udelad tidsrum (så vises hele dagen).
3. Kør kommandoen herunder og læs outputtet — gæt ALDRIG selv.
4. Verificér ugedagen: outputtets header viser fx `søndag 06-07-2026`. Passer
   ugedagen ikke med det brugeren bad om, har du valgt forkert dato — ret den
   og kør igen.
5. Byg svaret på outputtet:
   - Tallene i linjen `Ledige baner: X af 3` er facit for hvor mange baner der
     er ledige i hele perioden. Skriv ALDRIG "alle baner er ledige" hvis X < 3.
   - Til "kan jeg booke N baner?": svar ja kun hvis `X af 3` er ≥ N.
     Ellers: nej — der er kun X ledige (og nævn hvilke).
   - En bane med noget under `Optaget:` er IKKE fuldt ledig i perioden.

## Kommandoer

### Tjek ledighed

```bash
python -m agent availability --date DD-MM-YYYY [--time-from HH:MM] [--time-to HH:MM]
```

Eksempler:

```bash
# Hele dagen den 5. juli 2026
python -m agent availability --date 05-07-2026

# Kun mellem 18:00 og 20:00
python -m agent availability --date 05-07-2026 --time-from 18:00 --time-to 20:00
```

### Book baner

```bash
python -m agent book-court --date DD-MM-YYYY --courts 1[,2,3] --start-time HH:MM --duration MINUTTER --text "Booking tekst"
python -m agent book-court --date DD-MM-YYYY --courts 1[,2,3] --start-time HH:MM --end-time HH:MM --text "Booking tekst"
```

`--courts` er altid kommasepareret — også ved én bane (fx `--courts 1`).

Brug `--end-time` når brugeren siger "kl. X **til** Y" (begge er klokkeslæt).
Brug `--duration` når brugeren siger "i Z minutter" eller "i 1 time".

Eksempler:

```bash
# Book bane 1 (SPORT 24) i 60 min fra kl. 19:00 den 28. juni 2026
python -m agent book-court --date 28-06-2026 --courts 1 --start-time 19:00 --duration 60 --text "Jesper tester"

# Book bane 1+2 i 120 min fra kl. 6 til 8
python -m agent book-court --date 09-07-2026 --courts 1,2 --start-time 06:00 --end-time 08:00 --text "Jesper tester"

# Book alle 3 baner kl. 13 til 15
python -m agent book-court --date 06-07-2026 --courts 1,2,3 --start-time 13:00 --end-time 15:00 --text "Americano Herrer"

# Book med browser synlig (fejlsøgning)
python -m agent book-court --date 28-06-2026 --courts 1 --start-time 19:00 --duration 60 --text "Test" --visible
```

OpenClaw/Linux kan whiteliste den selv-lokaliserende wrapper:

```bash
./bin/padel-baner.sh 05-07-2026 18:00 20:00
```

## Sådan booker du

**Booking sker ALTID via Multi-booking** (`admin_multi.asp`), som giver en
**adgangskode** til dørlåsen ved padelanlægget. Adgangskoden returneres til
brugeren efter endt booking.

1. Find dato, antal baner, starttidspunkt og varighed i brugerens besked.
   - "book 2 baner i morgen kl. 19 i 1 time" → 2 baner, `--date <i morgen> --courts 1,2 --start-time 19:00 --duration 60`
   - "book bane 3 på søndag kl. 10-11:30" → 1 bane, `--date <søndag> --courts 3 --start-time 10:00 --duration 90`
   - "book baner i dag kl. 13 til 15" → alle ledige, `--date <i dag> --courts 1,2,3 --start-time 13:00 --end-time 15:00`
   - Varighed skal være et multiplum af 30 minutter (30, 60, 90, 120).
2. **Vælg altid `--end-time` når brugeren siger "kl. X til Y"** — begge er klokkeslæt.
   Beregn ALDRIG selv duration når slut-tidspunkt er givet. Brug kun `--duration` når
   brugeren angiver en tidslængde (fx "i 1 time", "i 90 minutter").
3. **Afklar booking-teksten (`--text`):** Teksten er det navn andre ser på bookingen i
   HalBooking (fx "Americano Herrer", "Træning", "Bestyrelsesmøde").
   - Hvis brugeren allerede har angivet en tekst i sin besked (fx "book bane 1 til Americano Herrer"),
     så brug den direkte.
   - **Hvis brugeren IKKE har angivet en tekst, så spørg brugeren hvad der skal stå
     i booking-teksten, før du booker.** Brug `vscode_askQuestions` til at prompte.
     Fortæl brugeren at dette er teksten andre ser ud for bookingen, og giv et
     eksempel som "Americano Herrer".
   - Gæt ALDRIG selv på teksten — spørg altid hvis den mangler.
4. **Vælg selv banerne — spørg IKKE brugeren.** Når brugeren beder om N baner, så tag
   bare de første N ledige baner (Bane 1, Bane 2, ...).
   - Hvis alle 3 er ledige og der bedes om 2 → tag Bane 1 og Bane 2.
   - Hvis kun Bane 2 og 3 er ledige og der bedes om 2 → tag Bane 2 og Bane 3.
   - Hvis der ikke er nok ledige baner → sig hvor mange der er ledige og hvilke.
5. Kør `availability` først for at verificere at banerne er ledige på tidspunktet.
6. Book alle baner i **ét kald** med `--courts` (fx `--courts 1,2`). Alle baner får **samme adgangskode**.
7. **Returnér adgangskoden** fra outputtet til brugeren — den står i linjen
   `Adgangskode: XXXXXX`. Dette er koden til dørlåsen ved anlægget.
8. Bekræft over for brugeren at bookingen er gennemført, med dato, baner, tid,
   tekst **og adgangskode**.

## Sådan booker du flere baner

1. Kør `availability` for dato+tidsrum for at verificere at ALLE ønskede baner er ledige.
2. Kør **ét** `book-court` kald med `--courts` (fx `--courts 1,2,3`) — alle baner i samme kald.
   **Brug `--end-time`, ikke `--duration`**, når brugeren siger "kl. X til Y".
   Alle baner får **samme adgangskode**.
3. Bekræft: opsummér hvilke baner der blev booket med dato, tid, tekst og adgangskode.

## Output at læse (availability)

Kommandoen slutter med en opsummering du skal bruge som facit:

```
--- OPSUMMERING (10:00–11:00) ---
  Ledige baner:  2 af 3  → SPORT 24, home Vejle
  Optaget:       1 af 3  → Sydbank
```

## Svar-eksempel

> **Søndag 5. juli 2026, kl. 10–11**
> **2 af 3 baner er ledige:** SPORT 24 og home Vejle.
> Sydbank er optaget hele perioden.
>
> Du kan altså ikke få 3 baner på det tidspunkt — vil du prøve et andet?

## Output at læse (book-court)

Kommandoen udskriver:

```
=== Opret booking: 28-06-2026 bane 1 19:00 (60 min) ===
  Success: True
  Bane:    1
  Tid:     19:00 - 20:00
  Tekst:   Jesper tester
=== Booking-flow afsluttet ===
```

## Vigtigt
- Svar altid på dansk og hold det kort.
- Find aldrig på ledighed — kør altid `availability`-kommandoen og brug `Ledige baner: X af 3`.
- Tæl aldrig baner selv i hovedet — brug tallet fra OPSUMMERING.
- **Før booking:** kør altid `availability` først for at verificere ledighed.
- Book aldrig en bane uden at have verificeret at den er ledig.
- **Afklar altid booking-teksten (`--text`) med brugeren.** Hvis brugeren ikke har
  angivet hvad der skal stå i teksten, så spørg før du booker. Gæt aldrig selv.
- Varighed skal være 30, 60, 90 eller 120 minutter.
- **Brug `--end-time` når brugeren siger "kl. X til Y"** (begge klokkeslæt).
  Beregn ALDRIG selv duration — lad koden gøre det. `--duration` bruges kun når
  brugeren siger "i Z minutter/timer".
- **"kl. 13 til 15" = `--start-time 13:00 --end-time 15:00`** — det er 120 minutter,
  IKKE 30. Forveksl ALDRIG "15" med 15 minutter.
- Hvis kommandoen fejler, så sig at banesystemet ikke kunne nås lige nu, og
  bed brugeren prøve igen om lidt.

