# ADR 0013: Priority Email Ten-Second Lead

- Status: Accepted
- Date: 2026-08-28

## Context

Subscriber reminder digests already resolve each normalized verified email to a
standard or priority delivery tier. Priority recipients are ordered first and
receive a larger daily allowance, but concurrent Cloudflare Worker drains can
still submit a standard reminder immediately after, or alongside, a priority
reminder. The product requires a visible delivery advantage: priority reminder
submissions must complete first, followed by a ten-second lead before standard
reminder submission begins.

The change must preserve the existing Airflow venue polling schedules, Web-owned
D1 outbox, provider budget, verification-email availability, and Cloudflare Free
resource constraints.

## Decision

- Apply the lead only to subscriber venue-reminder digests. Verification codes,
  subscription-expiry reminders, and other explicitly categorized system mail
  remain immediate.
- Before a standard reminder calls Tencent SES, query D1 for active priority
  reminder work and the latest completed priority delivery claim.
- Treat priority outbox rows in `processing`, or due rows in `pending`/`retry`,
  as outstanding. A standard reminder rechecks while any such row exists.
- After the latest priority SES submission attempt finishes, wait until the full
  ten-second interval has elapsed. A provider-accepted attempt and a failed
  attempt both close that attempt's priority window; a later priority retry
  opens a new window and resets the lead.
- Reuse `email_delivery_claims.updated_at` and the existing delivery-day indexes
  as the completion clock. No D1 schema migration, new cron, or Airflow schedule
  change is required.
- Bound one Worker invocation's wait to fifteen seconds. If priority work remains
  active beyond that bound, fail the standard submission before the provider
  call so the existing outbox retry path defers it rather than sending early.
- Never log an email address while evaluating or enforcing the gate.

## Concurrency Semantics

The D1 query coordinates independent Worker drains. It covers priority work that
was already queued, leased, or completed when the standard reminder checks the
lane. Work created after a standard reminder has passed its final gate cannot be
predicted; it belongs to the next delivery wave. Within each observable wave,
priority submissions finish first and standard submissions start no earlier
than ten seconds after the most recent priority completion.

## Consequences

- Priority subscribers receive a deterministic ten-second submission lead over
  standard subscribers in the same observable delivery wave.
- Standard reminders may arrive later than ten seconds when priority traffic is
  still active or a Worker invocation reaches its bounded wait. They are never
  intentionally submitted early.
- The gate adds only bounded, indexed D1 reads to reminder delivery. Waiting is
  asynchronous and does not change venue-inspection frequency.
- Verification and lifecycle mail are isolated from reminder-lane contention.
- Production acceptance uses unit/type/build checks, exact-commit Web health,
  and natural venue publication cycles. Routine verification must not send a
  real email or inject a production slot.
