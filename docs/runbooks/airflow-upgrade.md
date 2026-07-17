# Airflow 3 Fresh Start

Production moves from Airflow 2 to Airflow 3 with a new metadata database.
Historical DAG runs, task instances, XCom rows, logs, users, and rendered task
history are not migrated. The Airflow 2 database and encrypted backup remain
unchanged as rollback evidence.

## Configuration Scope

Immediately before cutover, export Variables, Connections, and Pools from the
running Airflow 2 system into a root-owned directory outside the repository.
Never print or commit the exported values.

`config/config-contracts.yaml` defines the Variable migration behavior:

- static configuration is preserved;
- venue deduplication and proxy caches use `fresh_start_policy: preserve`;
- email and WeChat fallback outboxes use `fresh_start_policy: reset`;
- contract defaults are created when the old system has no explicit value;
- undeclared legacy Variables are ignored;
- a missing required preserved Variable aborts the migration.

Resetting an outbox does not discard its evidence: the old database and
encrypted configuration backup retain it. Outboxes are never replayed.

## Preconditions

1. `make verify`, `make deploy-check`, and `make rollback-check` pass.
2. The exact commit and Airflow image are pushed or transferred and identified.
3. The encrypted Airflow 2 backup remains verified.
4. Root storage has at least the floor in `config/runtime-target.yaml`.
5. The old database, Redis, logs, `.env`, commit, and image are recorded.
6. Required external service checks are complete without sending test messages.

The isolated fresh-start procedure was verified on 2026-07-17; see
[`../fresh-start-rehearsal-2026-07-17.md`](../fresh-start-rehearsal-2026-07-17.md).

## Export From Airflow 2

Create a mode-700 cutover directory outside the repository. Use the Airflow 2
CLI to export `variables.raw.json`, `connections.json`, and `pools.json`.
Files must be mode 600 and removed from container temporary storage after
copying. Record names and counts only.

Add any required Variable that was previously hardcoded through a protected
operator input before the final export. Do not place its value in a command
transcript, Git, or a runbook.

## Prepare Airflow 3

1. Pause every Airflow 2 DAG and wait for running tasks to finish.
2. Stop the Airflow 2 application services.
3. Copy `.env` to a mode-600 `.env.airflow2` rollback file.
4. Stop and remove the old Compose containers without deleting bind-mounted
   data.
5. Deploy the exact Airflow 3 commit and image.
   The image must contain the active DAG files; do not add a host DAG bind
   mount as a cutover workaround.
6. Configure new, explicit volume names through
   `AIRFLOW_POSTGRESQL_VOLUME`, `AIRFLOW_REDIS_VOLUME`, and
   `AIRFLOW_LOGS_VOLUME`.
7. Set `AIRFLOW_DAGS_ARE_PAUSED_AT_CREATION=true`.
8. Generate Airflow 3 API, JWT, and Fernet secrets outside Git. Retain the old
   database credential so the Airflow 2 rollback remains immediately usable.
9. Set `AIRFLOW_EXECUTION_API_SERVER_URL` to the internal API Server URL,
   including the public `AIRFLOW_BASE_URL` path prefix before `/execution/`.
10. Validate the resolved Compose configuration and confirm that none of its
    mounts resolve to the preserved Airflow 2 database, Redis, or log paths.

Prepare the Variable import inside the pinned image:

```bash
docker compose run --rm --no-deps \
  -v "$cutover_dir:/cutover" \
  --entrypoint python airflow-cli \
  /opt/airflow/project/scripts/prepare_fresh_start_config.py \
  /cutover/variables.raw.json /cutover/variables.import.json
```

The report contains names and counts only. A nonzero result stops the cutover.

## Initialize And Import

1. Start the new PostgreSQL and Redis services.
2. Run the one-shot `airflow-migrate` service.
3. Run the one-shot `airflow-create-admin` service.
4. Import `variables.import.json`, Connections, and Pools.
5. Verify the imported Variable values without printing them:

```bash
docker compose run --rm \
  -v "$cutover_dir:/cutover:ro" \
  --entrypoint python airflow-cli \
  /opt/airflow/project/scripts/verify_fresh_start_config.py \
  /cutover/variables.import.json
```

6. Confirm both fallback outboxes are empty and continuity caches exist.
7. Start API Server, DAG Processor, Scheduler, Worker, Triggerer, and log cleaner.
8. Require a successful internal Execution API route probe, zero import
   errors, readable image-bundled DAG sources, and the exact active DAG set.

## Activate

Unpause active DAGs only after configuration and external-service checks pass.
Keep a component paused when its declared external prerequisite is not ready;
record the reason rather than weakening its contract.

Observe at least three complete scheduling cycles. Confirm successful venue and
proxy runs, independent email and WeChat behavior, stable outbox counts, no
duplicate notifications, and healthy service endpoints. Do not send a manual
real notification as a smoke test.

On a critical failure, stop scheduling and follow `rollback.md`.
