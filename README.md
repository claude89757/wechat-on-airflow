# wechat-on-airflow

Production Apache Airflow workflows that monitor Shenzhen tennis venue
availability, publish observations for verified-email Web subscriptions, and
send best-effort WeChat notifications. The repository also contains the
mobile-first Cloudflare Worker application that owns subscriber email.

Production completed a fresh-start migration from Airflow 2.10.5 to Airflow
3.3.0. Historical metadata was intentionally not migrated; configuration and
notification continuity caches were verified in the new runtime, while the
Airflow 2 database remains preserved for rollback.

## Runtime

- Apache Airflow 3.3.0 on Python 3.12
- CeleryExecutor
- PostgreSQL 17
- Redis broker
- FAB Auth Manager
- API Server, Scheduler, DAG Processor, Worker, and Triggerer
- Cloudflare Tunnel ingress at `https://airflow.claude89757.cc`
- Cloudflare Worker web application at `https://zacks.claude89757.cc`
- independent, repository-managed WeChat sender on the Android device host

Supported development and production target:

| Component | Version |
| --- | --- |
| Airflow | 3.3.0 |
| Python | 3.12 |
| PostgreSQL | 17 |
| Celery provider | 3.21.0 |
| FAB provider | 3.7.1 |
| Standard provider | 1.15.0 |

## Development

Python 3.12 and Docker Compose v2 are required.

```bash
make setup
make verify
```

`make verify` includes static checks, unit tests, configuration validation, the
pinned Airflow image build, the web application build, and a DagBag contract
check inside Airflow 3. The
DagBag check verifies DAG IDs, source files, task IDs, and import errors against
the active component manifest; the static manifest check also verifies each DAG
schedule. Tests and smoke checks do not send real email or WeChat messages.

Production DAG files are intentionally thin. Venue, proxy, and device
maintenance implementations are installed from `src/wechat_airflow/`.

The web application is under `webapp/`. It uses React, Cloudflare Workers, D1,
and Tencent SES. It does not list available courts or book a court. Users
verify an email once per browser, then create alert rules for selected venues,
daily time ranges, and a 7–14 day validity period.

## Configuration

Run `make local-secrets` to generate ignored, development-only Docker Secret
files inside a mode-`700` directory. The development files are mode `644`
because Linux Compose bind mounts preserve source ownership while the
containers use different non-root UIDs; the enclosing directory limits host
access. Production settings are managed by the protected GitHub environment,
Airflow Variables, Cloudflare Worker Secrets, host Docker Secrets, and systemd
credentials. Airflow Variable names and their schemas are documented in:

- `config/active-components.yaml`
- `config/config-contracts.yaml`

Neither file contains production values. Airflow has no fixed email recipient
lists and does not send venue email directly.

Airflow publishes raw venue observations to the Worker before attempting
best-effort WeChat delivery. The publisher is bounded and cannot fail a venue
DAG. Its endpoint and token are protected Airflow Variables. The Worker is the
only email-delivery owner: it verifies addresses, matches active subscriptions,
deduplicates events, and retries delivery through its D1 outbox.

Production Airflow is exposed through an outbound-only Cloudflare Tunnel. The
API server trusts proxy headers and binds host port 8080 to loopback only.
Public access uses the hostname root, and the private Execution API uses the
matching `/execution/` route.

The synchronous WeChat sender runs as a dedicated systemd service on the
Android host; see `docs/wechat-sender-service.md`. Its public send endpoint has
no token by design. Docker Compose remains an alternate development runtime.

## Operations

Read `AGENTS.md` first. Production procedures are maintained under
`docs/runbooks/`. The Airflow 3 cutover uses a fresh metadata database and
migrates configuration and continuity caches only. The Airflow 2 database
remains intact for rollback. Database restore, destructive cleanup, secret
rotation, and real notification tests require explicit human approval.

Metadata cleanup is not an Airflow DAG because Airflow 3 task subprocesses do
not receive direct metadata database access. `make db-cleanup-check` performs a
read-only production dry run; deletion requires a separately approved,
date-confirmed apply command.

The repository is designed for coding-agent maintenance. Machine-readable
component, configuration, and runtime contracts are under `config/`; chat
history is not an operational dependency.

Cloudflare deployment and operational checks are documented in
`docs/runbooks/webapp-deployment.md`.

## Contributing

See `CONTRIBUTING.md`, `SECURITY.md`, and `CODE_OF_CONDUCT.md`. CI runs the same
static, unit, manifest, Compose, image-build, and DAG-import gates used locally.
Versioning, the support matrix, release gates, and rollback expectations are in
`docs/release-strategy.md`.

## License

Apache License 2.0. See `LICENSE`.
