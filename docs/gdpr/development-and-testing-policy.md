# Udviklings- og testpolitik

## Codex og udviklere

- Codex må læse/ændre public-egnet kode, dokumentation og syntetiske fixtures.
- Codex må ikke få produktionscredentials, `.env`, `data/`, medlemsudtræk, mails, produktionslogs,
  screenshots eller backupindhold.
- Ingen Conventus-, HalBooking-, Gmail-, Telegram- eller LLM-produktionskald under udvikling.
- Fejl beskrives med exceptiontype, correlation ID og syntetisk reproduktion; ikke med rå payload.
- Hvis et secret findes, vises kun fil/linje og nøglekategori; credential roteres og historikken renses.

## Testlag

1. **Unit:** rene funktioner, fiktive id'er som `TEST-001`, `.invalid`-e-mails og mocks.
2. **Kontrakt:** gemt syntetisk XML/HTML med kun skemafelter; verificér field allowlist og parsing.
3. **Gateway-policy:** providerregion/fallback, SECRET/SENSITIVE, querylimit, approval og audit.
4. **Integration:** kun af autoriseret person mod produktion og kun allowlistede syntetiske testposter.
5. **Produktionsaccept:** ét/få konkrete records under tidsbegrænset, auditeret change.

Datatilsynet beskriver, at produktionsdata i test fortsat er personoplysninger og kræver behandlingsgrundlag,
dataminimering, sletning og passende kontroller; se
[vejledningen om testdata](https://datatilsynet.dk/regler-og-vejledning/behandlingssikkerhed/testdata-anvendelse-af-personoplysninger-ved-udvikling-og-test-af-it-systemer).

## Syntetiske fixtures

Tilladte værdier: `Test Person 001`, `synthetic@example.invalid`, `TEST-001`, `SYSTEMTEST`, fiktive
telefoner markeret som test og tokens som `synthetic-token` i unit tests. Brug aldrig realistiske CPR-numre,
rigtige adresser, medlemsnumre eller kopierede XML/HTML-responser.

## Conventus-produktionsintegrationstest

- Testscope ligger i privat deploymentconfig, ikke i repo, og valideres før hvert opslag.
- Testrecord har kendt id/præfiks/afdeling og må ikke ligne et reelt medlem.
- Read-only credential bruges til reads; writes kræver separat approval og rollbackplan.
- Formål, initiator, tidspunkt, records, resultat og oprydning registreres uden personindhold.
- Testdata slettes efter dokumenteret frist.

Kan testscope ikke håndhæves, må integrationstesten ikke automatiseres. En manuel accepttest kan kun
ske efter dataansvarliges konkrete beslutning.

## GitHub, PR og CI

- Issues, PR'er, kommentarer og artifacts må ikke indeholde persondata, logs eller screenshots.
- CI bruger kun syntetiske fixtures og har ingen produktionscredentials.
- PR kræver test, policy-manifestdækning, dependency review og secret scan (gitleaks eller tilsvarende).
- CI må ikke printe env, HTTP headers, providerpayload eller subprocess stdout.
- Artifacts er private, kortlivede og uden persondata; helst ingen artifacts for policytests.
- Branchebeskyttelse kræver mindst én reviewer for GDPR-/integrationændringer.

Repoet har pr. revision ingen trackede GitHub workflows. Secret scan og testworkflow er derfor et åbent
punkt, ikke en eksisterende kontrol.

## Fejlrapportering

Rapportér: version/commit, syntetisk input, action, exceptiontype, correlation ID, forventet/faktisk
kontrolresultat. Del aldrig prompt, modeloutput, member object, mailbody, URL med querysecret eller
screenshot fra produktion. Ved mistanke om brud aktiveres incidentprocedure og ingen yderligere kopier laves.
