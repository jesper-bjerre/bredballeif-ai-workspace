# Behandling i Conventus

## Miljømodel

Opgaven oplyser, at Conventus kun har én produktionsinstans. Repoet indeholder tre XML API-endpoints
til adressebog/grupper/afdelinger og Playwright-automation til login, økonomirapport og gruppeoprettelse.
Denne revision foretog ingen kald og læste ingen credentials.

Udvikling foregår altid med syntetiske fixtures og mocks. Integrationstest mod Conventus er en
særskilt, autoriseret produktionsbehandling og må ikke udføres af Codex. Et testscope skal mindst have:

```yaml
test_scope:
  allowed_member_ids: ["TEST-001", "TEST-002"]
  allowed_departments: ["SYSTEMTEST"]
  expires_at: "<kort tidsvindue>"
  read_only: true
```

`TestScope` i `scripts/gdpr_controls.py` fejler lukket for id/afdeling uden for allowlisten. Der er
ingen dokumenterede Conventus-testposter i repoet; etablering og oprydning er et P0 organisatorisk punkt.

## Faktisk API-adfærd

`bredballeif-padel-conventus/scripts/agent.py` bygger en GET-URL med forenings-id, API-key og gruppe-id
og parser hele medlemsposter, herunder adresse, kommune, telefon, e-mail og fødselsdato. Dette er ikke
en generisk rå HTTP-wrapper, men endpointet er stadig bredt. Search filtrerer først efter fuldt udtræk.

Implementeret forbedring:

- søgestreng skal være mindst tre tegn og må ikke være `all`, `alle`, `*` eller tom
- search-output bruger feltallowlist og højst 10 matches
- list bruger standard 10; større output kræver bulk-flag **og** gatewayapproval
- fejl viser kun exceptiontype, ikke URL/query med API-key
- gruppeoprettelser kræver `conventus.create-group` approval og audit-event

Resterende risiko: Conventus afleverer stadig hele objektet til lokal memory. Hvis API'et ikke kan
begrænse felter/resultater server-side, skal gatewayen straks projektere til toolkontrakten og droppe
råobjektet før modelkontekst/log.

## Påkrævede domænetools

| Tool | Input | Output | Max | Rolle | Read/write | Approval/audit |
|---|---|---|---:|---|---|---|
| `find_member` | navn ≥3, afdeling/gruppe | `member_id`, nødvendigt navn, match count | 10 | Afdelingsadmin | Read | Audit lookup; bulk forbudt |
| `get_membership_status` | eksakt member_id | aktiv/inaktiv, gruppe, periode | 1 | Afdelingsadmin i scope | Read | Audit status |
| `get_payment_status` | eksakt member_id/formål | status, ikke fuld økonomihistorik | 1 | Autoriseret økonomi/padel | Read | Audit status |
| `aggregate_members` | afdeling/periode | counts, aldrig personliste | Lokal | Afdelingsadmin | Read | Audit count |
| `update_member_email` | member_id, valideret ny e-mail | status + maskeret mål | 1 | Padel-admin | Write | 15-min approval + before/after metadata |
| `create_activity_registration` | aktivitet, dato, kapacitet, pris | group id/status | 1 | Padel-admin | Write/publicering | approval + audit |

Hvert tool skal deklarere dataklasse, allowed regions, field allowlist, rolle, max records, writeflag og
approval-event. TensorX får kun toolresultatet efter lokal filtrering; aldrig credentials, fri URL,
headers eller direkte adgang.

## Dataminimering før model

Foretrukket mønster:

1. Agenten vælger tool og valideret input.
2. Gatewayen kalder Conventus.
3. Lokal kode afgør status eller aggregerer.
4. Modellen får kun fx `{membershipStatus: "active", department: "Padel"}`.
5. Navn, beløb, mail eller medlemsnummer indsættes lokalt i en allerede genereret skabelon, hvis muligt.

Børneattestdata sendes ikke til ekstern model. Økonomirapporter skal fjernes for personnavne,
bilags-/posteringstekster og øvrige identifikatorer før analyse.

## Write approval

```text
AI foreslår handling + konsekvens + antal
  -> autoriseret bruger godkender
  -> gateway opretter kort approval-kontekst
  -> wrapper udfører eksakt action
  -> audit-event uden payload
```

Konteksten indeholder godkendte actions, actor role, correlation ID, expiry ≤15 minutter og granted.
Modellen må ikke kunne sætte disse env-felter. Statiske `--confirm`-flags er ikke menneskelig approval.

## Accepttest

Hvis testposter ikke kan oprettes, kan et rigtigt medlem kun bruges efter dokumenteret formål,
navngiven autoriseret initiator, ét/få id'er, kort tidsvindue, read-only hvor muligt, approval for writes,
redigerede logs og audit. Output må ikke kopieres til Codex, GitHub issue/PR eller screenshots.

Manglende testafgrænsning i Conventus er en resterende høj risiko og kan blokere skriverettigheder.
