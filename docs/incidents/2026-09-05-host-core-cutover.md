# Host Core cutover recovery — 2026-09-05

## Verified incident baseline

PR #208 / commit `1726aefc0ccf10262b676149542c7e21034a6fd1` repaired
Python 3.6 subprocess input handling and passed exact-commit CI.
Production ship `33961782432` then completed encrypted secret transfer,
15-table SQL import/reconciliation (including 104 subscriptions), and deployed
the stateless edge without a D1 binding. At 11:16:27 UTC, enabling delivery
failed with PostgreSQL `DeadlockDetected` while `ensure_schema` ran
`CREATE INDEX IF NOT EXISTS observed_slots_venue_date_idx`. Failure recovery
paused host delivery. Airflow, Sender, natural delivery acceptance and release
tagging had not run. A deployed edge is not proof of working notifications.

## Root cause and repair

The process-local schema-ready boolean was false in every new CLI process.
Even when the database was current, every operator command re-ran all schema
DDL and seed writes against concurrent venue observations. Idempotent SQL does
not mean lock-free SQL. Initialization now uses a durable fingerprint of base
DDL, extensions and venue seeds, serialized under the existing advisory lock.
A current database takes a read-only ledger path. The cache is engine-specific
and becomes ready only after commit. Only rolled-back deadlocks/lock timeouts
are retried, with bounded timeouts; other errors still fail closed.

The interrupted first cutover had reconciled migration data and exposed the
host API, but had not set `activated_at`. Retrying based only on that flag
could re-import stale D1 data over host-side subscription changes. The protected
release now resumes from the complete 15-table identity checkpoint, without
secret transfer, D1 import, or a maintenance edge. A pure edge without a valid
checkpoint is refused rather than overwritten. D1 is preserved, never deleted.

## Verification and release policy

Regressions cover an active PostgreSQL writer during cold-process startup,
ledger durability, engine-specific caching, rollback and bounded lock retries,
and executing the release shell with network-free stubs to prove that resume
cannot re-import or expose the maintenance edge. Exact-commit CI remains the
authoritative gate. Use the existing protected `0.7.0` ship transaction with
`scope=all sender=true`; all existing production acceptance requirements remain.
Do not mark the release complete before natural SES-delivered and WeChat-sent
records, the rollback-only subscription API probe, 26 venue DAGs with three
natural successes, and exact host/edge/Sender identities pass.

## Remaining Cloudflare boundary

Venue observations, matching, durable queues and existing email/WeChat delivery
run on the host and do not use D1 or Worker Cron. The browser `/api/*` entry
still invokes the Cloudflare Worker and its origin still uses Cloudflare
Tunnel. Stateless does not mean unlimited: Worker request/CPU quotas can still
affect new browser operations. A future quota-independent public API ingress
would need its own authenticated/rate-limited host route; do not silently
remove origin authentication or change paid plans in this incident repair.
