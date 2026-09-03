# ADR 0012: Airflow-Host Notification Core

- Status: Accepted
- Version: 0.7.0
- Date: 2026-09-03
- Supersedes delivery ownership in ADR 0007, ADR 0008, and PR #168

## Context

The Cloudflare Web application accumulated responsibility for subscription
storage, observation matching, subscriber-email outboxes, Tencent SES delivery
and reconciliation, dashboard aggregates, and a Web-subscription gate in front
of the independent Airflow-to-Android WeChat channel.

This made the D1 Free daily row-read allowance a shared failure domain. When D1
stopped accepting queries, existing subscriber email stopped and the stale
fail-closed WeChat gate could also suppress a healthy Android sender. The venue
pollers, PostgreSQL 17, Redis, Celery workers, and Android sender were still
available on the Airflow side.

## Decision

The Airflow production host owns the notification data plane:

- PostgreSQL schema `zacks_core` is the durable system of record for the local
  subscription replica, subscription-event deduplication, venue state, email
  outbox, provider state, quotas, and incidents.
- `zacks-notification-api` receives authenticated observations over the Docker
  network and transactionally matches them to the local subscription snapshot.
- `zacks-notification-worker` synchronizes a bounded active-subscription
  snapshot, sends Tencent SES email, and reconciles provider delivery status.
- Redis database 1 is an optional wake-up/cache plane. PostgreSQL constraints,
  transactions, leases, and advisory locks own correctness.
- Existing Airflow-to-Android WeChat delivery remains on the Airflow side. A
  fresh authoritative `allowed=false` gate can suppress a venue; missing,
  stale, or non-authoritative gate state fails open.
- Cloudflare is reduced to the public edge and a temporary enrollment
  compatibility source. It is not in the observation, matching, email-send,
  email-reconcile, or WeChat-decision hot path after cutover.

The first release keeps the current Web enrollment API and periodically imports
active subscriptions plus recent `subscription_events`. This permits a
reversible cutover without changing browser receipts or asking users to verify
again. A subsequent Web migration may move enrollment behind the existing
Cloudflare Tunnel and retire D1 after the rollback window.

## Reliability rules

1. Airflow writes observations to local PostgreSQL before any notification
   delivery.
2. A unique `(subscription_id, event_key)` record prevents duplicate subscriber
   alerts across the D1-to-PostgreSQL cutover.
3. Email workers use PostgreSQL row locks and a singleton advisory lock.
4. Redis failure only removes immediate wake-ups; bounded PostgreSQL polling
   continues.
5. A worker that loses a `processing` lease does not blindly resend. The row is
   marked `uncertain` and an incident is created because the provider may have
   accepted the request before the process failed.
6. Existing D1 subscription events are imported while venue DAGs are paused,
   before the observation endpoint is switched.
7. No release or health check sends a real email or WeChat message.

## Consequences

- A Cloudflare/D1 outage cannot stop delivery for subscriptions already present
  in the last successful local snapshot.
- New verification, subscription, cancellation, or priority changes remain
  unavailable during a Cloudflare outage until Web enrollment is moved locally.
- PostgreSQL becomes the notification system's durable dependency. This does
  not add a new host failure domain because Airflow already requires the same
  PostgreSQL service.
- D1 is retained read-only during the rollback window and is not deleted as
  part of the 0.7.0 release.

## Rollback

Set `ZACKS_CORE_DELIVERY_MODE=shadow`, restore
`WEBAPP_OBSERVATION_API_URL` from
`ZACKS_CORE_PREVIOUS_OBSERVATION_API_URL`, and restart the two core services.
The additive `zacks_core` schema remains for evidence and can be left unused.
Rollback does not delete D1 or PostgreSQL records.
