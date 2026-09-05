# Host Core-only production cutover

This procedure supersedes the previous shadow/dual-write/legacy rollback plan.
The source database is preserved; the old runtime is not retained as a serving
backend. Run only via GitHub's protected `production` Environment. An exact
commit on `main` with passing `CI / verify` is mandatory.

## Deployment transaction

Use Issue #39: `/release ship 0.7.0 <full-main-SHA> scope=all sender=true`.
Only the existing owner-authorized ChatOps dispatcher is permitted. Do not add a
one-time production workflow, bypass CI, restore an old runtime, or expose SSH,
database, SES, verification or invitation secrets to developer machines.

1. Build one exact application image. Ensure the additive `zacks` schema. Create
   a root-only custom-format PostgreSQL backup. Acquire the durable delivery
   fence and pause local consumers. Start the local API in prepared mode.
2. On first activation only, publish the one-time maintenance edge. It blocks
   business writes and contains no notification Cron. Drain the previous owner
   for 300 seconds. Transfer provider and identity/invitation secret material in
   an authenticated RSA-OAEP/AES-GCM envelope directly to the host.
3. Export D1 through its control-plane SQL export, not quota-limited SQL queries.
   Hash the gzip snapshot, copy to a root-only host directory, verify again in
   the API container, and import in one transaction with batched writes.
4. Reconcile the keys/counts of all 15 source tables and preserve provider message
   identities/statuses. Preserve old receipt hashes and verification/invitation
   peppers; verify old invitation ciphertext before re-encrypting locally.
   Expired non-renewing subscriptions become inactive. Old interrupted sends
   are quarantined, not replayed. Migration never truncates/deletes D1.
5. Route observations locally. Publish the production edge with **no D1 binding,
   no Cron schedule, no migration handler and no legacy imports**. Enable host
   email delivery; WeChat consumer remains prepared until collectors and device
   Sender have been deployed to the same commit.
6. Deploy all Airflow services and the Android Sender. Preserve venue schedules
   and drain old tasks rather than replaying or forcibly rewriting task state.
   Verify the Sender's durable idempotency and exact commit.
7. Run the operator-only API transaction probe on the production database. It
   exercises verification, creation/listing/deduplication/cancellation and auth,
   then rolls back every test record. No email/device service is called. Store
   only the privacy-safe result. This is NOT a browser or real-email probe.
8. Enable the dedicated WeChat worker and start an acceptance window. Require
   all 26 venue DAGs to complete three natural cycles with fresh observations;
   auxiliary services must have recent successful runs. Require exact component
   identities, fresh worker heartbeats, no stalled queues, reconciled migration,
   public health/bootstrap/security checks, and actual natural SES-delivered and
   WeChat-sent evidence. Only then create an immutable release tag.

The maintenance interval is explicit downtime for Web mutations, not a claim of
zero-downtime migration. The full import duration depends on the snapshot size.
Do not claim delivery has been validated merely because a container is running.

## Failure and cancellation

The runner uses `set -Eeuo pipefail` with EXIT/INT/TERM/HUP recovery. SSH does not
consume script stdin. Remote commands are Python 3.6-compatible wrappers; app
operations execute in the pinned Python 3.12 image. Errors pause host consumers
with a PostgreSQL exclusive delivery fence. If the API is down, pause runs in a
one-shot application container, not through the failed API.

Recovery is a repaired exact-main-commit release. `activated_at` is durable: once
set, **D1 import is forbidden even while delivery is paused**. Never recreate old
Cloudflare business ownership. Keep source snapshots and PostgreSQL backups
root-only and off public artifacts. Never automatically restore a snapshot over
live post-cutover writes. Data restore is a separate explicitly approved action.

## Notification semantics

Outboxes lease with `FOR UPDATE SKIP LOCKED`. External attempts are recorded
before dispatch. A provider/UI result that may already have succeeded becomes
`submission_unknown`; it is not retried without evidence. A provider retention
window expiring means delivery is unknown, not proven failed. Known connection
failures/rejections use bounded retry. Expired/changed slots and cancelled
subscriptions are rechecked before send and do not get replayed as stale alerts.

The Sender stores idempotency keys, payload hashes and results in its persistent
SQLite WAL database under `/var/lib/wechat-sender`, protected by systemd. Unknown
UI outcomes survive process restart. Per-group booking-link cooldowns live in
PostgreSQL. Old bounded collector preclaim caches do not own delivery outcomes.

## Verification and evidence

`CI / verify` runs Ruff, strict mypy, all Python tests, a disposable PostgreSQL 17
integration service, Web/Worker tests, browser regression, image and DagBag
contracts. Test DB fixtures refuse any database other than local `zacks_test`.
No production secrets or synthetic real notifications are used by CI.

`python -m wechat_airflow.host_core.health --expected-commit <SHA> --require-delivery`
is read-only and outputs a complete structured report. The protected workflow
publishes only counts, venue/task status, hashes and component identity. Missing
sections, stale evidence or absent natural delivery cannot be reported as a pass.
No customer emails, tokens, message bodies, SQL exports or credential values may
appear in public reports.

## Operational limits

The PostgreSQL instance currently also hosts Airflow metadata: host/DB failure
is a shared failure boundary. Redis is only the Celery broker, so its failure can
stop new collection even though already durable email work remains processable.
Cloudflare is still the public Web/Tunnel ingress. Verify the actual Sender
transport does not traverse a Cloudflare proxy before claiming end-to-end
Cloudflare-independent delivery. Neither frontend cache nor D1 is an automatic
business recovery source. Back up the PG business schema and Sender ledger and
rehearse recovery in isolation; do not claim high availability from a single host.
