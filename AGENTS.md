# Agent Guide

This repository is operated primarily by coding agents. Treat repository
content and production read-only checks as the source of truth. Do not rely on
chat history for operational knowledge.

## Mission

Run the production Shenzhen tennis availability workflows on Apache Airflow 3,
with Web-owned subscription email, best-effort WeChat delivery, deterministic
verification, and reversible production deployments.

For repository-wide diagnosis, operations, incident response, release, or
deployment work, load
`.agents/skills/operate-tennis-alerts/SKILL.md` and follow its lifecycle.

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
- `pi_host/`: Raspberry Pi scrape-host services, not Airflow DAG code.
- `docker/`: reproducible Airflow image files.
- `docs/`: architecture, runbooks, configuration, and decisions.

Do not add test DAGs, demos, generated files, or archived source under `dags/`.
DAG files must stay below the manifest checker's wiring-only limit and must not
import network clients directly. The exact mypy exclusions in `pyproject.toml`
are a bounded legacy backlog; do not broaden them, and remove an exclusion when
the corresponding adapter is made fully typed.

## Business Invariants

- Persist the Airflow venue notification cache before attempting WeChat
  delivery; the Web application owns subscriber-email event deduplication.
- Publish raw venue observations to the Web application before attempting WeChat
  delivery so a device outage cannot delay subscriber email.
- Airflow must not send venue email directly or read fixed recipient lists.
- The Web application owns email verification, subscription matching,
  deduplication, delivery retries, and its D1 notification outbox.
- WeChat failures are isolated per chat and recorded in the WeChat fallback outbox.
- Tests and smoke checks must never send real email or WeChat messages.
- The WeChat sender runs exactly one process per device; its in-process lock is
  not safe with multiple workers.
- Airflow fallback outboxes are incident records and must not be replayed automatically.
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
make webapp-deploy
make webapp-health
make pi-device-ssh-sync
```

`make verify` is the required local development gate before committing. The
authoritative release gate is the GitHub `CI / verify` check for the exact
release commit; it includes the Airflow 3 image build and DagBag contract check.

`make deploy`, `make webapp-deploy`, and `make sender-deploy` are optional
GitHub-only workstation dispatchers and are read-only by default. Use
`make deploy DEPLOY_ARGS="--apply --target-commit <full-sha>"` only after the
documented gates pass. Apply mode pauses active DAGs, drains task instances,
replaces only application containers, and restores the original DAG pause state.

The production WeChat sender uses `wechat-sender.service` on the Android host.
Deploy it through `production-wechat-sender.yml` or the unified
`production-release.yml`; direct host installation is an implementation detail,
not a workstation release path. Docker Compose is an alternate development
runtime, not the production process manager.

Airflow metadata cleanup is a deployment-manager command, not a DAG. Run
`make db-cleanup-check` for a read-only production dry run. Apply mode requires
explicit human approval and an exact `--confirm-delete-before YYYY-MM-DD`;
never schedule or invoke deletion autonomously.

## Production Access

Production access is mediated by the protected GitHub `production`
Environment. A workstation authenticates only with `gh auth login`; GitHub
Actions receives scoped SSH deployment identities and invokes the structured
operations scripts. Runtime secrets stay in platform-native stores and are
never downloaded to developer devices.

The Raspberry Pi used for YDMap / 大沙河国际网球交流中心 browser scraping
is a third remote host, alongside the Airflow server and the Android WeChat
sender host. Its login identity is stored only in the GitHub `production`
Environment. Do not copy those values into the repository, commit `.env`,
print them, or treat a workstation `.env` as production identity.

GitHub Environment secret names:

- `PI_DEVICE_SSH_HOST`
- `PI_DEVICE_SSH_PORT`
- `PI_DEVICE_SSH_USER`
- `PI_DEVICE_SSH_PASSWORD`
- `PI_DEVICE_SSH_KNOWN_HOSTS`
- `PI_DEVICE_SSH_HOST_KEY_SHA256`

The contract also lists these names in
`config/runtime-target.yaml` under `pi_device_ssh_environment` and
`github_environment_secrets`. Airflow and sender hosts use SSH public keys;
the Pi currently uses password authentication plus a pinned host-key
fingerprint. Future Airflow or GitHub workflows that need the Pi must read
these Environment secrets in Actions, then keep the runtime copy in an
Airflow Variable or a host credential file. Do not download the password to
a laptop, and do not accept an unverified host key.

Before and after a production change:

```text
make production-health
```

The health workflow requires an explicit full release SHA and fails when the
deployed commit differs. Local `HEAD` is never production identity.

Never print Variable values, Connection credentials, GitHub Environment
secrets, email addresses, API tokens, database passwords, device login
details, or the Fernet key.

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
