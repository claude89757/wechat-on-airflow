# Venue status display semantics

The Web venue list separates three different concepts:

- **Inspection cadence** is the configured Airflow schedule: 15 seconds for Shenzhen Bay, 3 minutes for Dashah International, and 1 minute for the other active tennis venues unless the policy declares another exception.
- **Last reported state** is the most recent availability, health, or error state that changed and was accepted by the Web pipeline.
- **Dashboard read time** is when the browser last loaded that stored state. The page reads once on first open and again only after an explicit refresh or a state-changing user action.

A card that says `正常 · 1分钟/次` and `记录于 4小时前` means the last reported state was healthy four hours ago while Airflow continues to inspect the venue once per minute. It does not claim that the browser or Cloudflare has received a liveness heartbeat during those four hours.

Stable empty observations remain on the Airflow host after their first successful publication and never publish merely because time elapsed. A real availability, health, or error change still changes the fingerprint immediately and enters the notification pipeline on the first matching inspection. Persistent available slots retain a cheap indexed rematch probe so a newly created subscription can match availability that was already open.

The dashboard does not schedule an automatic refresh. The top refresh button bypasses the client and edge caches. Browser refresh is only a data read and is never treated as proof that an Airflow watcher is alive; operational liveness belongs to the protected server health and diagnosis workflows.

The cadence labels must remain aligned with `config/venue-schedule-policy.yaml`; regression coverage enforces the current default and explicit exceptions. The full architecture contract is recorded in `docs/decisions/manual-refresh-no-heartbeat.md`.
