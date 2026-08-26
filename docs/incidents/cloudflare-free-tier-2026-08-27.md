# Cloudflare Free-Tier Remediation — 2026-08-27

## Incident

The production account reported repeated Workers CPU-limit events and recurring
D1 free-tier overage. The affected runtime is the single Cloudflare Worker that
owns the public Web application, subscription matching, D1 notification outbox,
and Tencent SES delivery lifecycle.

The investigation found three independent amplifiers:

1. every Airflow venue poll performed a full D1 ingest even when the normalized
   availability payload had not changed;
2. every successful observation synchronously launched delivery reconciliation,
   while the one-minute cron also ran both the new and legacy reconcilers;
3. the front-end refresh loop repeatedly executed personalized bootstrap queries
   and identity activity writes, and the aggregate submitted metric scanned the
   notification outbox by provider timestamp.

The venue polling schedules are not the problem to solve. They are a product
latency contract and remain unchanged.

## Invariants

- Shenzhen Bay remains every 15 seconds.
- The other active venue watchers remain every 30 seconds unless their existing
  repository contract already specifies another value.
- Every real slot, venue-health, or error change is forwarded immediately.
- An unchanged venue scope still forwards a heartbeat every five minutes, below
  the Web application's ten-minute freshness threshold.
- Subscriber email remains Web-owned and continues to drain after a forwarded
  observation.
- No production database records are deleted by this repair.

## Repair

### Observation ingest

`observation_ingest_state` stores one indexed fingerprint and last-forwarded
time for each venue/date scope. `checked_at` is deliberately excluded from the
fingerprint; venue health, error state, and normalized slot identity remain in
it. A changed fingerprint bypasses the throttle immediately. An unchanged
fingerprint receives a successful deduplicated response until the five-minute
heartbeat expires.

This keeps all Airflow API polling intact while replacing repeated full
subscription scans, slot upserts, outbox dedupe writes, and outbox drains with a
single primary-key D1 lookup.

### Delivery lifecycle

The synchronous reconciliation attached to every observation is removed. The
recent-first reconciler runs every five minutes with a batch of five per queue.
Legacy housekeeping runs separately at minute 17 of each hour, so it no longer
overlaps the five-minute path. The protected manual reconciliation endpoint uses
the same bounded batch.

### Dashboard

Bootstrap responses are cached in the Cloudflare Cache API for at most 120
seconds under a synthetic key derived from the verification receipt and the
existing pepper. Receipt tokens never appear in the cache URL. Browser responses
remain `no-store`, and subscription mutations invalidate both the caller's
private cache entry and the anonymous aggregate entry.

The global submitted-reminder metric now counts one `sent`
`email_delivery_claims` row per digest for the Shanghai delivery day, backed by
`email_delivery_claims_day_status_idx`, instead of repeatedly scanning and
deduplicating notification rows.

## Acceptance

Before any production apply, the exact branch commit must pass `CI / verify` and
Web deployment preflight. After an approved exact-commit deploy, observe at least
three natural venue cycles and a full 24-hour Cloudflare window.

Target outcomes:

- no change to any active venue DAG schedule;
- changed availability appears in the Web notification pipeline on the first
  matching poll;
- venue health never becomes stale because of deduplication;
- delivery-status confirmation normally updates within ten minutes;
- Workers `exceededCpu` remains zero during the observation window;
- D1 rows read remain below 2,000,000 per day;
- D1 rows written remain below 30,000 per day;
- no real verification, venue email, or WeChat probe is sent without separate
  approval.

If the usage targets are not met, use D1 query metrics and Worker invocation
status to identify the remaining query before considering a paid-plan upgrade.
Do not reduce Airflow venue polling frequency as a fallback.

## Rollback

Rollback is the previous exact Worker commit. The new D1 table and index are
additive and can remain unused after a Worker rollback; no destructive reverse
migration is required.
