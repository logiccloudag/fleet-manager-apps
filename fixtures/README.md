# Live-suite fixture

This branch is the fixture of the WFM live suites (FM-1839). It is not catalog content.
It holds Margo rc3 ApplicationDescriptions:

- `live-fixture-a` 1.0.0, 1.1.0, 1.2.0: a helm profile (`kubernetes`) and two compose profiles (`compose`, `compose-modular`).
- `live-fixture-a` 2.0.0: one compose profile (`compose-solo`), so it drops the tracks of the older versions.
- `live-fixture-b` 1.0.0: a helm profile only.

The live suites in `apps/api-integration-tests` register it as a Git registry in their sandbox organization.
