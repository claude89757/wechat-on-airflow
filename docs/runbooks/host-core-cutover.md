# Airflow-host notification core cutover

## Purpose

Move Web subscription state and subscriber-email delivery from Cloudflare D1
to the PostgreSQL-backed host core without sending a synthetic email or WeChat
message. D1 is retained read-only as migration evidence and a pre-activation
rollback source; it is not automatically reactivated after host delivery may
have begun.

## Ownership switches

- `ZACKS_DELIVERY_OWNER`: `cloudflare` or `airflow_host`
- `ZACKS_OBSERVATION_MODE`: `cloudflare`, `dual`, or `host`
- `ZACKS_WECHAT_GATE_SOURCE`: `legacy`, `host`, or `off`
- `HOST_CORE_CUTOVER`: route public `/api/*` to the host core
- `HOST_CORE_QUIESCE`: reject mutations and skip Worker cron
- `HOST_CORE_MIGRATION_ENABLED`: expose protected migration endpoints

The safe state before cutover is Cloudflare owner, legacy observation, legacy
WeChat gate. The safe state after cutover is host owner, host observation, host
WeChat gate, public host routing, migration disabled.

## Protected workflow

Use `.github/workflows/production-host-core.yml` through the `production`
Environment and an exact full main SHA. The workflow requires the exact `CI /
verify` check before any mutation.

`deploy-shadow` performs a reversible preparation only: it exposes migration,
creates the local schema and services, transfers SES configuration through a
hybrid encrypted envelope, imports D1, and enables dual observation. Cloudflare
remains the only email sender.

`full-cutover` performs the entire sequence:

1. Run host and edge preflight.
2. Deploy the legacy Worker with protected migration endpoints enabled.
3. Start `zacks-api` and `zacks-notification-worker` in shadow mode.
4. Transfer SES secrets directly Worker-to-host; GitHub receives no plaintext.
5. Import an initial D1 snapshot.
6. Send natural Airflow observations to both local PostgreSQL and the legacy
   Worker, then require recent status from at least 20 of the 26 venues.
7. Freeze legacy mutations and cron.
8. Wait for in-flight legacy requests and import the final snapshot.
9. Switch observations and the WeChat gate to PostgreSQL, explicitly stop the
   local notification worker, and verify the host API while delivery is paused.
10. Route public API calls to the host, disable migration endpoints, and verify
    both the stateless edge identity and the host API before any host delivery.
11. Make the host core the only email owner and start the local notification
    worker.
12. Verify local and public exact-commit health, readiness, and active ownership.

The delivery pause between steps 9 and 11 is an activation barrier. A failed
edge deployment can therefore return to the legacy path before the host has
sent anything. Once host delivery is activated, automated recovery never
reactivates the now-stale D1 sender.

## Failure recovery and rollback

Before host delivery activation, rollback uses this order:

1. Keep or restore the legacy edge in quiesced mode.
2. Set the host delivery owner to Cloudflare, restore the public legacy
   observation URL, and start the host services in non-sending mode.
3. Re-enable the legacy edge only after the host owner has stopped.

After host delivery activation, D1 no longer contains authoritative delivery
state. Re-enabling its sender could duplicate messages that PostgreSQL already
submitted. The safe automated response is therefore:

1. Keep the public API routed to the PostgreSQL host core.
2. Set `ZACKS_DELIVERY_OWNER=cloudflare` only as a neutral paused value.
3. Stop `zacks-notification-worker`.
4. Preserve all PostgreSQL Outbox and provider state for diagnosis and
   roll-forward activation.

This post-activation state is a **safe pause**, not a legacy rollback. Do not
reactivate D1 delivery without an explicit reconciliation plan. Do not delete or
rewrite the host schema during either recovery path.

## Verification without real delivery

- `/zacks-api/api/healthz` and public `/api/healthz` report the host SHA.
- `/api/edge-healthz` independently reports the exact stateless edge SHA.
- `/zacks-api/api/readyz` confirms PostgreSQL and host SES configuration.
- All 26 venue rows exist and at least 20 have natural observations in the last
  15 minutes before cutover.
- Active subscription count is non-zero after migration.
- `zacks-notification-worker` is stopped during the public edge activation
  barrier and running only after `ZACKS_DELIVERY_OWNER=airflow_host`.
- Worker migration endpoints return 404 after cutover.
- No test notification is sent. Observe at least three natural schedule cycles.

## D1 retirement

D1 deletion is deliberately outside this release. After a stable evidence
window, export final evidence, remove the binding and cron from a separate
human-approved change, then delete D1 only under explicit irreversible-operation
approval.
