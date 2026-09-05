# ADR 0013: Host Core-only operation and evidence-driven acceptance

Status: implementation decision approved by owner, 2026-09-05.

The owner requires full Host Core migration without legacy runtime compatibility.
This supersedes ADR 0012's dual-writing and automatic legacy recovery steps.
Preserving source data does not mean retaining a compatibility backend.

PostgreSQL `zacks` owns identity, subscription eligibility, current observations,
semantic event identities, outboxes, delivery attempts, quotas, device intents,
booking-link cooldowns and the durable delivery-control fence. Redis is only the
Celery broker, not notification truth. Airflow retains its collection schedules;
slow device sends move to a dedicated consumer. A process-independent device
ledger complements—not replaces—host outbox ownership.

We choose honest uncertain-send quarantine rather than an impossible blanket
exactly-once claim for external SES/UI operations without atomic provider
idempotency. The device ledger prevents repeating the same known intent after
restart. Before-send expiry, current availability and subscription cancellation
are rechecked. Weather is evaluated by booking date. The edge has no D1 binding
or business Cron. A maintenance-only migration artifact is never a fallback.

Activation is a durable irreversible ownership milestone, not data deletion.
After activation, failure pauses Host Core and a repaired exact commit rolls
forward. Restoring old D1 state over new writes is prohibited. A production API
transaction probe rolls back all test writes; it proves production DB/API logic,
not public browser interaction or real email receipt. Independent natural
provider/device delivery evidence and complete per-venue cycles are mandatory.

Tradeoffs: a single-host PostgreSQL failure still affects collection and business
operations; edge outage still affects users changing subscriptions. The current
release emphasizes correctness and deployability before adding multi-host HA.
