# Cloudflare D1 Daily Read-Limit Incident — 2026-09-02

## Status

Production Airflow host access, SSH authentication, and the public Web entrypoint
remain reachable. The outage is inside the Cloudflare Worker data path: D1 has
exhausted the account's Free-plan daily row-read allowance and rejects database
queries with Cloudflare error code `7500`.

Until the quota resets or the account moves to Workers Paid, D1-backed Web APIs,
observation ingestion, delivery reconciliation, subscription data, and admin
metrics can return HTTP 500. Static assets or an already cached page can still
appear available, so the symptom can look like a partial server outage.

No production repair has been deployed from this incident branch.

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
   `message_id` without a `message_id` index.

The earlier free-tier remediation in migration `0009` reduced unchanged
observation ingestion and indexed `email_delivery_claims`. It did not index
these remaining `notification_outbox` access paths.

## Remediation

Migration `0016_optimize_notification_outbox_reads.sql` adds three additive,
partial indexes:

- `notification_outbox_message_id_lookup_idx` bounds provider-message lookup
  and reconciliation updates;
- `notification_outbox_submitted_at_lookup_idx` bounds current-day global and
  recipient submission counts;
- `notification_outbox_delivered_at_lookup_idx` bounds delivered-today counts.

The indexes exclude rows whose relevant provider fields are still null. This
keeps pending observation records out of the new indexes and limits D1 write and
storage amplification.

`tests/webapp_notification_outbox_read_migration_test.py` recreates the existing
production indexes, applies migration `0016`, and verifies with SQLite
`EXPLAIN QUERY PLAN` that the four hot query shapes use the new indexes instead
of `SCAN notification_outbox`.

## Recovery Procedure

The Free-plan quota resets at `00:00 UTC`; for this incident the next reset is
2026-09-03 00:00 UTC, or 2026-09-03 09:00 in Korea. Moving the account to
Workers Paid is the immediate alternative if service must recover before that
reset.

After D1 accepts queries again:

1. let CI verify this branch and review the draft pull request;
2. run protected Web preflight for the exact merged commit;
3. deploy the Web scope so migration `0016` is applied;
4. rerun `webapp-observation-diagnose` and delivery reconciliation diagnosis;
5. monitor D1 rows read and written for a full UTC day, with an operational
   target below 2,000,000 rows read per day and enough margin below the write
   limit.

Do not merge or deploy solely because the quota reset makes the site appear
healthy again. Without the index repair, the same workload can exhaust the next
UTC day's allowance.

## Rollback

The migration is additive and changes no application behavior or existing
records. The indexes can remain after an application rollback. Drop them only
if production measurements show unacceptable write amplification; capture D1
read/write evidence before doing so.
