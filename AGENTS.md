# Agent Guide

This repository is operated primarily by coding agents. Treat repository
content and production read-only checks as the source of truth. Do not rely on
chat history for operational knowledge.

## Mission

Run the production Shenzhen tennis availability workflows on Apache Airflow 3,
with independent email routing, best-effort WeChat delivery, deterministic
verification, and reversible production deployments.

## Read First

1. `config/active-components.yaml`
2. `config/config-contracts.yaml`
3. `config/runtime-target.yaml`
4. `ARCHITECTURE.md`
5. `docs/production-baseline.md`
6. Relevant runbooks and ADRs

On every resumed task, inspect the current Git worktree, pushed commit, existing
verification evidence, and production baseline before changing files. Continue
from the last verified state; chat history is not authoritative.

## Repository Boundaries

- `dags/`: production DAG definitions only.
- `src/wechat_airflow/venues/`: venue API, parsing, filtering, and delivery orchestration.
- `src/wechat_airflow/proxy_tools/`: proxy refresh implementations.
- `src/wechat_airflow/maintenance/`: device maintenance implementations.
- Other `src/` packages: reusable notification and external-service clients.
- `tests/`: unit, contract, DAG import, and smoke tests.
- `config/`: non-secret machine-readable contracts.
- `scripts/`: idempotent development and operations commands.
- `docker/`: reproducible Airflow image files.
- `docs/`: architecture, runbooks, configuration, and decisions.

Do not add test DAGs, demos, generated files, or archived source under `dags/`.
DAG files must stay below the manifest checker's wiring-only limit and must not
import network clients directly. The exact mypy exclusions in `pyproject.toml`
are a bounded legacy backlog; do not broaden them, and remove an exclusion when
the corresponding adapter is made fully typed.

## Business Invariants

- Persist the venue notification deduplication cache before attempting delivery.
- A WeChat outage must not delay or fail email delivery.
- Email failure must not fail a venue DAG; record it in the email fallback outbox.
- WeChat failures are isolated per chat and recorded in the WeChat fallback outbox.
- Every venue uses its own recipient Variable. There is no global recipient fallback.
- Tests and smoke checks must never send real email or WeChat messages.
- The WeChat sender runs exactly one process per device; its in-process lock is
  not safe with multiple workers.
- Fallback outboxes are incident records and must not be replayed automatically.
- Do not change active DAG IDs without a migration plan; DAG IDs own run history.
- Production deploys use an exact Git commit and pinned container image.

## Standard Commands

Run these through the repository `Makefile`:

```text
make setup
make format
make lint
make typecheck
make test
make test-dags
make compose-config
make smoke
make verify
make deploy
make deploy-check
make production-health
make rollback-check
make db-cleanup-check
make sender-image
```

`make verify` is the required local gate before committing. It includes the
Airflow 3 image build and DagBag contract check.

`make deploy` is read-only by default. Use
`make deploy DEPLOY_ARGS="--apply --target-commit <full-sha>"` only after the
documented gates pass. Apply mode pauses active DAGs, drains task instances,
replaces only application containers, and restores the original DAG pause state.

The production WeChat sender uses `wechat-sender.service` on the Android host.
Deploy it with `scripts/install_wechat_sender.sh --target-commit <full-sha>`;
add `--apply` only after preflight. Docker Compose is an alternate development
runtime, not the production process manager.

Airflow metadata cleanup is a deployment-manager command, not a DAG. Run
`make db-cleanup-check` for a read-only production dry run. Apply mode requires
explicit human approval and an exact `--confirm-delete-before YYYY-MM-DD`;
never schedule or invoke deletion autonomously.

## Production Access

Server connection details are read from the untracked `.env`. Production
inspection must be read-only unless the task explicitly reaches a documented
deployment step.

Before and after a production change:

```text
make production-health
```

The health check fails when the production commit differs from local Git HEAD.
Run it from the exact pushed commit intended to own production.

Never print Variable values, Connection credentials, email addresses, API
tokens, database passwords, device login details, or the Fernet key.

## Agent Authority

Agents may autonomously perform read-only inspection and local reversible work:

- inspect local and production state without revealing secrets;
- edit code, tests, documentation, and non-secret configuration;
- build images and run isolated migration rehearsals;
- create backups;
- commit and push verified changes;
- deploy reversible application changes only after all documented gates pass.

Human approval is required before high-risk or irreversible work:

- deleting or cleaning production database records;
- running the production Airflow metadata database migration to a new major version;
- restoring or replacing the production database;
- rotating production secrets;
- rewriting Git history;
- sending real test notifications;
- deleting a component whose production ownership remains ambiguous.

Use `inspect -> plan -> preflight -> apply -> verify -> observe -> record`.
On failure use `stop -> preserve evidence -> rollback -> verify -> record`.
Do not treat a restart as root-cause resolution; add a regression check or
update a contract/runbook when an incident teaches a new operational fact.

## Completion Checklist

- Worktree contains no accidental or generated changes.
- Active component manifest matches production.
- Tests cover the changed behavior without real external delivery.
- `make verify` passes.
- Documentation and ADRs reflect architectural changes.
- Changes are committed and pushed.
- Production deploys the pushed commit.
- Post-deploy health checks pass over multiple schedule cycles.
- Remaining risks and unrelated failures are reported precisely.
