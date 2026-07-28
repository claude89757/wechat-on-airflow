# ADR 0007: Cloudflare Web Subscriptions

## Status

Accepted.

## Context

Users need a mobile interface for future tennis availability alerts without an
account system. The interface must verify email ownership, accept venue and
time-window preferences, show service health, and avoid exposing current
availability. Existing Airflow email lists and fixed venue filters are not a
user subscription model.

## Decision

Serve the React application and API from one Cloudflare Worker at
`zacks.claude89757.cc`. Store verification challenges, long-lived browser
receipts, subscriptions, observed slot keys, and notification outbox records in
D1. Send verification and alert messages through the existing approved Tencent
SES template.

Airflow remains the booking-source integration layer. Each venue watcher
publishes raw slots to the Worker after completing legacy notification
delivery. Publication is bearer-authenticated, bounded by a short timeout, and
best effort. It never changes the legacy deduplication cache or DAG result.

The Worker matches slot overlap against active subscriptions and writes a
unique `(subscription_id, event_key)` before sending. Email delivery uses a
leased retry outbox with bounded attempts. Subscription alerts contain only
venue, date, weekday, and time.

Email ownership produces an opaque 180-day receipt. The browser stores up to
three receipts locally, while D1 stores only receipt hashes. Public dashboard
responses contain aggregate counts and masked email addresses only.

## Consequences

- A Cloudflare outage does not delay legacy Airflow email or WeChat delivery.
- Arbitrary user time ranges are independent of legacy venue filters.
- Existing slots can notify a newly created subscription on its next scan, but
  the same subscription-slot event cannot be sent twice.
- D1 is the authoritative subscription store; Airflow Variables hold only the
  ingestion endpoint and shared token.
- Cloudflare and Tencent SES credentials remain deployment secrets and are
  never committed.
