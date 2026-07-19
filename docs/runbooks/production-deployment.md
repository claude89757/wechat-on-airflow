# Production Deployment

This runbook covers reversible application deployments after the Airflow 3
fresh start. The one-time Airflow 2 cutover is in `airflow-upgrade.md`.

## Preconditions

```bash
make verify
make deploy
make deploy-check
make rollback-check
make production-health
```

The pre-deploy health command may report known production issues, but its output
must be recorded and understood. The worktree must be clean, the exact commit
must be pushed, CI must pass, and rollback inputs must be available.

## Deploy

1. Record pre-deploy health, current commit, image ID, and configuration names.
2. Run the default read-only deployment preflight:

   ```bash
   make deploy DEPLOY_ARGS="--target-commit <full-sha>"
   ```

3. Apply the exact pushed commit:

   ```bash
   make deploy DEPLOY_ARGS="--apply --target-commit <full-sha>"
   ```

   The command builds a commit-tagged image, changes only Airflow application
   services, preserves each DAG's pause state, drains active tasks before
   replacing workers, and waits for service health checks. If startup fails it
   restores the previous commit, image configuration, and DAG pause state. It
   batches pause-state changes through the supported Airflow CLI and does not
   recreate PostgreSQL, Redis, or log volumes.
4. Run `make production-health`.
5. Compare the Execution API route probe, DAG source readability,
   registration, import errors, exact local/production commit match, outbox
   counts, and service health.
6. Observe the cycle count in `config/runtime-target.yaml`.
7. Record the deployed commit and evidence in the production baseline.

Application deployments must retain the configured Airflow 3 database, Redis,
and log volume names. They must never mount the preserved Airflow 2 paths.

## Cloudflare Tunnel

Production uses `airflow.claude89757.cc` through the host-managed
`cloudflared.service`. Container configuration must use:

```text
AIRFLOW_BASE_URL=https://airflow.claude89757.cc
AIRFLOW_EXECUTION_API_SERVER_URL=http://airflow-api-server:8080/execution/
```

Keep the public root and private `/execution/` routes paired. The API server
must run with proxy headers enabled and publish `127.0.0.1:8080:8080`; the
tunnel origin is `http://127.0.0.1:8080`. Tunnel credentials and the Cloudflare
account certificate stay outside the repository with root-only permissions.

After any ingress or Airflow base URL change, verify:

```bash
systemctl is-enabled cloudflared.service
systemctl is-active cloudflared.service
curl --fail https://airflow.claude89757.cc/api/v2/monitor/health
curl --fail https://airflow.claude89757.cc/
make production-health
```

The production health check also requires the private Execution API probe to
return its expected unauthenticated response and the active DAGs to complete
their declared successful run history.

## WeChat Sender

The sender is deployed independently, so it can be repaired without restarting
Airflow:

```bash
sudo scripts/install_wechat_sender.sh --target-commit <full-sha>
sudo scripts/install_wechat_sender.sh --apply --target-commit <full-sha>
systemctl is-enabled wechat-sender.service
systemctl is-active wechat-sender.service
```

Use root-owned `/etc/wechat-sender.env` with mode `600` for the device and the
loopback Appium endpoint. Apply mode deploys an exact commit, runs one
unprivileged worker, retries transient Git fetch failures, enables automatic
startup, and waits for `GET /readyz`. Also verify `GET /healthz`; do not call
the send endpoint as a smoke test. Historical fallback records are not replayed
automatically. Docker Compose is retained only as a development or
alternate-host runtime.

## Metadata Cleanup

Metadata cleanup is deployment maintenance, not an Airflow DAG. Its normal
agent check is read-only:

```bash
make db-cleanup-check
```

Do not schedule apply mode. After explicit human approval for a specific
cutoff, use:

```bash
PYTHONPATH=src .venv/bin/python scripts/airflow_db_cleanup.py \
  --apply --confirm-delete-before YYYY-MM-DD --format json
```

Apply mode requires a clean pushed commit, an exact production commit match,
and a verified encrypted database backup. It deletes records and cannot be
used as a smoke test.
