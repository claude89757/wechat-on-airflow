---
name: operate-tennis-alerts
description: Operate this repository's Shenzhen tennis alert platform across Airflow 3, PostgreSQL Host Core, the stateless Cloudflare edge, Tencent SES, Android Sender and owner-authorized MCP. Use for diagnosis, incidents, health, configuration, releases, deployment, observation and cleanup review.
---

# Operate Tennis Alerts

The owner accepts interruptions. Follow the minimal lifecycle in
`docs/runbooks/fast-verification.md`: scoped local tests, fast PR checks, one main
release gate and protected SHA-based updates. Shared Python changes require
lint/typecheck/Python tests, not unrelated image builds. Prefer interruptible
Airflow updates; never clear durable business outboxes or bypass authentication.
These rules supersede blanket full-verify and uninterrupted-service requirements.

For venue/coupled business updates read `docs/runbooks/venue-onboarding.md` and
use `make release`. It coordinates the existing protected interruptible Airflow,
Sender, Host Core/edge and activation stages; resume with `make release-resume`.
The diff base is the live Host Core SHA, not an old semantic tag. Do not send an
ordinary venue update through `scope=all` just to satisfy the legacy coupled
release guard; unrelated MCP services must not block it. Natural receipts remain
asynchronous observations, with no synthetic sends.

For verification scope follow `docs/runbooks/fast-verification.md`. Focused local
checks replace blanket full verification for documentation, frontend and MCP-only
work; shared or release-control changes still require `make verify`. The exact
pushed CI gate and protected production authority remain mandatory.

Treat the repository and read-only production evidence as operational memory.
Carry work from diagnosis through verified production state when the request
includes repair, maintenance, release, or deployment.

## Rebuild Context

Work from the repository root. Confirm it by locating
`config/active-components.yaml`.

Read these sources before changing runtime behavior:

1. `AGENTS.md`
2. `config/active-components.yaml`
3. `config/config-contracts.yaml`
4. `config/runtime-target.yaml`
5. `ARCHITECTURE.md`
6. `docs/production-baseline.md`
7. The runbook and ADR relevant to the affected component

Inspect the worktree, local `HEAD`, upstream state, existing test evidence, and
the current production baseline. Do not infer production state from chat
history. Never print Variable values, credentials, recipient addresses,
tokens, device login details, database passwords, or Fernet material.

## Classify The Work

Choose the narrowest applicable class:

- **Read-only diagnosis:** inspect code, contracts, logs, health, recent runs,
  service status, and incident outbox metadata without changing production.
- **Reversible repair:** change code, tests, documentation, or non-secret
  contracts; deploy an exact pushed commit with a documented rollback.
- **Configuration maintenance:** compare names, types, counts, and protected
  hashes; migrate required configuration without exposing values.
- **Release:** verify, commit, push, wait for CI, deploy every affected runtime,
  observe natural cycles, and record evidence.
- **High-risk operation:** stop before apply and obtain explicit approval.

High-risk operations include production database migration or replacement,
metadata deletion, backup restore, secret rotation, Git history rewriting,
real email or WeChat tests, and deleting a component whose ownership is not
proven.

## Execute The Lifecycle

1. **Inspect:** establish the exact code, configuration contract, service, DAG,
   and external dependency involved.
2. **Baseline:** run the applicable read-only checks before editing. Preserve
   timestamps, counts, commit IDs, failing states, and rollback inputs without
   recording secrets.
3. **Diagnose:** identify the failing ownership boundary and root cause. Read
   [diagnosis.md](references/diagnosis.md) for symptom-specific checks.
4. **Specify acceptance:** add a failing regression test or a deterministic
   machine-verifiable check. Tests and smoke checks must not deliver real
   notifications.
5. **Repair:** make the smallest complete change within the repository
   ownership boundaries. Update contracts, runbooks, ADRs, and baseline facts
   when behavior or operations change.
6. **Verify locally:** run focused credential-free checks while iterating, then
   run the checks required by `docs/runbooks/fast-verification.md`. Local checks are development evidence, not production
   authority.
7. **Publish code:** confirm the diff contains no secrets or generated noise,
   commit intentionally, push the exact commit, and require GitHub `CI / verify`
   to pass.
8. **Deploy:** select the component path in
   [release-paths.md](references/release-paths.md). Dispatch the protected GitHub
   preflight before apply and deploy only the exact full commit SHA. Never use
   local Wrangler, SSH, server credentials, or a workstation environment file.
9. **Verify production:** use the protected component health workflows with the
   explicit release SHA, contract checks, and browser checks as applicable.
   Compare against the baseline.
10. **Observe:** wait for the schedule-cycle count declared in
    `config/runtime-target.yaml`. Prefer natural DAG runs; do not manufacture
    production notifications.
11. **Record:** update durable repository evidence when an incident reveals a
    new fact. Report the deployed commit, checks, residual risk, and unrelated
    warnings precisely.

Use `inspect -> plan -> preflight -> apply -> verify -> observe -> record`.
On failure use `stop -> preserve evidence -> rollback -> verify -> record`.
Never treat a restart alone as a root-cause fix.

## Preserve System Invariants

- Persist venue deduplication state before attempting delivery.
- Publish raw venue observations to the Web application before attempting
  WeChat so a device outage cannot delay subscriber email.
- Keep subscriptions, matching and email delivery in PostgreSQL Host Core;
  Cloudflare is a stateless public edge and D1 is an unbound migration archive.
  Venue DAGs must not read fixed recipient lists or send venue email.
- Persist observations and durable delivery intents in Host Core; channel
  failures must not prevent independent email or WeChat processing.
- Isolate WeChat failures per chat and run one sender process per device.
- Treat retired Airflow outboxes as non-replay incident evidence. Active
  PostgreSQL outboxes follow durable worker leases and reconciliation; uncertain
  provider submissions must never be blindly replayed.
- Prevent duplicates through PostgreSQL subscription/event identity contracts.
- Do not display bookable slots or email addresses in the public web app.
- Keep DAG files wiring-only and preserve active DAG IDs unless a migration
  plan is approved.
- Keep production on a pushed commit and pinned image. Preserve PostgreSQL,
  Redis, and log volumes during application deployments.

## Use Repository Commands

For daily operations, prefer the MCP-first routing in
`docs/runbooks/agent-operations.md`: `ops_status`, `ops_diagnose` or
`phone_devices` first; protected GitHub diagnostics remain the fallback and
business-acceptance implementation. MCP command execution requires individual
human approval and must not replace protected releases. Check for active releases
on the host before requesting a mutation; there is no cross-channel shell lock.

Use the `Makefile` as the supported interface. Prefer:

```text
make production-health
make phone-diagnose
make sender-diagnose
make sender-recover
make verify
make deploy-check
make rollback-check
make deploy
make db-cleanup-check
```

Do not replace structured scripts with improvised remote shell sequences.
Outside owner-authorized MCP administration, authenticate the workstation only
with GitHub and dispatch production operations through protected workflows.
Deployment credentials must come
from the GitHub `production` Environment. Runtime credentials must come from
Airflow Variables, Cloudflare Worker Secrets, Docker Secrets, or systemd
credentials; the repository and developer workstation must not contain
production secret files. The Raspberry Pi scrape host uses the
`PI_DEVICE_SSH_*` names declared in `config/runtime-target.yaml`; never print
those values or copy a workstation `.env` into production.

## Finish Only With Evidence

Do not declare completion until:

- the worktree has no accidental changes;
- tests cover the changed behavior;
- required scoped local checks pass (full `make verify` for shared changes);
- the exact commit is pushed and CI passes;
- each affected production component runs that commit;
- post-deploy health and required natural cycles pass;
- no real notification was sent without approval;
- rollback remains available;
- documentation and machine-readable contracts match reality.

If a required check cannot run, state exactly which check is missing and why.
