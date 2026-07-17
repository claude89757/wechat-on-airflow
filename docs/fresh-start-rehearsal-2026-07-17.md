# Airflow 3 Fresh-start Rehearsal: 2026-07-17

## Result

The Airflow 3 fresh metadata database and configuration migration rehearsal
passed without calling a booking, email, WeChat, GitHub, Appium, SSH, or ADB
endpoint.

The isolated rehearsal verified:

- pullable PostgreSQL and Redis registry manifest digests;
- independent named PostgreSQL, Redis, and log volumes;
- Airflow 3.3.0 and FAB schema initialization on an empty PostgreSQL 17 database;
- explicit FAB administrator creation;
- preparation of all 33 contract-declared Variables;
- preservation of 26 exported configuration or continuity values;
- creation of five contract defaults;
- reset of two fallback outboxes without replay;
- import and value-level verification of 33 out of 33 Variables;
- zero Airflow DAG import errors.

The verification output contained configuration names and counts only. The
dummy values, temporary containers, networks, and named volumes were removed
after the rehearsal.

## Findings Resolved

The first Compose check found that the previous PostgreSQL and Redis SHA values
were host-local image configuration IDs, not pullable registry manifest
digests. The references were replaced with the exact `RepoDigests` observed on
production and then pulled successfully in a clean local environment.

A host bind-mount rehearsal also exposed platform-specific ownership behavior.
The Airflow 3 runtime now uses explicit named volumes instead. This prevents
accidental reuse of the preserved Airflow 2 bind-mounted data and delegates
container storage ownership to Docker.

## Production Implications

Production must use the exact pushed image and explicit volume names from its
untracked environment. The final configuration export must replace the
rehearsal's dummy values, pass the same preparation and verification commands,
and start all DAGs paused. No historical Airflow metadata or fallback outbox is
imported.
