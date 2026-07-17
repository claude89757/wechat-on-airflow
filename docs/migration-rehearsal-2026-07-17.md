# Airflow 3 Migration Rehearsal: 2026-07-17

## Result

The isolated Airflow 2.10.5 to Airflow 3.3.0 migration, target-service startup,
and restore-based rollback rehearsal passed. Production migration is **not yet
approved** because the production host fails the reliable-storage gate and the
external WeChat device path is not ready.

No production database was modified. No notification task was executed. The
temporary plaintext archive, rehearsal containers, networks, and volumes were
deleted after verification.

## Inputs

- encrypted PostgreSQL backup completed at `2026-07-16T15:48:54Z`
- encrypted size: `2,145,199,776` bytes
- SHA-256: `1f4b3bbac4750def97112d9a9adeb7f751dee7412d0cb79121bdd864eaafa622`
- archive inventory: 368 PostgreSQL custom-format entries from PostgreSQL 17.5
- target image: `wechat-on-airflow:3.3.0`
- rehearsed image ID:
  `sha256:428b4ab3e4999e09bfeab6544bcf5733d02e8b243d884d18909a786d44568d92`
- pinned Airflow base image:
  `apache/airflow:3.3.0-python3.12@sha256:b572e9241d7b09b295c9ea97adeb7b3dfc932e2fbcdebec59256dad69061bb29`
- PostgreSQL image:
  `postgres:17.5-bookworm@sha256:fbcea1bd13b6a882cd6caa6b58db3ae5c102efe50ec625b3e2a5cbc50db5bfe4`

The archive was decrypted only into a mode-700 directory outside the
repository, with the file mode set to 600. It was removed after both rehearsals.
No secret values, recipient addresses, endpoints, or payloads were printed.

## Restored Baseline

The first four-job restore completed in `3,013` seconds (50 minutes 13 seconds).

| Object | Rows |
| --- | ---: |
| `dag_run` | 2,906,329 |
| `task_instance` | 11,929,339 |
| `xcom` | 3,737,487 |
| `log` | 33,596,463 |
| `variable` | 31 |
| `connection` | 0 |
| `slot_pool` | 1 |
| `ab_user` | 1 |
| `ab_role` | 5 |

- source Airflow revision: `5f2621c13b39`
- restored database size: `24,987,520,147` bytes
- all 31 Variable names were inventoried without reading values

## Core And FAB Migration

The official `airflow db migrate` command ran once with
`AIRFLOW__DATABASE__MIGRATION_BATCH_SIZE=20000000`. The monitoring client was
interrupted once, but the migration container, PostgreSQL transaction, PID, and
advisory lock remained active. Monitoring resumed against the same process; the
migration was not restarted.

The core migration ran from `2026-07-16T21:26:16Z` until shortly before the
successful head check at `2026-07-17T00:55:51Z`, approximately 3 hours 29
minutes. Important measured stages were:

| Stage | Duration |
| --- | ---: |
| add and index UUIDs for 11,929,339 task instances | 2 h 43 min 40 s |
| convert 3,737,487 XCom values to JSONB | 18 min 57 s |
| backfill 2,906,329 DAG run `run_after` values | 16 min 5 s |
| FAB provider migration | 64.67 s |

Validation results:

- core revision: `d2f4e1b3c5a7`
- FAB revision: `02ca36b0235b`
- `airflow db check-migrations`: passed
- `airflow db check`: passed
- `task_instance.id`: PostgreSQL `uuid`, non-null, zero missing values
- business-table counts: unchanged
- `log`: three additional Airflow CLI audit rows (`cli_migratedb` and
  `cli_check`), and no business-event delta
- migrated database size: `34,329,939,091` bytes
- database growth: `9,342,418,944` bytes
- peak Docker volume usage observed: `43.87 GB`
- minimum workstation free space observed during migration: approximately
  `43 GB`

Temporary PostgreSQL role-level memory overrides used for the rehearsal were
reset and verified absent after migration.

## Target Topology

All database DAG records were paused before service startup. The restored
database contained 12 historical `running` task instances and one
`up_for_retry` task instance, so the rehearsal Worker listened only on an empty
`rehearsal-health` queue. The Scheduler's default queue was not consumed.

The following Airflow 3 services started successfully against the migrated
copy:

- API Server
- Scheduler
- DAG Processor
- Triggerer
- Celery Worker

The API health response reported healthy metadata database, Scheduler,
Triggerer, and DAG Processor components. The Worker returned Celery `pong`.
The DAG Processor registered exactly nine current DAGs with zero import errors.
One historical Appium watcher remained correctly marked stale. Redis contained
only Celery binding keys and no task messages.

## Restore-Based Rollback

The migrated database and volume were discarded. A second empty PostgreSQL
17.5 database was created and the same archive was restored with four jobs.

- restore duration: `3,031.49` seconds (50 minutes 31.49 seconds)
- restored revision: `5f2621c13b39`
- restored database size: `24,987,667,603` bytes
- all nine row counts in the baseline table matched exactly

The restored database, volume, network, and temporary plaintext archive were
then deleted and verified absent. The encrypted backup and its key remain
outside the repository.

## Final Local Candidate Images

After the rehearsal report and runtime checks were finalized, both images were
rebuilt from the current worktree and verified locally:

- Airflow: `sha256:7bd456ca1d78ef5883dbd7bfac547d370e8171a174119eca72b6f9ab05a5a461`
- WeChat sender:
  `sha256:6e78ffd5acd32b192fcf24a92ba7ed9f8c2e11d7ffd312ba120db3f90af6f4fd`

These are candidate artifacts, not production approval. The production change
record must bind rebuilt or transferred images to the exact pushed commit and
verify their IDs again on the production host.

## Production Gates

Production currently has a `42,475,056,275` byte metadata database and only
`16,659,836,928` bytes free on reliable storage. The secondary filesystem has
ext4 I/O errors and cannot be used. The rehearsal's database and volume growth,
scaled to the larger live database, means the current host cannot support both
migration work and restore headroom.

Do not request production migration approval until all of these conditions are
met:

1. Provide at least 80 GiB free on reliable production storage after the final
   backup, then rerun the read-only storage gate.
2. Create and verify a fresh encrypted production backup immediately before
   downtime.
3. Securely configure `VENUE_EMAIL_FROM_ADDRESS` and
   `VENUE_EMAIL_REPLY_TO` without printing their values.
4. Restore the external Appium/device path and make the managed sender
   `/readyz` check pass. The changed SSH host fingerprint must be verified by a
   human before storing it as `login_info.host_key_sha256` in
   `APPIUM_SERVER_LIST`.
5. Record the exact approved Git commit and final Airflow and sender image IDs.
6. Obtain explicit human approval for the production metadata migration.

After approval, use the procedure in
[`runbooks/airflow-upgrade.md`](runbooks/airflow-upgrade.md), abort on any failed
gate, and observe at least three complete scheduling cycles after resuming.
