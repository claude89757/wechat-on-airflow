# Production Deployment

This runbook covers reversible component deployments after the Airflow 3 fresh
start. The one-time Airflow 2 cutover is in `airflow-upgrade.md`.

## Preconditions

The exact release commit must be on protected `main` with a successful GitHub
`CI / verify` check. GitHub is the authoritative control plane; workstations
keep only GitHub authentication and never hold production Cloudflare or SSH
credentials.

Before release:

1. record current Web, Airflow, and sender identities and health;
2. review the diff for secrets and confirm version/changelog consistency;
3. merge through a pull request and use the full merge SHA;
4. identify whether the release changes Web, Airflow, sender, or only the
   control plane.

Only `.github/workflows/ops-chatops.yml` listens to owner comments on issue 39.
Do not add another `issue_comment` listener for release, tag, or operations
commands.

## Routine Named Release

Use one command:

```text
/release ship <version> <full-sha> scope=auto sender=false
```

The workflow performs these steps in order:

1. validate `pyproject.toml`, runtime package version, and the matching
   `CHANGELOG.md` section before any production mutation;
2. require the exact-SHA `CI / verify` check through the common release gate;
3. compare the target with the previous semantic release and resolve the
   component scope;
4. apply only the required components through the protected `production`
   Environment;
5. run each deployed component's exact-commit health checks;
6. create the immutable Git tag and GitHub Release only after deployment
   succeeds;
7. publish one authoritative result comment and one Action summary.

`scope=auto` is preferred. A manual scope may broaden the plan, but the planner
rejects any scope that omits a detected runtime component. Sender deployment is
never implied: when sender code is in scope the command must include
`sender=true`.

Control-only releases—workflows, release tooling, documentation, tests, and
version-only metadata—run the full conservative CI suite but deploy no runtime.
Web-only releases no longer restart Airflow. The release summary records
component identities independently rather than requiring a repository-wide SHA
that forces unrelated replacements.

## Advanced and Recovery Commands

Use these only when a separate dry run, staged incident recovery, or a resumed
tag operation is required:

```text
/release preflight <full-sha> scope=auto sender=false
/release apply <full-sha> scope=auto sender=false
/release tag <version> <full-sha>
```

A separate preflight is recommended for unusual D1 migrations, Airflow runtime
or metadata changes, and rollback rehearsals. Routine low-risk releases do not
need it because Web apply runs its own build/dry-run/migration listing and the
Airflow transaction runs its own preflight before replacement.

The production release gate is the only CI waiter. It fails immediately for an
older target with no CI record, polls only an existing queued or in-progress
check, and rejects unsuccessful checks. ChatOps must not duplicate that wait.

## Component Deployment Order

When multiple components are in scope, deployment remains ordered:

1. Web application and D1 migrations;
2. Airflow application services;
3. WeChat sender when explicitly approved.

A skipped component is recorded as skipped, not treated as a failure. Unknown
or unclassified runtime paths conservatively expand to all components.

## Airflow Transaction

Airflow apply builds a commit-tagged image, drains active task instances,
preserves each already-declared DAG's pause state, restores newly introduced
target DAGs as unpaused even if leftover metadata marked them paused, replaces
only application services, and retains PostgreSQL, Redis, log, and other
stateful volumes. It batches pause-state changes through the supported
Airflow CLI.

Deployment and full production health are one transaction. If new containers
start but any complete health check fails, the workflow restores the prior
commit, image configuration, and DAG pause state, verifies the restored version,
and fails the attempted release. Deployment failure and restore failure are
reported separately.

The health gate checks, among other contracts:

- exact Airflow component commit and supported Airflow version;
- service and container health;
- private Execution API route behavior;
- DAG source readability, registration, pause state, and import errors;
- required Variables without exposing values;
- declared recent successful schedule cycles (new DAGs with only successful
  but incomplete history stay apply-healthy as warming-up warnings);
- managed Cloudflare Tunnel and sender readiness;
- outbox evidence without automatic replay.

Observe the cycle count in `config/runtime-target.yaml` after changes that affect
DAG behavior.

## Web Application

Web apply performs:

1. deterministic production build;
2. Wrangler deploy dry-run with the target deployment commit;
3. remote D1 migration listing;
4. D1 migration apply;
5. Worker deployment;
6. exact-commit `/api/healthz` verification.

Never use workstation Wrangler credentials for a production migration or
deployment. For a Web-only release, Airflow remains on its existing healthy
component commit.

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

## WeChat Sender

The sender can be repaired independently without restarting Airflow. Sender
scope requires explicit `sender=true`. Apply deploys the exact commit to the
Android host, runs one unprivileged worker, enables automatic startup, and waits
for both `/healthz` and `/readyz`.

The protected workflow transfers verified history over the pinned SSH
connection, so the Android host does not need direct GitHub access. Do not call
the send endpoint as a smoke test. A real message probe requires a separate,
explicit owner-approved `/ops wechat-contact-probe` command. Historical fallback
records are never replayed automatically.

## Runtime Secrets

Airflow infrastructure secrets are source files under
`/etc/wechat-on-airflow/secrets`, owned by `root:root` with directory mode `750`
and file mode `640`. Airflow and PostgreSQL run as distinct non-root UIDs with
primary group `0`, so this is the minimum shared permission required by
Compose's bind-mounted file Secrets.

Do not create repository or workstation environment files. Recreating
containers must go through the protected GitHub workflow so the exact image,
public base URL, internal Execution API URL, and Secret directory are applied
together.

## Rollback

The scope planner compares a forward candidate with its preceding semantic
release. It must not be used to infer which parts of an arbitrary historical
commit should be restored.

For a component-only rollback, dispatch the matching protected reusable workflow
with the prior recorded component commit:

- `production-webapp.yml` with `operation=deploy_apply` for Web;
- `production-airflow.yml` with `operation=deploy_apply` for Airflow application
  services;
- `production-wechat-sender.yml` with `operation=apply` for the sender, after
  explicit real-host approval.

Each workflow preserves its normal preflight and exact-commit health checks. Use
the full production release path only for a reviewed repository-wide rollback
whose detected scope intentionally includes all relevant components. This does
not replace the Airflow 3 metadata database.

Database restore, Airflow major-version migration, and metadata deletion are
separate high-risk operations requiring explicit approval.

## Metadata Cleanup

Metadata cleanup is deployment maintenance, not an Airflow DAG. Its normal
agent check is read-only:

```bash
make db-cleanup-check
```

Do not schedule apply mode. After explicit approval for a specific cutoff, use:

```bash
PYTHONPATH=src .venv/bin/python scripts/airflow_db_cleanup.py \
  --apply --confirm-delete-before YYYY-MM-DD --format json
```

Apply mode requires a clean pushed commit, an exact production commit match,
and a verified encrypted database backup. It deletes records and cannot be used
as a smoke test.
