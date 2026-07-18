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
