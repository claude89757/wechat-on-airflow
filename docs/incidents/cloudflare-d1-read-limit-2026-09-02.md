# Cloudflare D1 Daily Read-Limit Incident — 2026-09-02

## Status

Production Airflow host access, SSH authentication, and the public Web entrypoint
remain reachable. The outage is inside the Cloudflare Worker data path: D1 has
exhausted the account's Workers Free daily row-read allowance and rejects
database queries with Cloudflare error code `7500`.

Until the quota resets, D1-backed Web APIs, observation ingestion, delivery
reconciliation, subscription data, and admin metrics can return HTTP 500. Static
assets, `/api/healthz`, or an already cached page can still appear available, so
the symptom can look like a partial server outage.

The remediation deliberately remains on Workers Free. It does not reduce any
venue's upstream polling frequency and does not send a real email or WeChat
probe during release.

## Evidence

Read-only production diagnosis was run against exact main commit
`77bd0adb76b1ca716bd928705dddae78b7ea76ac`.

- Ops diagnosis run `33614031324` reached the production host and completed the
  authenticated Web probe, but `POST /api/internal/reconcile-deliveries`
  returned HTTP 500 with `D1_ERROR`.
- Protected Web preflight run `33614245883` exposed the upstream Wrangler
  message: `Your account has exceeded D1's free tier daily row read limit` with
  error code `7500`.
- The most recent successful production diagnostic before the outage showed
  individual `notification_outbox` aggregate queries reading approximately
  41,730 to 42,497 rows while returning only a small aggregate result.

The last main commit changed only the Web logo. Its Web deployment completed
successfully on 2026-08-31, and Airflow was not redeployed for that asset-only
release. Restarting Airflow or rolling back the logo does not address this
failure mode.

## Root Cause

Cloudflare began enforcing D1 Free-plan daily limits on 2026-09-01. Production
reached the 5,000,000-row daily read limit because several frequent queries were
not bounded by a suitable index as `notification_outbox` accumulated history:

1. global daily delivery-budget checks filtered only by
   `provider_submitted_at`;
2. per-recipient daily delivery-budget and dashboard checks filtered by email
   plus provider timestamps;
3. delivered-today dashboard checks filtered by status and
   `provider_delivered_at`;
4. delivery reconciliation selected and updated rows repeatedly by
   `message_id` without a `message_id` index;
5. every observation scope still crossed the network at least once every five
   minutes, and an unchanged heartbeat re-entered more Worker layers than needed;
6. the browser's 30-second refresh loop periodically exhausted its short client
   cache and created new personalized bootstrap work;
7. the delivery diagnostic script contained historical aggregate shapes that
   could themselves read a large fraction of the Outbox during an incident.

The earlier free-tier remediation in migration `0009` reduced unchanged
observation ingestion and indexed `email_delivery_claims`. It did not index the
remaining `notification_outbox` access paths or coalesce heartbeats across
parallel Airflow task scopes.

## Free-Tier Remediation

### Indexed Outbox reads

Migration `0016_optimize_notification_outbox_reads.sql` adds three additive,
partial indexes and runs `PRAGMA optimize`:

- `notification_outbox_message_id_lookup_idx` bounds provider-message lookup
  and reconciliation updates;
- `notification_outbox_submitted_at_lookup_idx` bounds current-day global and
  recipient submission counts;
- `notification_outbox_delivered_at_lookup_idx` bounds delivered-today counts.

The indexes exclude rows whose relevant provider fields are still null. This
keeps pending observation records out of the new indexes and limits D1 write and
storage amplification. Migration tests verify the four production query shapes
with `EXPLAIN QUERY PLAN` and reject a full `SCAN notification_outbox`.

### Sparse server liveness, not browser-driven health

A browser refresh cannot prove that an Airflow watcher is alive; it only rereads
whatever D1 already contains. The repair therefore removes frequent per-task
heartbeats but retains one sparse, lightweight liveness update per venue.

The Airflow publisher now keeps an atomic, process-independent fingerprint file
in the shared Airflow logs volume:

- every real slot, health, or error change bypasses throttling immediately;
- unchanged polls do not call the Worker;
- parallel day/task scopes share one venue-level liveness budget;
- at most one unchanged publication per venue is allowed every eight minutes,
  below the existing ten-minute venue-health freshness window;
- after a failed Web publication, unchanged retries are limited to once every
  two minutes while a new state change still bypasses the backoff;
- cached WeChat gate state is retained without rewriting the Airflow metadata
  database on every unchanged response.

When an unchanged publication reaches the Worker, it updates only the indexed
observation timestamp and `venue_status`. It does not rescan subscriptions,
rewrite observed slots, create Outbox rows, reconcile delivery, or fetch a
WeChat gate. A changed fingerprint still enters the complete business path.
Subscription and priority mutations invalidate the observation fingerprints so
a newly eligible subscriber is matched on the next natural venue poll even when
the availability payload itself has not changed.

### User-driven dashboard network refresh

The existing refresh control continues to use `?refresh=1` and bypasses both
client and edge caches. Automatic UI renders reuse the in-memory dashboard for
one day, so the 30-second presentation loop no longer creates periodic network
or D1 work. Verification, identity changes, subscription create/cancel, and
priority redemption invalidate the cache immediately. The private edge cache is
retained for five minutes as a second layer for page loads and concurrent tabs.

### Bounded diagnostics

`diagnose_email_delivery_metrics.sh` now requires an indexed current-day or
retention-window predicate for Outbox aggregates. The only older-than-retention
check is an existence probe with `LIMIT 1`; it no longer calculates an exact
all-history count during routine diagnosis.

### Quota-exhaustion release path

The protected Web release still fails closed for all unexpected database,
authentication, migration, and configuration errors. It tolerates only the
known D1 Free row-read quota message or error code `7500`:

1. build and dry-run the exact main commit;
2. attempt the normal migration listing and apply;
3. if and only if D1 reports the known exhausted quota, defer the migration;
4. deploy the Worker repair and verify its exact commit through `/api/healthz`,
   which does not query D1;
5. deploy the matching Airflow publisher;
6. after D1 accepts queries, the five-minute Worker cron idempotently creates
   the same indexes once, records a schema marker, and resumes normal work.

Schema repair is not executed on the observation request hot path. The normal
D1 migration remains authoritative whenever the database is available.

## Expected Budget

There are currently 26 Web venues. With one unchanged liveness publication per
venue every eight minutes, the theoretical maximum is 4,680 unchanged Worker
requests per day before task runtime and inactive periods reduce it. Each uses a
primary-key state lookup and, only when due, two small state writes. Real changes
add a comparatively small number of full ingests.

The operational acceptance targets remain:

- D1 rows read below 2,000,000 per UTC day;
- D1 rows written below 30,000 per UTC day;
- total Worker requests below 80,000 per UTC day;
- Workers `exceededCpu` equal to zero;
- no active venue DAG polling schedule changed;
- availability and health changes visible on the first matching poll.

## Recovery Procedure

The Free-plan quota resets at `00:00 UTC`; for this incident the next reset is
2026-09-03 00:00 UTC, or 2026-09-03 09:00 in Korea.

The repair can be deployed before the reset because its protected release path
does not require a successful D1 query when the exact quota-specific error is
observed. After the reset:

1. confirm the schema marker and migration `0016` are applied;
2. verify `/api/bootstrap` and an unauthenticated observation probe;
3. observe natural venue cycles without injecting a production slot;
4. run the bounded observation and delivery diagnostics once;
5. monitor a complete UTC day of D1 rows read/written and Worker invocations.

A quota reset alone is not acceptance. Without the code and index repair, the
same workload can exhaust the next UTC day's allowance.

## Rollback

The D1 migration is additive and changes no existing records. The indexes can
remain after an application rollback. The Airflow local state file contains
only fingerprints, timestamps, and the already redacted gate decision; deleting
it causes a safe fail-open full publication on the next poll. A component
rollback must use the prior exact Web and Airflow commits through their protected
workflows.
