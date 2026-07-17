# ADR 0004: Fresh Airflow 3 Metadata Database

- Status: Accepted
- Date: 2026-07-17

## Context

The Airflow 2 metadata database is approximately 42 GB and contains millions of
historical DAG runs and task instances. Migrating it provides no business value
for venue polling, while requiring substantial storage, downtime, and rollback
complexity. Runtime configuration and notification continuity are required.

## Decision

Airflow 3 starts with new, explicitly named PostgreSQL, Redis, and log volumes. Historical Airflow 2
metadata is not migrated. The old database, logs, environment file, commit, and
encrypted backup remain available for rollback.

The cutover migrates:

- contract-declared static Variables;
- venue-specific recipients and external-service credentials;
- venue deduplication caches to prevent duplicate notifications;
- proxy caches to reduce startup disruption;
- Connections and Pools;
- administrator settings through the untracked container environment.

Email and WeChat fallback outboxes are reset in Airflow 3 and retained only in
the preserved Airflow 2 evidence. They are not replayed. DAGs are initially
paused and activated only after configuration verification.

## Consequences

- Airflow 3 has no historical run, task, XCom, rendered template, or audit data.
- The 42 GB database rewrite and in-place schema downgrade risk are removed.
- Rollback switches commits, environment files, and storage ownership instead of
  restoring a migrated database.
- Deduplication behavior remains continuous across the cutover.
- Configuration migration becomes an explicit, tested release artifact.
