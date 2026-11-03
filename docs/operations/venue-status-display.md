# Venue status display semantics

The Web venue list separates three different concepts:

- **Inspection cadence** is the configured Airflow schedule: 2 minutes for Shenzhen Bay, 3 minutes for Greater Bay Area, 15 seconds for Dashah River free courts, 2 minutes for Dashah International, and 1 minute for other active tennis venues unless the policy declares another exception.
- **Last reported state** is the most recent observation accepted by Host Core, including an unchanged or intentional-idle observation.
- **Dashboard read time** is when the browser last loaded that stored state. The page reads once on first open and again only after an explicit refresh or a state-changing user action.

A `2分钟/次` label reports Shenzhen Bay's configured interval. The `记录于` timestamp describes the last observation loaded by the browser; the browser snapshot can become older until the next dashboard read. Protected health checks establish current watcher liveness from server-side evidence.

Shenzhen Bay and Greater Bay Area query CRLand only from 08:00 inclusive to 21:00 exclusive in Asia/Shanghai. Their cards show `2分钟/次` and `3分钟/次`; those intervals describe active polling during that window. Scheduled runs outside it continue internal healthy empty observations to refresh status and clear stale availability, without querying the venue or attempting reminders. An overnight healthy status is therefore not evidence of an overnight venue query.

Every natural round records an observation at the local Host Core API. Repeated observations refresh timestamps while semantic fingerprints suppress duplicate notification events. This preserves freshness and lets current availability be matched to newly created subscriptions without treating browser refreshes as watcher activity.

The dashboard does not schedule an automatic refresh. The top refresh button bypasses the client and edge caches. Browser refresh is only a data read and is never treated as proof that an Airflow watcher is alive; operational liveness belongs to the protected server health and diagnosis workflows.

The cadence labels must remain aligned with `config/venue-schedule-policy.yaml`; regression coverage enforces the current default and explicit exceptions. `ARCHITECTURE.md` records the current observation contract; `docs/decisions/manual-refresh-no-heartbeat.md` records the earlier browser-refresh decision.
