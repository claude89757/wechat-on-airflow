#!/usr/bin/env bash
set -euo pipefail

: "${CLOUDFLARE_ACCOUNT_ID:?}"
: "${CLOUDFLARE_API_TOKEN:?}"

wrangler() {
  (cd webapp && npx wrangler "$@")
}

# Keep diagnostics aggregate/redacted: no recipient addresses, subjects, bodies,
# request IDs, provider message IDs, or delivery reasons are printed.
printf '%s\n' '__EMAIL_DELIVERY_METRICS__'
wrangler d1 execute zacks-tennis-alerts --remote --json --command "
WITH day AS (
  SELECT datetime('now','+8 hours','start of day','-8 hours') AS start_utc
)
SELECT
  COUNT(DISTINCT CASE WHEN provider_submitted_at >= day.start_utc THEN message_id END) AS submitted_today,
  COUNT(DISTINCT CASE WHEN status='delivered' AND provider_delivered_at >= day.start_utc THEN message_id END) AS delivered_today,
  COUNT(DISTINCT CASE WHEN status='failed' AND provider_submitted_at >= day.start_utc THEN message_id END) AS failed_today,
  COUNT(DISTINCT CASE WHEN status='submitted' AND provider_submitted_at >= day.start_utc THEN message_id END) AS pending_today,
  COUNT(DISTINCT CASE WHEN provider_submitted_at >= day.start_utc AND provider_checked_at IS NOT NULL THEN message_id END) AS checked_today,
  COUNT(DISTINCT CASE WHEN status='submitted' AND provider_submitted_at >= day.start_utc AND provider_checked_at IS NULL THEN message_id END) AS never_checked_today,
  COUNT(DISTINCT CASE WHEN status='submitted' AND provider_submitted_at >= day.start_utc AND provider_status='not_found' THEN message_id END) AS not_found_today,
  COUNT(DISTINCT CASE WHEN status='submitted' AND provider_submitted_at >= day.start_utc AND provider_status LIKE 'check_error:%' THEN message_id END) AS check_error_today,
  COUNT(DISTINCT CASE WHEN provider_submitted_at >= day.start_utc AND message_id LIKE 'worker:%' THEN message_id END) AS placeholder_message_ids_today
FROM notification_outbox, day;
"

printf '%s\n' '__PROVIDER_STATUS_BREAKDOWN__'
wrangler d1 execute zacks-tennis-alerts --remote --json --command "
WITH day AS (
  SELECT datetime('now','+8 hours','start of day','-8 hours') AS start_utc
)
SELECT
  status,
  COALESCE(provider_status,'(null)') AS provider_status,
  COUNT(DISTINCT message_id) AS messages
FROM notification_outbox, day
WHERE provider_submitted_at >= day.start_utc
GROUP BY status, COALESCE(provider_status,'(null)')
ORDER BY messages DESC, status, provider_status;
"

printf '%s\n' '__PENDING_AGE__'
wrangler d1 execute zacks-tennis-alerts --remote --json --command "
WITH day AS (
  SELECT datetime('now','+8 hours','start of day','-8 hours') AS start_utc
)
SELECT
  MIN(provider_submitted_at) AS oldest_submitted_at,
  MAX(provider_submitted_at) AS newest_submitted_at,
  MIN(provider_checked_at) AS oldest_checked_epoch_ms,
  MAX(provider_checked_at) AS newest_checked_epoch_ms,
  COUNT(DISTINCT message_id) AS pending_messages
FROM notification_outbox, day
WHERE status='submitted' AND provider_submitted_at >= day.start_utc;
"

printf '%s\n' '__RECONCILIATION_BACKLOG__'
wrangler d1 execute zacks-tennis-alerts --remote --json --command "
WITH bounds AS (
  SELECT
    datetime('now','-48 hours') AS recent_cutoff,
    datetime('now','-30 days') AS retention_cutoff
)
SELECT
  COUNT(DISTINCT CASE
    WHEN provider_submitted_at >= bounds.recent_cutoff THEN message_id END
  ) AS recent_pending,
  COUNT(DISTINCT CASE
    WHEN provider_submitted_at >= bounds.retention_cutoff
     AND provider_submitted_at < bounds.recent_cutoff THEN message_id END
  ) AS queryable_backlog,
  COUNT(DISTINCT CASE
    WHEN provider_submitted_at < bounds.retention_cutoff THEN message_id END
  ) AS retention_expired,
  COUNT(DISTINCT message_id) AS total_pending,
  MIN(provider_submitted_at) AS oldest_pending_at,
  MAX(provider_submitted_at) AS newest_pending_at
FROM notification_outbox, bounds
WHERE status='submitted'
  AND message_id IS NOT NULL
  AND message_id NOT LIKE 'worker:%';
"

printf '%s\n' '__VENUE_NOTIFICATION_COVERAGE__'
wrangler d1 execute zacks-tennis-alerts --remote --json --command "
SELECT
  COUNT(*) AS venues,
  SUM(CASE WHEN last_notification_at IS NOT NULL THEN 1 ELSE 0 END) AS venues_with_confirmed_delivery,
  MAX(last_notification_at) AS latest_confirmed_delivery_at
FROM venue_status;
"
