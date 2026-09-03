# Agent Guide

This repository is operated primarily by coding agents. Treat repository
content and production read-only checks as the source of truth. Do not rely on
chat history for operational knowledge.

## Mission

Run the production Shenzhen tennis availability platform on Apache Airflow 3
with PostgreSQL-owned subscriptions and notification state, host-owned Tencent
SES delivery, best-effort WeChat delivery through the Android sender,
deterministic verification, and reversible exact-commit deployments.

For repository-wide diagnosis, operations, incident response, release, or
deployment work, load
`.agents/skills/operate-tennis-alerts/SKILL.md` and follow its lifecycle.

## Read First

1. `config/active-components.yaml`
2. `config/config-contracts.yaml`
3. `config/host-core-contract.yaml`
4. `config/runtime-target.yaml`
5. `ARCHITECTURE.md`
6. `docs/production-baseline.md`
7. Relevant runbooks and ADRs

On every resumed task, inspect the current Git worktree, pushed commit, existing
verification evidence, and production baseline before changing files. Continue
from the last verified state; chat history is not authoritative.

## Repository Boundaries

- `dags/`: production DAG definitions and task wiring only.
- `src/wechat_airflow/venues/`: venue API, parsing, filtering, and observation orchestration.
- `src/wechat_airflow/host_core/`: the PostgreSQL-backed Web API, migration, matching,
  email delivery, delivery reconciliation, and durable notification workers.
- `src/wechat_airflow/notifications/`: Airflow observation client, WeChat client,
  booking-link policy, and channel-specific compatibility helpers.
- `src/wechat_airflow/proxy_tools/`: proxy refresh implementations.
- `src/wechat_airflow/maintenance/`: device maintenance implementations.
- `tests/`: unit, contract, DAG import, migration, and smoke tests.
- `config/`: non-secret machine-readable contracts.
- `scripts/`: idempotent development and operations commands.
- `pi_host/`: Raspberry Pi scrape-host services, not Airflow DAG code.
- `webapp/`: React assets and the stateless Cloudflare edge gateway. Legacy D1
  code is retained only for the migration and rollback window.
- `docker/`: reproducible Airflow and service image files.
- `docs/`: architecture, runbooks, configuration, decisions, and evidence.

Do not add test DAGs, demos, generated files, or archived source under `dags/`.
DAG files must stay below the manifest checker's wiring-only limit and must not
import network clients directly. The exact mypy exclusions in `pyproject.toml`
are a bounded legacy backlog; do not broaden them, and remove an exclusion when
the corresponding adapter is made fully typed.

## Business Invariants

- PostgreSQL schema `zacks` is the only durable business store after host-core
  cutover. It owns identities, subscriptions, venue status, event identities,
  notification Outboxes, quotas, leases, and delivery results.
- Redis is optional acceleration and wake-up only. Redis loss must not lose,
  duplicate, or change the eligibility of a notification.
- Persist a normalized venue observation in the host-core database before
  creating or attempting email or WeChat delivery.
- Venue DAGs do not contain recipient lists or call Tencent SES directly. The
  host notification worker owns subscriber-email matching, deduplication,
  batching, quotas, retries, and provider reconciliation.
- Airflow continues to call the Android WeChat sender. The venue-level Web
  subscription gate is read from local PostgreSQL; Cloudflare or D1 failure must
  not stop an already configured WeChat channel.
- Exactly one subscriber-email owner is active at a time. During migration it is
  Cloudflare; after the atomic owner switch it is the Airflow-host core. Dual
  observation writes must never become dual delivery ownership.
- Cloudflare is a public edge only after cutover: static assets, TLS/WAF, and a
  stateless `/api/*` reverse proxy. Worker Cron performs no notification work.
- D1 remains read-only during the rollback window. This release must not delete,
  truncate, or overwrite the production D1 database.
- WeChat failures are isolated per chat. Stale WeChat incident records are not
  blindly replayed.
- Tests and smoke checks must never send real email or WeChat messages.
- The WeChat sender runs exactly one process per device; its in-process lock is
  not safe with multiple workers.
- Do not change active DAG IDs or polling cadence without an explicit migration
  and policy update; DAG IDs own run history.
- Production deploys use an exact pushed Git commit and pinned container image.

## Standard Commands

Run supported checks through the repository `Makefile`:

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
make webapp-deploy
make webapp-health
make pi-device-ssh-sync
```

`make verify` is the required local development gate before committing. The
authoritative release gate is the GitHub `CI / verify` check for the exact
release commit; it includes the Web/Worker checks, Airflow image build, Compose
validation, and DagBag contract check.

The first host-core cutover is not a normal component deployment. Use the
protected `production-host-core.yml` lifecycle and
`docs/runbooks/host-core-cutover.md`. It must perform preflight, shadow deploy,
secure secret transfer, initial import, natural dual-write observation,
quiescence, final import, one-owner cutover, public verification, and automatic
rollback on failure.

`make deploy`, `make webapp-deploy`, and `make sender-deploy` are optional
GitHub-only workstation dispatchers and are read-only by default. Use an apply
mode only after the documented exact-SHA gates pass.

The production WeChat sender uses `wechat-sender.service` on the Android host.
Deploy it through `production-wechat-sender.yml` or the unified
`production-release.yml`; direct host installation is an implementation detail,
not a workstation release path.

Airflow metadata cleanup is a deployment-manager command, not a DAG. Run
`make db-cleanup-check` for a read-only production dry run. Apply mode requires
explicit human approval and an exact `--confirm-delete-before YYYY-MM-DD`;
never schedule or invoke deletion autonomously. Host-core business records and
D1 rollback records are outside this cleanup path.

## Production Access

Production access is mediated by the protected GitHub `production`
Environment. A workstation authenticates only with GitHub; GitHub Actions
receives scoped SSH and Cloudflare deployment identities and invokes structured
operations scripts. Runtime secrets stay in platform-native stores, root-owned
host files, Airflow Variables/Connections, or systemd credentials and are never
downloaded to developer devices.

The initial host-core migration transfers the existing Tencent SES settings
from Worker Secrets directly to root-owned host files using an ephemeral
RSA-OAEP/AES-GCM envelope. GitHub receives neither plaintext values nor durable
decryption material. Do not replace this with logs, artifacts, repository
secrets, or command-line echoing.

The Raspberry Pi used for YDMap browser scraping is a third remote host,
alongside the Airflow server and Android sender host. Its login identity is
stored only in the GitHub `production` Environment. Do not copy those values
into the repository, commit `.env`, print them, or accept an unverified host
key.

Before and after a production change:

```text
make production-health
```

The health workflow requires an explicit full release SHA and fails when the
deployed commit differs. Local `HEAD` is never production identity.

Never print Variable values, Connection credentials, GitHub Environment
secrets, email addresses, API tokens, database passwords, device login details,
SES keys, invitation plaintext, or the Fernet key.

## Agent Authority

Agents may autonomously perform read-only inspection and local reversible work:

- inspect local and production state without revealing secrets;
- edit code, tests, documentation, and non-secret configuration;
- build images and run isolated migration rehearsals;
- create backups;
- commit and push verified changes;
- deploy reversible application changes only after all documented gates pass.

Human approval is required before high-risk or irreversible work:

- deleting or cleaning production business or metadata records;
- deleting D1 or ending the documented rollback window;
- running a production Airflow metadata migration to a new major version;
- restoring or replacing a production database;
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
- Active component and host-core contracts match production.
- Tests cover changed behavior without real external delivery.
- `make verify` passes.
- Documentation and ADRs reflect the architecture and ownership boundary.
- Changes are committed and pushed.
- Exact-SHA CI succeeds.
- Every affected production component runs the pushed commit.
- Host-core cutover evidence proves one delivery owner, successful migration,
  public and local health, and rollback readiness.
- Post-deploy checks pass over the required natural schedule cycles.
- Remaining risks and unrelated failures are reported precisely.
