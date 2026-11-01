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
8. Enable the dedicated WeChat worker after the API probe. Tag the release at
   that point. Three natural venue cycles, fresh observations and natural
   SES or WeChat receipts stay visible to production health and do not hold
   the pipeline or the tag.

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

### Recover an interrupted release with email already active

Normal `routine-upgrade` still requires both delivery gates to be enabled. Do
not enable an incompatible WeChat consumer to satisfy that gate, or select a
first-cutover operation to avoid the operational baseline check. The protected
ship lifecycle has an explicit recovery entry for the verified state
`deliveryEnabled=true`, `wechatEnabled=false`:

```text
/release recover 0.9.1 <new-full-main-sha> <existing-host-runtime-sha> <control-updated-at-UTC> scope=all sender=true
```

The timestamp is the existing control row's exact `updatedAt`, not the time of
the command. The router passes `recovery_runtime_commit`,
`recovery_control_updated_at`, `recovery_delivery_enabled=true` and
`recovery_wechat_enabled=false` to `production-host-core.yml` with
`operation=recovery-upgrade`. Other states and omitted baselines are rejected.
Both the new target and the existing runtime require successful exact-SHA CI;
the new target must still be current main.

Before changing the host checkout, the reviewed runner code executes bounded
read-only checks in the existing API container. It checks the schema
fingerprint, prior activation and complete migration reconciliation, the exact
control timestamp and gates, a fresh active email-owner heartbeat, API/edge
identity, the existing routing, and the IDs/image digests/runtime revisions of
all eight application containers. Email must have one running consumer and
WeChat must remain stopped. The protected baseline contains no recipient,
message, credential or raw configuration values and is saved before checkout.

Preparation builds the new exact image and creates a protected business-schema
backup while email continues running. The candidate must use exactly the
already-applied schema fingerprint; this recovery cannot introduce schema
changes, reimport D1, rotate identities, reset caches, or restore a database.
Immediately before mutation it rechecks the baseline, acquires the existing
exclusive delivery fence, and compares the old runtime commit, gates and
control timestamp atomically. Only a successful compare-and-set closes delivery
and marks runtime mutation as started. A stale request cannot pause a later
operator's state.

Preflight/build failures leave the running email service alone. After checkout,
source restoration is allowed only while the original container and database
identities are demonstrably unchanged; a missing runner marker alone is
insufficient. Once the fence commits, failure retains evidence and safely
pauses delivery. Do not blindly restore the previous mixed component versions.

The remaining deployment and acceptance steps are unchanged: protected Pi
preflight/apply, exact Web/Host/Airflow/Sender identities, production API
transaction rollback probe, natural cycles for all 26 active venues, and real
natural email and WeChat receipts. Baoan's approved feature rollback retires
its business route and observations while preserving its historical database
rows; the Pi candidate and acceptance contract are Dashah-only. The Pi gate is
retained rather than skipped. Shared WeChat groups stay paused and the dedicated
Dashah free group retains its existing routing.

There is a delivery interruption after the fence. The established cutover step
resumes email once the new Host/edge are ready; WeChat becomes eligible only
after the full component deployment and exact Sender/API checks. A later
technical failure safely pauses both channels. If all technical checks pass
and only natural delivery receipts are absent, acceptance stays pending and
leaves the healthy consumers active. Resume the same run's failed jobs to
preserve the acceptance window; never manufacture a test notification.

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

## Notification reliability releases (0.8.2 and later)

A change under `src/wechat_airflow/host_core/` requires `scope=all sender=true`
and the protected **ship** lifecycle, not an Airflow-only apply. The lifecycle
builds and checks the new Host Core image, fences delivery, updates all consumers,
then requires exact identities and the API transaction rollback probe before
activating workers and tagging. Natural venue cycles and email/WeChat receipts
are observed in production and do not hold the tag. A verified
existing migration checkpoint skips the D1 import. Never clear the checkpoint or
reimport the archive to get a later release through its gate.

Collection, enqueue and delivery are separate signals. In particular, a green
venue DAG is not a delivery receipt. Enqueue failures are recorded as hashed
`wechat_delivery_incidents` and checked independently by business acceptance;
new terminal send failures and unknown submissions fail the release health gate.
The website's latest venue email receipt is channel-wide, not the logged-in
subscriber's receipt or a WeChat receipt. No effective subscription means no
email will be generated; do not automatically revive cancelled/expired rules.

Expired availability lines are removed individually at enqueue and dispatch;
malformed lines remain protocol errors. Sender records `preparing` before UI
navigation and durably switches to `dispatching` immediately before the first
irreversible send action. Only proven `not_submitted` outcomes get bounded
retries. Historical `dispatching`/`submission_unknown` rows are never replayed.
Read-only status reconciliation requires both idempotency key and payload hash,
and can only mark a message sent when the device ledger confirms it. Missing
or uncertain device evidence stays quarantined for operator review. Never send
synthetic notifications or reset old queue/cache entries as acceptance.
