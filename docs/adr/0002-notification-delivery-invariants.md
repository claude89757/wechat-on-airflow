# ADR 0002: Notification Delivery Invariants

- Status: Accepted
- Date: 2026-07-17

## Decision

Each venue owns an independent recipient Variable. The detection cache is
persisted before delivery. Email and WeChat are independent best-effort
channels, and each channel records deduplicated failures in its own bounded
outbox without failing the venue DAG.

## Consequences

- A WeChat outage cannot delay email.
- An email outage cannot cause repeated detection notifications.
- Missing recipient configuration is visible in the email outbox and never
  falls back to another venue.
- Outboxes are diagnostic state and are not automatic retry queues.
- Tests replace both external delivery clients.
