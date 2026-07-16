# Venue Email Notifications

Each active Shenzhen venue watcher uses its own Airflow Variable:

- `SZW_EMAIL_LIST`: Shenzhen Bay subscribers.
- `JDWX_EMAIL_LIST`: Jindi subscribers.
- `SYSH_EMAIL_LIST`: Shangyue Shahe subscribers.
- `TOPS_EMAIL_LIST`: TOPS subscribers.
- `TYZX_EMAIL_LIST`: Shenzhen Sports Center subscribers.

Each variable must be a JSON list of email addresses. There is no global recipient list and no fallback to another venue's list. A venue with a missing, empty, or invalid list does not send email; its failure is written to the fallback outbox instead.

Each venue watcher persists its detection cache first and then calls the common venue email helper. All newly detected slots from one watcher run are combined into one Tencent SES request. This prevents one-email-per-slot bursts from triggering per-recipient frequency limits.

Email content is intentionally terse. The subject contains the first slot, and the plain-text body contains one line per slot in the form `court date weekday time-range`. It does not include notification counts, instructions, subscription text, or booking disclaimers.

The active Tencent SES template ID is stored in `VENUE_EMAIL_TEMPLATE_ID`. This allows a newly reviewed template to be activated without redeploying the DAG code.

The helper validates and deduplicates recipients without printing addresses. A missing or invalid recipient list, Tencent SES exception, or `success: false` response is recorded in the Airflow-managed `EMAIL_SEND_FALLBACK_OUTBOX` variable and does not fail the venue DAG. The outbox retains 200 entries by default; override that limit with `EMAIL_SEND_FALLBACK_MAX_ITEMS`.
