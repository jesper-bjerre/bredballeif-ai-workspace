# bredballeif-ai-workspace

AI workspace til udvikling af agenter og skills til Bredballe Idrætsforening.

De primære BIF-skills bor nu i monorepoet under `skills/<navn>/`. Kør:

```powershell
pwsh scripts/sync_skills.ps1
```

for at oprette lokale discovery-links i `.github/skills/` og `.claude/skills/`.

Se [AGENTS.md](AGENTS.md) for arkitektur, workflow og sikkerhedsregler.
