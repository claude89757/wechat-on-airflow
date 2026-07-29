# ADR 0008: Web-Only Subscriber Email

- Status: Accepted
- Date: 2026-07-30

## Context

Airflow previously sent venue email to five fixed recipient Variables while the
Cloudflare application independently sent verified subscription alerts. The
two delivery models produced different filtering rules, duplicated sender
configuration, and exposed fixed-recipient batches to Tencent SES frequency
limits.

The Web subscription model now owns recipient verification, venue selection,
time windows, validity, deduplication, and bounded delivery retries. Keeping a
second Airflow email path no longer has a product or operational owner.

## Decision

- The Cloudflare application is the only owner of subscriber email delivery.
- Airflow does not read fixed recipient lists, load Tencent SES credentials, or
  send venue email directly.
- Every venue watcher publishes raw observations to the Web application before
  attempting best-effort WeChat delivery.
- The Worker matches active subscriptions and owns the retrying D1 email
  outbox. Observation publication remains bounded and cannot fail a venue DAG.
- Airflow keeps its WeChat deduplication cache and incident outbox. The retired
  Airflow email outbox is preserved as historical evidence and is never
  replayed automatically.

## Consequences

- A WeChat or Android device outage cannot delay Web subscription email.
- Users receive email only for verified Web subscriptions and their selected
  venue, time, and validity rules.
- Removing an Airflow fixed-recipient Variable cannot affect subscriber email.
- A Cloudflare ingestion outage can delay subscriber email, but does not fail
  venue DAGs or block best-effort WeChat delivery.
- Airflow no longer requires the Tencent Cloud Python SDK or venue email sender
  secrets.
