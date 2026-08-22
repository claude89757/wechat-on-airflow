---
name: operate-tennis-alerts
description: Operate and maintain this repository's Shenzhen tennis alert platform across Apache Airflow 3, the Cloudflare Worker and D1 web subscription service, Tencent SES email, and the Android-host WeChat sender. Use for problem diagnosis, incident response, production health checks, DAG or notification failures, configuration maintenance, web-app changes, sender repairs, release preparation, exact-commit deployment, post-deploy observation, rollback, cleanup review, or any end-to-end lifecycle task in wechat-on-airflow.
---

# Operate Tennis Alerts

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
   run `make verify`. Local checks are development evidence, not production
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
- Keep subscriber email in the Cloudflare Web application. Airflow must not
  read fixed recipient lists, load SES credentials, or send venue email.
- Do not fail a venue DAG because Web observation or WeChat delivery fails;
  record the appropriate bounded incident or retry state.
- Isolate WeChat failures per chat and run one sender process per device.
- Treat the Airflow WeChat outbox and retired email outbox as non-replay
  incident evidence.
- Prevent duplicate web notifications with the D1 subscription/event identity
  contract.
- Do not display bookable slots or email addresses in the public web app.
- Keep DAG files wiring-only and preserve active DAG IDs unless a migration
  plan is approved.
- Keep production on a pushed commit and pinned image. Preserve PostgreSQL,
  Redis, and log volumes during application deployments.

## Use Repository Commands

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
Authenticate the workstation only with GitHub and dispatch production
operations through the protected workflows. Deployment credentials must come
from the GitHub `production` Environment. Runtime credentials must come from
Airflow Variables, Cloudflare Worker Secrets, Docker Secrets, or systemd
credentials; the repository and developer workstation must not contain
production secret files.

## Finish Only With Evidence

Do not declare completion until:

- the worktree has no accidental changes;
- tests cover the changed behavior;
- `make verify` passes;
- the exact commit is pushed and CI passes;
- each affected production component runs that commit;
- post-deploy health and required natural cycles pass;
- no real notification was sent without approval;
- rollback remains available;
- documentation and machine-readable contracts match reality.

If a required check cannot run, state exactly which check is missing and why.
