# Venue status display semantics

The Web venue list separates two different clocks:

- **Inspection cadence** is the configured Airflow schedule: 15 seconds for Shenzhen Bay, 3 minutes for Dashah International, and 1 minute for the other active tennis venues unless the policy declares another exception.
- **Status sync time** is the most recent observation timestamp currently visible through the existing Cloudflare observation heartbeat and dashboard caches.

A card that says `正常 · 1分钟/次` and `状态同步 4分钟前` means that Airflow continues to inspect the venue once per minute while the unchanged Web status snapshot was last forwarded or exposed four minutes ago. It does not mean the venue skipped four inspection cycles.

This presentation is intentionally client-only. It does not add an API endpoint, Worker invocation, D1 read or write, cache invalidation, scheduled job, or static asset request. The five-minute unchanged-observation heartbeat and the existing 120-second edge/client dashboard caches remain unchanged. A real availability, health, or error change still bypasses observation deduplication immediately and enters the notification pipeline on the first matching inspection.

The cadence labels must remain aligned with `config/venue-schedule-policy.yaml`; regression coverage enforces the current default and explicit exceptions.
