# Architecture

## Production Data Flow

```mermaid
flowchart LR
    API["Venue booking APIs"] --> DAG["Venue polling DAGs"]
    Proxy["Proxy sources and cache"] --> DAG
    DAG --> Cache["Airflow Variable dedupe cache"]
    Cache --> Email["Tencent SES"]
    Cache --> WeChat["Managed WeChat sender API"]
    Email -. failure .-> EmailOutbox["Email fallback outbox"]
    WeChat -. failure .-> WeChatOutbox["WeChat fallback outbox"]
```

The deduplication cache is written before delivery. Email and WeChat are
independent best-effort channels so a WeChat device outage does not delay email.
Fallback outboxes are deduplicated incident records, not automatic retry queues;
blind replay could send stale or duplicate availability.

The WeChat sender runs as an independent Compose project with one process per
device. It is not an Airflow component, but it is repository-managed and
included in production health checks.

## Airflow 3 Runtime

```mermaid
flowchart TB
    API["Airflow API Server"] --> DB[("PostgreSQL")]
    Scheduler["Scheduler"] --> DB
    DagProcessor["DAG Processor"] --> DB
    Triggerer["Triggerer"] --> API
    Scheduler --> Redis[("Redis")]
    Redis --> Worker["Celery Worker"]
    Worker --> API
    Worker --> External["Booking, email, WeChat, SSH/ADB services"]
```

The target runtime uses the official Airflow 3 image, a pinned custom build,
CeleryExecutor, PostgreSQL, Redis, and FAB Auth Manager.

Airflow 3 uses fresh, explicitly named PostgreSQL, Redis, and log volumes. The Airflow 2
metadata database is not upgraded or reused; it remains intact for rollback.
Only contract-declared configuration and continuity state are imported.
Historical runs, task instances, XCom rows, and fallback outboxes do not cross
the cutover boundary.

## Ownership Boundaries

- DAG files define schedules and task wiring only. The component manifest
  enforces a 120-line limit and rejects direct network-client imports.
- Venue querying, parsing, filtering, and notification orchestration live in
  `src/wechat_airflow/venues/`.
- Proxy refresh implementations live in `src/wechat_airflow/proxy_tools/`.
- Device maintenance implementations live in
  `src/wechat_airflow/maintenance/`.
- Notification clients and fallback logic belong in `src/`.
- Airflow Variables provide runtime configuration, not business logic.
- Fresh-start Variable behavior is declared in
  `config/config-contracts.yaml`; venue deduplication state is preserved and
  fallback outboxes are reset without replay.
- Production maintenance is executed through scripts and one-off deployment
  manager commands, not through Airflow internal Python APIs.

The authoritative active component and configuration contract is
`config/active-components.yaml`. Static verification checks each declared
schedule, and Airflow 3 DagBag verification checks the DAG ID, source file, and
task IDs against that manifest.

The venue and proxy adapters were moved without rewriting their dynamic API
payload handling. Their exact modules are a bounded typing backlog in
`pyproject.toml`; all other source modules remain under strict mypy checking.
