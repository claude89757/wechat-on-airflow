# Contributing

## Development

Use Python 3.12 and Docker Compose v2.

```bash
make setup
make verify
make test-dags
```

Tests must not call production venue APIs when a deterministic fake is
available and must never send real email or WeChat messages.

## Changes

- Keep DAG files limited to scheduling and task wiring.
- Put reusable logic in `src/wechat_airflow`.
- Update `config/active-components.yaml` and configuration contracts when
  runtime dependencies change.
- Add an ADR for decisions that change architecture, data ownership, notification
  semantics, deployment, or rollback.
- Do not commit secrets, production values, logs, databases, or backups.

Use focused commits. A pull request must explain the behavior change, risk,
verification commands, configuration impact, and rollback path.
