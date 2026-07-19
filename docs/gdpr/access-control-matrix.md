# Adgangskontrolmatrix

Rollerne er målarkitektur. Repoet dokumenterer kun to Telegram-agentgrupper; brugeridentiteter, RBAC,
MFA, servicekonti, SSH og CI-adgang er ikke tracket og skal verificeres i deploymentet.

| Rolle | Skills/systemer | Medlemsstatus | E-mail/telefon | Write/send/publicér | Masseudtræk | SENSITIVE | SECRET/admin |
|---|---|---|---|---|---|---|---|
| Padel-administrator | Padel skills; Conventus/HalBooking | Ja, kun Padel og behov | Begrænset ved konkret onboarding | Kun scoped 15-min approval | Nej; særskilt bulk-role | Nej | Ingen secretvisning; ingen serveradmin |
| Bestyrelsesadministrator | Børneattest/vedtægter og godkendte tværgående tools | Ved dokumenteret behov | Kun relevant proces | Approval efter mandat | Særskilt godkendelse | Lokal atteststatus ved særskilt rolle | Ingen runtimecredentials |
| Børneattest-ansvarlig | `bredballeif-boerneattest`, Conventus lokal behandling | Kun relevante frivillige | Som udgangspunkt nej | Ingen Conventus-write fra skill | Kun årsrapport med bulk approval | Ja, need-to-know/local-only | Ingen LLM/provideradmin |
| Økonomi-/fondsansvarlig | økonomi/fonde | Normalt nej | Projektkontakt ved behov | Lokal historik; ekstern indsendelse manuelt godkendt | Max 10 ansøgninger; ikke medlemsliste | Nej som standard | Fundraising credential skjult |
| Teknisk drift | Hostinger/OpenClaw/logs/deploy | Ikke indholdsmæssigt behov | Nej | Deployment efter change approval | Nej | Nej | Secret store/SSH efter least privilege + MFA |
| OpenClaw agent | Kun whitelisted domænetools | Minimeret toolresultat | Kun hvis nødvendigt | Foreslår; kan kun udføre med gatewayapproval | Max 10; ingen bulk default | Ingen ekstern model | Ingen env/shell/raw HTTP |
| TensorX EU | Modelinference | Kun minimeret kontekst | Kun hvis uundgåeligt og godkendt | Ingen tools/systemadgang | Aldrig komplet liste | Nej | Nej |
| Codex | Repo, kode, syntetiske tests | Nej | Nej | Kun repoændringer; ingen prod/deploy | Nej | Nej | Ingen prodcredentials/logs |
| CI servicekonto | Test/scan af repo | Nej | Nej | Build/test; ingen prod | Nej | Nej | Kun kortlivede repo-scoped tokens |
| Conventus/HalBooking/Gmail servicekonti | Ét konkret integrationformål | Efter scope | Efter scope | Separate read/write identities | Bulk kun særskilt identity | Børneattest kun read identity | Credentials i secret store |

## Rettighedsmatrix pr. risikofyldt tool

| Tool/action | Padel-admin | Bestyrelse | Børneattestansvarlig | OpenClaw | Approval |
|---|---:|---:|---:|---:|---|
| Conventus `search` | Padel scope | Ved behov | Relevante frivillige | Ja, max 10 | Ikke ved enkelt read |
| Conventus `list`/bulk | Nej default | Nej default | Årsformål | Nej default | `*.bulk-read` særskilt |
| Børneattest status | Nej | Begrænset | Ja, lokal | Ikke til ekstern LLM | `boerneattest.sensitive-read` |
| HalBooking `create/onboard` | Ja | Nej | Nej | Kun efter gateway | `halbooking.member.create` / `onboarding.onboard` |
| Gmail `process-emails` | Ja som kontrolleret batch | Nej | Nej | Kun efter gateway | process + onboard actions, max 10 |
| Conventus `create-group` | Ja | Efter mandat | Nej | Kun efter gateway | `conventus.create-group` |
| Banebooking | Ja | Efter lokal regel | Nej | Kun særskilt admin-wrapper efter gateway | `halbooking.court.book` |
| Fonds ekstern indsendelse | Manuel autoriseret rolle | Efter mandat | Nej | CLI indsender ikke | Navngiven slutversion |

## Håndhævelseskrav

- Telegram user-id allowlist, ikke kun gruppenavn; default deny og hurtig offboarding.
- MFA hvor platformen understøtter det; bot token/gruppeinvitation er ikke tilstrækkelig identitet alene.
- Separate OpenClaw-agenter, servicekonti og credentials pr. rolle/read-write.
- Bevar separate read- og admin-entrypoints; whitelist admin-wrapper kun for rollen og med separat servicekonto.
- Modellen har ingen generisk shell, Python, HTTP, fil- eller env-adgang.
- Approvalmetadata injiceres af gatewayen og kan ikke angives af Telegramtekst/toolinput.
- Kvartalsvis access review og straks-offboarding ved rolleophør.
