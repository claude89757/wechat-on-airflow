# ADR 0001: Airflow 3 Production Runtime

- Status: Accepted
- Date: 2026-07-16

## Context

Production currently runs Bitnami Airflow 2.10.5 on Python 3.12 with
CeleryExecutor, PostgreSQL 17, and Redis. Airflow 2 reached end of life on
2026-04-22. The existing image installs a broad provider set and mutates the
container at startup.

Airflow 3 separates the API server from DAG processing and task execution,
restricts direct metadata database access from task code, moves common
operators to the Standard Provider, and replaces the Airflow 2 webserver/API
startup model.

## Decision

Use:

- Apache Airflow `3.3.0`
- official image base
  `apache/airflow:3.3.0-python3.12@sha256:b572e9241d7b09b295c9ea97adeb7b3dfc932e2fbcdebec59256dad69061bb29`
- a repository-owned, reproducible custom image
- CeleryExecutor for the first production migration
- PostgreSQL 17
- Redis as the Celery broker
- FAB Auth Manager to preserve production-grade username/password access
- explicit API Server, Scheduler, DAG Processor, Triggerer, and Worker services

Dependencies and providers will be pinned. Containers will not install packages
or run operating-system upgrades during startup.

## Why Celery Is Retained Initially

The current deployment and task history use CeleryExecutor. Changing both the
Airflow major version and execution model in one production migration would
make failures harder to isolate. Executor simplification can be evaluated in a
separate ADR after Airflow 3 is stable.

## Why FAB Auth Manager

Airflow documents Simple Auth Manager as intended for development and testing
unless access is protected externally. Production currently exposes the Airflow
HTTP port and already has FAB user data. FAB therefore provides the safer,
lower-surprise migration path.

## Consequences

- `airflow api-server` replaces `airflow webserver`.
- FAB provider migrations are part of the database rehearsal and production
  migration.
- PythonOperator imports move to `airflow.providers.standard`.
- DAG author interfaces move to `airflow.sdk`.
- task code must not open Airflow metadata database sessions.
- database maintenance moves to an explicit deployment-manager command.
- the migration service uses a rehearsed batch size above the current
  `task_instance` row count to avoid repeated full-table scans during the
  Airflow 3 UUID migration.
- the image becomes larger than a minimal LocalExecutor image, but the migration
  changes fewer production dimensions.

## References

- https://airflow.apache.org/docs/apache-airflow/stable/installation/upgrading_to_airflow3.html
- https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/index.html
- https://airflow.apache.org/docs/docker-stack/
- https://airflow.apache.org/docs/apache-airflow-providers-fab/stable/upgrading.html
