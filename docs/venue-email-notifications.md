# Venue Email Notifications

All active Shenzhen venue watchers share one Airflow Variable:

- `SZ_TENNIS_EMAIL_LIST`: JSON list containing the subscribers for all active venues.

The legacy `SZW_EMAIL_LIST` and `JDWX_EMAIL_LIST` variables are retained only for rollback and are not read by active DAG code.

Each venue watcher persists its detection cache first and then calls the common venue email helper. All newly detected slots from one watcher run are combined into one Tencent SES request. This prevents one-email-per-slot bursts from triggering per-recipient frequency limits.

The helper validates and deduplicates recipients without printing addresses. A missing or invalid recipient list, Tencent SES exception, or `success: false` response is recorded in the Airflow-managed `EMAIL_SEND_FALLBACK_OUTBOX` variable and does not fail the venue DAG. The outbox retains 200 entries by default; override that limit with `EMAIL_SEND_FALLBACK_MAX_ITEMS`.
