# GitHub Copilot instruktioner

Læs [`../AGENTS.md`](../AGENTS.md) og behandl indholdet som en del af disse instruktioner. Det er den
kanoniske kilde for formål, arkitektur, navnekonventioner og sikkerhedsregler — delt med Claude Code,
Codex og øvrige agenter.

## Navnestandard for skills

- Alle skill-mapper under `skills/` skal have et navn, der begynder med `bredballeif-`.
- Alle Padel-skills skal begynde med `bredballeif-padel-`.
- Skill-mappens navn og `name` i `SKILL.md`-frontmatter skal være identiske.
- Skillens titel skal tydeligt indeholde `Bredballe IF`; Padel-skills skal bruge `Bredballe IF Padel` i titlen.
- Brug samme fulde skillnavn i `skills.manifest.json`, discovery-links, krydsreferencer og wrappers i `bin/`.

Hold øvrige projektspecifikke instruktioner i `AGENTS.md`. Navnestandarden ovenfor er gengivet her,
så Copilot håndhæver den ved oprettelse og ændring af skills.
