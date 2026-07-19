# Logging- og retentionpolitik

## Fundne log-/persistensflader

| Flade | Repoevidens | Risiko | Krav/status |
|---|---|---|---|
| CLI stdout/stderr | Mange `print`; tool-output går muligvis til OpenClaw/model/session | PERSONAL/SECRET i logs | Password/raw subprocess fjernet flere steder; samlet policy mangler |
| Audit-events | `scripts/gdpr_controls.py` | Lav hvis kun metadata | Event, status, count, role, correlation, timestamp; ingen payload |
| Playwright screenshots | `**/scripts/screenshots/`, gitignored | Kan vise fuld side/persondata/session | Default off via env; privat krypteret temp og automatisk sletning mangler ved opt-in |
| HalBooking discovery HTML | Ikke længere persisteret | Rå HTML kan have persondata/tokens | Dump er fjernet; fortsat regressionstest kræves |
| Fondsstore/run log | `data/bredballeif-fondsansoegning`, JSON/JSONL | INTERNAL/PERSONAL historik | Gitignored og privat; encryption/retention mangler |
| Midlertidig compare-fil | `NamedTemporaryFile`, unlink i finally | Komplet medlemsliste kortvarigt | Tempdisk kan være ukrypteret; compare bør redesignes lokalt/streaming |
| OpenClaw sessioner | Ikke i repo | Prompts/tool-output/persondata | **SKAL VERIFICERES ORGANISATORISK** |
| Reverse proxy/systemd/container | Ikke i repo | URL, Telegram-id, errors | **SKAL VERIFICERES ORGANISATORISK** |
| Telegram | Ekstern tjeneste | Beskeder/metadata | **SKAL VERIFICERES ORGANISATORISK** |
| LLM prompt/output | Providerconfig mangler | PERSONAL/tredjeland | Zero retention og EU-route før PERSONAL |
| Gmail | Message, labels, statusmail | PERSONAL og medlemsstatus | Mailbox retention og adgang fastsættes |
| CI | Ingen workflow tracket | Kan kopiere stdout/secrets | Ingen proddata/secrets; secret masking; kort artifactretention |
| Backups | Ikke i repo | Forlænger alle retentionperioder | Kryptering, restoreadgang og expiry mangler |

## Tilladt logformat

```json
{
  "event": "conventus.member.lookup",
  "status": "success",
  "recordCount": 1,
  "actorRole": "padel-admin",
  "correlationId": "...",
  "timestamp": "..."
}
```

Forbudt: prompts/svar med persondata, API-responser, mail/telefon/adresse/CPR, noter, passwords,
tokens, cookies, authorization headers, fulde URL'er med querysecret og member objects.

`redact_sensitive_data` maskerer feltnavne og almindelige fritekstmønstre. Redaction er defense in depth;
data må helst aldrig gives til loggeren. Navne og fritekstsensitive forhold kan ikke pålideligt findes
med regex.

## Foreslåede slettefrister til beslutning

Dette er forslag, ikke godkendte frister:

| Data | Foreslået maksimum | Beslutning/ejer |
|---|---:|---|
| Sikkerheds-/auditlog uden payload | 90 dage online + op til 12 måneder begrænset arkiv ved behov | Dataansvarlig/sikkerhedsejer |
| Applikations-/proxylog | 30 dage | Teknisk ejer |
| OpenClaw samtale/tool-output med PERSONAL | 0–7 dage; helst ingen persistens | Dataansvarlig |
| SENSITIVE tool-output | Ingen sessionpersistens | Dataansvarlig/DPIA |
| Screenshots/HTML/temp | Slet ved command completion; fejlmateriale maks. 24 timer efter godkendt incident | Teknisk ejer |
| LLM prompt/output | Zero retention kontraktuelt/teknisk | Leverandørejer |
| Telegram-beskeder | Kortest mulige; særskilt deletionprocedure | Telegram-/systemejer |
| Gmail-notifikationer/statusmail | Fastlægges efter medlemsadministrativt behov; labels er ikke sletning | Procesejer |
| Fondsprojekt/historik | Projekt-/regnskabs-/tilskudskrav fastlægges pr. kategori | Økonomi/fondsansvarlig |
| Backups | 30–90 dage med dokumenteret expiry og sletning fra rotation | Teknisk ejer |
| CI logs/artifacts | Logs 30 dage; artifacts 1–7 dage og uden persondata | Repoejer |

## Adgang, sletning og kontrol

Logs er read-only for sikkerhedsejer/teknisk drift, ikke almindelige Telegram-brugere eller modellen.
Auditlager skal være append-only, adgangslogget og korrelerbart uden payload. Kvartalsvis stikprøve
kontrollerer redaction og sletning. Backuprestore skal respektere sletteanmodninger via en dokumenteret
procedure, så data ikke genindføres permanent.

Ingen frist er gældende før dataansvarlig har godkendt den og teknisk ejer har dokumenteret konfiguration
og sletningstest.
