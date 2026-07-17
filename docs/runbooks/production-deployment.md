# Production Deployment

This runbook covers reversible application deployments after the Airflow 3
fresh start. The one-time Airflow 2 cutover is in `airflow-upgrade.md`.

## Preconditions

```bash
make verify
make deploy-check
make rollback-check
make production-health
```

The pre-deploy health command may report known production issues, but its output
must be recorded and understood. The worktree must be clean, the exact commit
must be pushed, CI must pass, and rollback inputs must be available.

## Deploy

1. Record pre-deploy health, current commit, image ID, and configuration names.
2. Pull the exact pushed commit on the server.
3. Load or build the image identified by that commit.
4. Validate Compose with the untracked production environment.
5. Apply only the services in the approved change.
6. Run `make production-health`.
7. Compare DAG registration, import errors, outbox counts, and service health.
8. Observe the cycle count in `config/runtime-target.yaml`.
9. Record the deployed commit and evidence in the production baseline.

Application deployments must retain the configured Airflow 3 database, Redis,
and log volume names. They must never mount the preserved Airflow 2 paths.

## WeChat Sender

The sender is deployed independently, so it can be repaired without restarting
Airflow:

```bash
docker compose -f docker-compose.sender.yml config --quiet
docker compose -f docker-compose.sender.yml up -d --build
docker compose -f docker-compose.sender.yml ps
```

Use an untracked environment file for the device and Appium endpoint. Verify
`GET /healthz` and `GET /readyz`; do not call the send endpoint as a smoke test.
Historical fallback records are not replayed automatically.
