# wechat-on-airflow

Production Apache Airflow workflows that monitor Shenzhen tennis venue
availability and send concise email and best-effort WeChat notifications.

The repository is migrating from Airflow 2.10.5 to Airflow 3.3.0. Until the
production migration is complete, `config/active-components.yaml` and
`docs/production-baseline.md` distinguish the observed runtime from the target
runtime.

## Runtime

- Apache Airflow 3.3.0 on Python 3.12
- CeleryExecutor
- PostgreSQL 17
- Redis broker
- FAB Auth Manager
- API Server, Scheduler, DAG Processor, Worker, and Triggerer
- independent, repository-managed WeChat sender service

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
make test-dags
```

`make test-dags` builds the pinned Airflow image and checks DAG imports inside
Airflow 3. Tests and smoke checks do not send real email or WeChat messages.

## Configuration

Copy `.env.example` to `.env` for container-level settings. Airflow Variable
names and their schemas are documented in:

- `config/active-components.yaml`
- `config/config-contracts.yaml`

Neither file contains production values. Every venue has an independent email
recipient Variable; there is no global recipient fallback.

The synchronous WeChat sender has a separate Compose project; see
`docs/wechat-sender-service.md`. Its public send endpoint has no token by
design; the sender Compose project exposes only its HTTP service.

## Operations

Read `AGENTS.md` first. Production procedures are maintained under
`docs/runbooks/`. Production database migration, restore, destructive cleanup,
secret rotation, and real notification tests require explicit human approval.

The repository is designed for coding-agent maintenance. Machine-readable
component, configuration, and runtime contracts are under `config/`; chat
history is not an operational dependency.

## Contributing

See `CONTRIBUTING.md`, `SECURITY.md`, and `CODE_OF_CONDUCT.md`. CI runs the same
static, unit, manifest, Compose, image-build, and DAG-import gates used locally.

## License

Apache License 2.0. See `LICENSE`.
