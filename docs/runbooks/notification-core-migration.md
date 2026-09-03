# Notification Core 0.7.0 Migration Runbook

## Goal

Move existing-subscriber email and WeChat decision making onto the Airflow host
without changing any venue polling cadence or sending synthetic notifications.
Cloudflare remains the Web enrollment edge during the rollback window.

## Preconditions

- Exact release commit has passed `CI / verify`.
- Production Airflow, PostgreSQL, Redis, and Android sender health checks pass.
- D1 accepts the bounded subscription snapshot query.
- `TENCENT_SECRET_ID`, `TENCENT_SECRET_KEY`, sender addresses, template ID, and
  delivery-limit values are available to the protected production workflow.
- No database values or recipient addresses are printed in logs.

## Preflight

1. Build the exact Airflow image.
2. Render Docker Compose and confirm the two new services:
   `zacks-notification-api` and `zacks-notification-worker`.
3. Run `python scripts/notification_core_admin.py migrate` in an Airflow image.
4. Start both services with `ZACKS_CORE_DELIVERY_MODE=shadow`.
5. Synchronize the D1 snapshot and require a non-empty active-subscription
   result unless an operator explicitly approves an empty production state.
6. Verify `/healthz` and `/readyz` over loopback.

## Shadow phase

- Keep `WEBAPP_OBSERVATION_API_URL` pointing to the Cloudflare Worker.
- Keep `ZACKS_CORE_DELIVERY_MODE=shadow`.
- The local worker refreshes subscription state but does not claim or send
  email.
- Compare only aggregate counts and hashes. Do not log addresses or tokens.

## Atomic cutover

1. Pause all venue inspection DAGs through the supported deployment operation.
2. Drain active venue task instances.
3. Run one final subscription snapshot synchronization. The snapshot includes
   recent `subscription_events`, which become the duplicate-prevention boundary.
4. Run:

   ```text
   python scripts/notification_core_admin.py cutover
   ```

   This stores the previous endpoint, changes the observation endpoint to
   `http://zacks-notification-api:8091/api/internal/observations`, and sets the
   delivery owner to `active`.
5. Restart `zacks-notification-worker` so an environment override cannot mask
   the Variable-owned delivery mode.
6. Resume venue DAGs in their prior pause state.
7. Observe natural schedule cycles. Do not create artificial slots or deliver
   test notifications.

Existing D1 outbox rows may finish under the previous owner. Imported
`subscription_events` ensure the local core does not recreate those events.
New observations go only to the local core.

## Acceptance

- Local API reports a ready subscription snapshot.
- At least three natural venue cycles complete successfully.
- Venue task logs show the local internal URL and successful responses.
- A Cloudflare/D1 read failure does not suppress WeChat; only a fresh explicit
  local gate denial does.
- Redis interruption causes polling fallback, not delivery data loss.
- No `processing` lease is automatically replayed after expiry.
- PostgreSQL unique constraints show zero duplicate dedupe keys.
- Cloudflare Worker no longer receives venue observations after cutover.
- Email provider reconciliation continues from the local worker.

## Rollback

1. Pause and drain venue inspection DAGs.
2. Run:

   ```text
   python scripts/notification_core_admin.py rollback
   ```

3. Restart the notification worker in shadow mode.
4. Resume DAGs.
5. Verify observations reach the previous Cloudflare endpoint.

Do not delete `zacks_core` or D1 records during rollback. Database deletion and
D1 retirement are separate, explicitly approved operations.

## Post-cutover retirement

After a seven-day clean observation window:

- remove Cloudflare Worker scheduled delivery jobs;
- remove Worker-side Tencent SES secrets;
- move Web enrollment API behind the existing Cloudflare Tunnel;
- archive the final D1 export;
- request separate approval before deleting D1.
