# ADR 0015: Event-driven observations and manual dashboard refresh

## Status

Accepted for the Cloudflare Workers Free production architecture.

## Context

Venue adapters must continue polling upstream booking systems at their configured
cadence so a real availability, health, or error transition is detected on the
first matching poll. Forwarding every unchanged poll—or periodically forwarding
an unchanged heartbeat—creates avoidable Worker invocations and D1 reads and
writes. Browser polling has a similar cost problem and cannot prove that an
Airflow watcher is alive; it only rereads the last state already stored by the
Web application.

Removing all unchanged publications introduces one correctness risk: a user may
create a subscription after a matching slot was already observed. If the slot
remains unchanged, a purely fingerprint-based publisher would not send it again
just to reevaluate the new subscription.

## Decision

1. Airflow retains every existing upstream venue polling schedule.
2. The Airflow publisher stores one atomic local fingerprint per venue/task
   scope. A new slot set, health state, or error state is forwarded immediately.
   A fingerprint that has already succeeded is suppressed indefinitely; a failed
   fingerprint is retried on a bounded two-minute backoff.
3. The Worker applies the same event-driven fingerprint rule as defense in
   depth. There is no unchanged observation heartbeat and no D1 liveness write.
4. Every accepted changed observation replaces a bounded current snapshot for
   its venue/task scope. The table contains only current normalized slots and
   status, not an append-only observation history.
5. Subscription creation immediately matches the new subscription against the
   bounded current snapshots. Existing unique event/outbox constraints preserve
   notification deduplication. Therefore a new subscription does not depend on
   replaying an unchanged venue observation.
6. The dashboard loads once when the page or identity changes. Subsequent
   network reads occur only after an explicit refresh or a state-changing user
   action. The refresh control bypasses both client and edge caches.
7. Venue status shown in the dashboard is explicitly the **last known state**.
   User refresh reads the latest stored record; it does not trigger an upstream
   venue crawl and is not used as an operational liveness signal.
8. Airflow/Worker health remains an operational concern verified by protected
   GitHub production diagnostics, logs, and exact-commit health checks rather
   than customer browser traffic.

## Consequences

- Unchanged observations generate zero Airflow-to-Worker traffic after the
  initial state has been recorded.
- D1 writes occur for real state changes, subscription mutations, delivery
  lifecycle changes, and bounded maintenance—not for liveness heartbeats.
- A restart or loss of the local fingerprint file safely causes a one-time full
  reseed. Worker-side deduplication prevents duplicate business processing when
  its persisted fingerprint already matches.
- A key-version/state-version bump during this rollout intentionally causes one
  reseed per task scope so the new current snapshot table is populated.
- Dashboard data can remain unchanged until the user presses refresh. All copy
  and labels must describe it as last known data.
- If Airflow is unavailable, a manual refresh can still return a successful but
  old record. Operational monitoring must detect that condition separately.

## Rejected alternatives

- **Keep sparse heartbeats:** cheaper than the original implementation, but still
  spends quota solely to refresh a liveness timestamp and couples product data
  to monitoring.
- **Let browsers refresh automatically:** cost scales with open tabs and users,
  while providing no evidence that venue watchers are running.
- **Rerun full venue processing after every subscription mutation:** requires a
  periodic coordination signal or a replay of upstream observations. The bounded
  current snapshot gives the same subscription correctness with fewer moving
  parts and predictable D1 cost.
