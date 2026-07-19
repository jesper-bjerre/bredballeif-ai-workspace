# LLM-providerpolitik

## Bindende teknisk regel

Provider, model og **hele fallbackkæden** valideres før første modelkald. Ukendt provider/region,
manglende DPA-status eller manglende zero-retention-evidens giver fail-closed:

> Den godkendte EU-model er ikke tilgængelig. Opgaven blev ikke sendt til en alternativ provider.

Ingen model, alias, agent-, skill- eller environment-override må omgå policyen. Retry må kun ske til
samme godkendte EU-konfiguration eller en på forhånd godkendt EU-fallback.

## Status pr. providerkategori

| Provider | Tilladt brug | Krav | Repo-status |
|---|---|---|---|
| Codex/OpenAI | Kode, dokumentation, PUBLIC og syntetiske data | Ingen produktionscredentials/-logs/-medlemsdata | Brug oplyst; runtime-DPA/region ikke relevant for prod i dette design |
| TensorX | Nødvendige almindelige personoplysninger | Foreningsejet konto, DPA, EU-inference, zero retention, træningsfravalg, underdatabehandlere, endpoint-lock | Ønsket; **SKAL VERIFICERES ORGANISATORISK** |
| Lokal model/kode | INTERNAL/PERSONAL og foretrukket SENSITIVE deterministik | Isoleret VPS, ingen ekstern telemetry, patching og adgangskontrol | Ikke dokumenteret |
| DeepSeek direkte/officiel API | Kun PUBLIC eller reelt anonymt | Særskilt godkendelse; aldrig samtalekontekst med INTERNAL/PERSONAL | Ikke fundet i repo; skal være blokeret for medlemsflows |
| Kimi direkte/officiel API | Kun PUBLIC eller reelt anonymt | Samme som DeepSeek | Ikke fundet i repo; skal være blokeret for medlemsflows |
| OpenAI/Anthropic runtime | Kun efter konkret godkendelse og region-/DPA-vurdering; aldrig automatisk fallback for PERSONAL | Commercial DPA, behandlingslokation, retention/træning, underdatabehandlere og overførsel | Ingen runtimekonfiguration fundet |
| Routere/ukendt provider | Blokeret | Identificer slutprovider og region deterministisk | Ingen router må anvendes før godkendelse |

## Obligatorisk registry-indhold

For hver provider/model: entydigt alias, juridisk leverandør, base URL, model-id, inferencelande,
support-/abuse-adgang, retention, træningsbrug, DPA-version, underdatabehandlere, overførselsgrundlag,
godkendelsesdato/ejer og udløbs-/reviewdato. Secrets lagres separat og må ikke indgå i registryet.

## Provider-lock

- PERSONAL: `allowed_regions = [EU, EEA]`, `allow_non_eu_fallback = false`.
- SENSITIVE og SECRET: ingen ekstern route.
- PUBLIC: ikke-EU kan kun aktiveres pr. eksplicit PUBLIC-job; aldrig som global fallback.
- INTERNAL: EU som default; særskilt beslutning for ikke-EU.
- Alias skal resolve til samme registrerede provider og region ved start og før retry.
- Providerændringer eller nye underdatabehandlere stopper PERSONAL-trafik, indtil review er godkendt.

## Evidens og test

`validate_provider_route` i `scripts/gdpr_controls.py` afviser ukendt, ikke-godkendt eller ikke-tilladt
region, kræver EU/EØS for PERSONAL og afviser ikke-EU-fallback. PUBLIC kan kun bruge en ikke-EU
primær provider, når den konkrete invocation er PUBLIC og regionen står eksplicit i dens policy.
Testene bruger kun fiktive providernavne/metadata. Der er ingen netværksklient eller TensorX-aktivering.

Repoet mangler den faktiske OpenClaw-route. Før godkendelse skal ejer fremlægge en redigeret configdump
med primary, model, region, fallbacks, retry, aliases og overrides samt en kontrolleret failover-test.

Datatilsynet understreger, at den dataansvarlige skal kende underdatabehandlere og behandlingslokation i
leverandørkæden; se [udtalelsen om tredjelandsoverførsler](https://www.datatilsynet.dk/afgoerelser/afgoerelser/2026/jan/vilkaar-i-databehandleraftalen-om-overfoersler-af-personoplysninger-til-tredjelande).
