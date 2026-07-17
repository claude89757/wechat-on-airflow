# Airflow 3 Upgrade

The production metadata migration is a high-risk, irreversible-in-place
operation and requires explicit human approval.

## Rehearsal Gate

Before requesting approval:

1. Verify the encrypted PostgreSQL backup checksum and archive inventory.
2. Restore the entire archive into an isolated PostgreSQL 17 instance.
3. Record restore duration, database size, and free disk.
4. Run the pinned Airflow 3 database migration against the copy.
5. Start the target API Server, Scheduler, DAG Processor, Worker, and Triggerer.
6. Prove all active DAGs load with zero import errors.
7. Validate history, Variables, Connections, Pools, FAB users, and permissions
   without printing sensitive values.
8. Verify rollback by discarding the migrated copy and restoring the original
   backup into a new empty database.
9. Run no-delivery notification tests.
10. Require reliable production free space greater than the rehearsed peak
    database growth plus rollback headroom. A passing migration on a workstation
    does not waive this production storage gate.

The 2026-07-17 rehearsal completed all ten checks. See
[`../migration-rehearsal-2026-07-17.md`](../migration-rehearsal-2026-07-17.md)
for the measured evidence. Production approval remains blocked by storage and
external sender readiness prerequisites documented in that report.

### Large `task_instance` Tables

Airflow 3 adds a UUID primary key to `task_instance`. The official migration
updates rows in batches selected with `WHERE id IS NULL LIMIT batch_size`.
With the production baseline of roughly 12 million rows, the default small
batch repeatedly scans the table and makes migration time impractical.

`airflow-migrate` therefore sets
`AIRFLOW__DATABASE__MIGRATION_BATCH_SIZE` from
`AIRFLOW_MIGRATION_BATCH_SIZE`, currently `20000000`. This is an official
Airflow database setting and is intentionally limited to the one-shot
migration service. Before a future major migration, compare it with the live
`task_instance` count and rehearse again on a fresh restore.

Do not replace this setting with custom SQL or run concurrent migration
containers.

## Approval Request

Report the exact commit and image, expected downtime, measured rehearsal
duration, backup identifiers and verification, migration commands, health
checks, abort conditions, and restore-based rollback steps.

## Production Procedure

1. Pause new scheduling and wait for active tasks to finish.
2. Create and verify a final backup.
3. Stop Airflow application components while retaining PostgreSQL and Redis.
4. Deploy the exact approved commit and image.
5. Run `airflow db migrate` once from the maintenance service.
6. Run required FAB migration checks.
7. Start API Server, DAG Processor, Scheduler, Worker, and Triggerer.
8. Verify service health, configuration names, DAG registration, history, and
   zero import errors.
9. Resume schedules.
10. Observe at least three complete scheduling cycles and check for duplicate
    notifications.

On any critical failure, stop scheduling and restore the pre-upgrade database
using `rollback.md`.
