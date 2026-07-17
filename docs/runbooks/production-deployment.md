# Production Deployment

This runbook covers reversible application deployment. The Airflow 2 to 3
metadata database migration is a separate, human-approved operation described
in `airflow-upgrade.md`.

## Preconditions

```bash
make verify
make test-dags
make deploy-check
make rollback-check
make production-health
```

The worktree must be clean, the exact commit must be pushed, CI must pass, an
encrypted verified backup must exist, and rollback inputs must be available.

## Deploy

1. Record the pre-deploy health JSON and current production commit.
2. Pull the exact pushed commit on the server.
3. Build the pinned image; never install dependencies during container startup.
4. Validate the resolved Compose configuration.
5. Apply only the services included in the approved change.
6. Run `make production-health`.
7. Compare DAG registration, import errors, outbox counts, and service health.
8. Observe at least the number of schedule cycles declared in
   `config/runtime-target.yaml`.
9. Record the deployed commit and verification evidence in the change record.

If a required check fails, stop and follow `rollback.md`.

## WeChat Sender

The sender is deployed independently, so it can be repaired without restarting
Airflow:

```bash
docker compose -f docker-compose.sender.yml config --quiet
docker compose -f docker-compose.sender.yml up -d --build
docker compose -f docker-compose.sender.yml ps
```

Use an untracked environment file for the device name and Appium endpoint.
Verify `GET /healthz` and `GET /readyz`; do not call the send endpoint as a
smoke test. Historical fallback records are not replayed automatically.
