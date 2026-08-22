# ADR 0010: Tiered Subscriber Email And Priority Invites

- Status: Accepted
- Date: 2026-08-22

## Context

The subscription Worker can generate many time-sensitive venue-reminder emails
for one recipient in a day. A global Tencent SES budget protects the provider
account but does not prevent one highly active subscriber from consuming a
disproportionate share or receiving excessive mail. The product also needs a
small priority cohort without introducing passwords or a full account system.

## Decision

- Apply a per-recipient Shanghai-calendar-day cap to provider digest deliveries.
- Start with 30 deliveries per day for standard users and 100 for priority users.
  Both are configuration values, are returned to the Web client for transparent
  display, and should be reviewed from delivery, suppression, complaint, and
  engagement data.
- Keep aggregating all currently claimed slot rows for a recipient into one
  digest; the digest, not each slot, consumes one unit.
- Suppress over-cap reminders instead of carrying them to the next day, because
  venue availability is time-sensitive and deferred mail can be misleading.
- Exclude verification codes from the cap.
- Resolve the tier at send time. Priority users are ordered first when the
  existing global provider budget is constrained.
- Use an atomic D1 delivery reservation to prevent overlapping Worker drains
  from racing past a recipient's limit.
- Bind priority status to the normalized verified email. A successful upgrade
  remains active until an operator explicitly revokes it; invite expiry controls
  only the redemption window.
- Provision one-time expiring invite phrases through an authenticated internal
  endpoint. Generate two independently random, human-readable word segments
  plus a six-character ambiguity-free random suffix, return plaintext once, and
  store only an HMAC-SHA-256 hash.
- Prefer dedicated `INVITE_CODE_PEPPER` and `INVITE_ADMIN_TOKEN` Worker Secrets.
  For backwards-compatible rollout, when either is absent the deployment entry
  uses the existing `VERIFICATION_PEPPER` for invite HMAC and
  `AIRFLOW_PUSH_TOKEN` for the internal provisioning endpoint. Dedicated secrets
  can be added later without downtime or data migration.
- Require a valid verified-email receipt to redeem and rate-limit attempts by
  both verified identity and hashed IP.

## Consequences

- Email volume and message fatigue are bounded per recipient.
- Priority users gain a larger cap and queue precedence without bypassing the
  weather gate, verification requirements, or the global provider budget.
- Over-cap events are intentionally lost; WeChat remains independent and is not
  controlled by these email tiers.
- Operations must apply the D1 migration before deployment; the existing Worker
  secret set is sufficient for initial rollout, while dedicated invite secrets
  remain a recommended hardening step.
- Invite codes are not recoverable from D1. Lost plaintext codes must be
  replaced, not retrieved.
