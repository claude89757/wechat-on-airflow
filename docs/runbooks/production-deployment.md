# Production Deployment

This runbook covers reversible application deployments after the Airflow 3
fresh start. The one-time Airflow 2 cutover is in `airflow-upgrade.md`.

## Preconditions

The exact release commit must be on protected `main` with a successful GitHub
`CI / verify` check. Dispatch `production-release.yml` in `preflight` mode and
record any known production issue before apply. Application rollback requires a
previous pushed release commit and valid Compose configuration; it does not
require a database backup because application deployment preserves all data
volumes.

The GitHub UI is the authoritative entry point. `make deploy`,
`make webapp-deploy`, `make sender-deploy`, and component health targets are
optional `gh` dispatchers. They use only GitHub workstation authentication and
never connect with workstation-held production credentials.

## Deploy

1. Record pre-deploy component health and the current release identities.
2. Dispatch `production-release.yml` with `mode=preflight`, the full target SHA,
   and the intended sender selection.
3. After preflight succeeds, dispatch the same SHA with `mode=apply`.
4. The release first applies D1 migrations and the Worker, then Airflow, then the
   sender when selected. Each component runs its own post-apply health check.
5. Airflow deployment builds a commit-tagged image, changes only application
   services, preserves each DAG's pause state, drains active tasks before
   replacing workers, and waits for service health checks. If startup fails it
   restores the previous commit, image configuration, and DAG pause state. It
   batches pause-state changes through the supported Airflow CLI and does not
   recreate PostgreSQL, Redis, or log volumes.
6. Compare the Execution API route probe, DAG source readability,
   registration, import errors, exact release/production commit match, outbox
   counts, and service health.
7. Observe the cycle count in `config/runtime-target.yaml`.
8. Record the deployed commit and GitHub run in the production baseline.

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

After any ingress or Airflow base URL change, dispatch the Airflow `health`
operation with the exact deployed SHA. The protected workflow checks the host
service state, loopback origin, public health endpoint, and public root.

The production health check also requires the private Execution API probe to
return its expected unauthenticated response and the active DAGs to complete
their declared successful run history.

## WeChat Sender

The sender can be deployed independently through its protected workflow, so it
can be repaired without restarting Airflow. Dispatch `dry_run`, then `apply`,
with the same exact commit. Optional `gh`-only wrappers are:

```bash
make sender-deploy DEPLOY_ARGS="--target-commit <full-sha>"
make sender-deploy DEPLOY_ARGS="--apply --target-commit <full-sha>"
make sender-health
```

Use root-owned files under `/etc/wechat-sender/credentials` with directory mode
`700` and file mode `600` for the device and loopback Appium endpoint. Apply
mode deploys an exact commit, runs one unprivileged worker, retries transient
Git fetch failures for standalone installs, enables automatic startup, and waits
for `GET /readyz`. The protected workflow transfers the verified `origin/main`
history as a Git bundle over its pinned SSH connection, so the Android host does
not need direct GitHub access during a deployment. Also verify `GET /healthz`;
do not call the send endpoint as a smoke test. Historical fallback records are
not replayed automatically. Docker Compose is retained only as a development
or alternate-host runtime.

`make sender-diagnose` also returns a sanitized UI structure snapshot for
device incidents: current activity, control geometry, resource IDs, and known
navigation roles. It deliberately reports only whether other text is present,
never chat names or message content.

For an incident where WeChat exposes no usable accessibility tree, run
`make sender-screenshot`. The protected workflow captures one read-only device
screenshot, stores it as a GitHub artifact for one day, and downloads it under
the ignored `.local/diagnostics/` directory. Treat the image as sensitive
operational evidence: do not commit it or paste it into logs.

## Runtime Secrets

Airflow infrastructure secrets are source files under
`/etc/wechat-on-airflow/secrets`, owned by `root:root` with directory mode
`750` and file mode `640`. Airflow and PostgreSQL run as distinct non-root UIDs
with primary group `0`, so this is the minimum shared permission required by
Compose's bind-mounted file Secrets. Compose mounts only the declared Secret
files, and Airflow loads them through supported command-backed configuration.
Do not create a repository or workstation environment file. Recreating containers must go
through the protected GitHub workflow so the exact image, public base URL,
internal Execution API URL, and Secret directory are applied together.

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
