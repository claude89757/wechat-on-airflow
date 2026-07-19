# wechat-on-airflow

Production Apache Airflow workflows that monitor Shenzhen tennis venue
availability and send concise email and best-effort WeChat notifications.

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
- Cloudflare Tunnel ingress at `https://airflow.claude89757.cc/airflow`
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
pinned Airflow image build, and a DagBag contract check inside Airflow 3. The
DagBag check verifies DAG IDs, source files, task IDs, and import errors against
the active component manifest; the static manifest check also verifies each DAG
schedule. Tests and smoke checks do not send real email or WeChat messages.

Production DAG files are intentionally thin. Venue, proxy, and device
maintenance implementations are installed from `src/wechat_airflow/`.

## Configuration

Copy `.env.example` to `.env` for container-level settings. Airflow Variable
names and their schemas are documented in:

- `config/active-components.yaml`
- `config/config-contracts.yaml`

Neither file contains production values. Every venue has an independent email
recipient Variable; there is no global recipient fallback.

Production Airflow is exposed through an outbound-only Cloudflare Tunnel. The
API server trusts proxy headers and binds host port 8080 to loopback only. The
public base URL retains the `/airflow` prefix; the private Execution API URL
must retain the same prefix before `/execution/`.

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

## Contributing

See `CONTRIBUTING.md`, `SECURITY.md`, and `CODE_OF_CONDUCT.md`. CI runs the same
static, unit, manifest, Compose, image-build, and DAG-import gates used locally.
Versioning, the support matrix, release gates, and rollback expectations are in
`docs/release-strategy.md`.

## License

Apache License 2.0. See `LICENSE`.
