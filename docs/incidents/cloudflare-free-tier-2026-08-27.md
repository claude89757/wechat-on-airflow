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

- Shenzhen Bay remains every 15 seconds with four parallel day tasks.
- Greater Bay Area remains every 30 seconds with three parallel day tasks.
- The five existing single-task 30-second venue watchers remain every 30 seconds.
- Shenzhen Sports Center remains every minute.
- Every real slot, venue-health, or error change is forwarded immediately.
- An unchanged venue/task scope still forwards a heartbeat every five minutes,
  below the Web application's ten-minute freshness threshold.
- Availability that disappears and then reappears is forwarded on the first
  matching poll.
- Subscriber email remains Web-owned and continues to drain after a forwarded
  observation.
- No production database records are deleted by this repair.

## Request budget

At the configured schedules, the theoretical maximum observation publication
rate is 47,520 Worker requests per day before task runtime and scheduler overlap
reduce it:

- Shenzhen Bay: `4 × 86,400 / 15 = 23,040`;
- Greater Bay Area: `3 × 86,400 / 30 = 8,640`;
- five single-task 30-second watchers: `5 × 86,400 / 30 = 14,400`;
- Shenzhen Sports Center: `86,400 / 60 = 1,440`.

This intentionally preserves the product polling contract and leaves 52,480
requests of the Workers Free 100,000-request daily allowance for the UI, cron,
and other API traffic. A continuously open browser identity previously issued
up to 2,880 bootstrap requests per day. The client now coalesces that to at most
720 network requests per day, reuses cached data while the document is hidden,
and invalidates immediately after subscription or priority-tier changes.

The Worker Cache API and client cache reduce D1/CPU work and UI request volume;
they do not change the Airflow polling schedules. Production request metrics
must still be monitored because many simultaneously open browser identities can
consume the remaining Workers request allowance even when D1 is healthy.

## Repair

### Observation ingest

`observation_ingest_state` stores one indexed fingerprint and last-forwarded
time for each venue/Airflow-task scope. The shared publisher obtains the current
Airflow task ID without changing any watcher schedule or watcher call site.
`checked_at` is deliberately excluded from the fingerprint; venue health, error
state, and normalized slot identity remain in it. A changed fingerprint bypasses
the throttle immediately. An unchanged fingerprint receives a successful
deduplicated response until the five-minute heartbeat expires.

A stable task scope is required for correctness. It prevents parallel day tasks
from overwriting one another and ensures an available → empty → available state
transition is never hidden by a recent fingerprint from a different task.
Older Airflow publishers without the new field are accepted through a fail-open
compatibility scope until the matching Airflow commit is deployed.

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
seconds under a private URL on the Worker custom-domain origin. The path contains
only a one-way digest derived from the verification receipt and the existing
pepper; receipt tokens never appear in the cache URL. Browser responses remain
`no-store`, and subscription mutations invalidate both the caller's private
cache entry and the anonymous aggregate entry.

The browser client also coalesces bootstrap requests for the same identity for
120 seconds. It retains the existing UI refresh loop, serves the in-memory value
without a network call during the cache window, reuses the last value while the
page is hidden, and invalidates immediately after any dashboard-changing user
action. Dashboard counters can therefore be up to two minutes old; venue polling
and notification generation remain real-time at their original schedules.

The global submitted-reminder metric now counts one `sent`
`email_delivery_claims` row per digest for the Shanghai delivery day, backed by
`email_delivery_claims_day_status_idx`, instead of repeatedly scanning and
deduplicating notification rows.

## Acceptance

Before any production apply, the exact branch commit must pass `CI / verify` and
protected release preflight. The Worker migration and the Airflow shared
publisher must ship from the same exact commit. After an approved exact-commit
deploy, observe at least three natural venue cycles and a full 24-hour Cloudflare
window.

Target outcomes:

- no change to any active venue DAG schedule;
- changed availability appears in the Web notification pipeline on the first
  matching poll;
- an available → empty → available transition is visible without waiting for the
  five-minute heartbeat;
- venue health never becomes stale because of deduplication;
- delivery-status confirmation normally updates within ten minutes;
- Workers `exceededCpu` remains zero during the observation window;
- total Worker requests remain below 80,000 per day as an operational warning
  threshold, leaving margin below the Free hard limit;
- D1 rows read remain below 2,000,000 per day;
- D1 rows written remain below 30,000 per day;
- no real verification, venue email, or WeChat probe is sent without separate
  approval.

If the usage targets are not met, use D1 query metrics and Worker invocation
status to identify the remaining query before considering a paid-plan upgrade.
Do not reduce Airflow venue polling frequency as a fallback.

## Rollback

Rollback is the previous exact Worker and Airflow commit. The new D1 table and
index are additive and can remain unused after a rollback; no destructive
reverse migration is required.
