# Venue integration and routine business updates

For an ordinary venue integration, reuse an existing adapter where possible.
Keep venue IDs and DAG IDs stable after launch. Default polling is one minute;
declare exceptions in `config/venue-schedule-policy.yaml`.

## Development

1. Add adapter configuration and the wiring-only DAG. Update
   `config/active-components.yaml`, `config/config-contracts.yaml` and the
   schedule policy. Preserve existing recipient routes and deduplication.
2. Add the venue ID/name to `src/wechat_airflow/host_core/domain.py`,
   `webapp/cloudflare/domain.ts` and `webapp/src/api.ts`. Add the card icon/color
   in `webapp/src/Prototype.tsx`, booking link and notification name if needed.
   Keep `managed_services.webapp.expected_venue_count` in
   `config/runtime-target.yaml` consistent. Business acceptance and browser QA
   derive their active venue set from the catalogs.
3. Cover new parsing/filtering behavior with focused mock tests. For PosPal,
   unopened future dates can have no classrooms; only an entirely empty scan
   window with no request errors means invalid classroom configuration.
4. Run scoped checks from [fast-verification.md](fast-verification.md), merge
   through a PR, and use the full main merge SHA after `CI / verify` passes.

## One protected update

```sh
make release TARGET_COMMIT=<full-main-sha>
```

This dispatches **Production Business Update** (`production-business.yml`).
Follow its Actions run. The workflow reads the live Host Core SHA as its diff
base, checks exact-main CI, and reuses the existing protected lifecycle:

1. Host Core `routine-upgrade`, including backup, preflight and stateless edge;
2. Airflow `deploy_recovery`, allowing short interruptions without a long drain;
3. Sender `apply`, keeping its exact SHA aligned with the consumer;
4. `activate-workers`, including the transaction-rollback API probe;
5. an independent read-only public Host Core / edge / catalog health check.

No version bump, tag, separate component dispatches or synthetic notification
is required. The make command explicitly includes Sender alignment. A failed
deployment or activation stage pauses Host Core delivery through the existing
protected operation; inspect the failed stage before resuming. Observation
reports do not turn off already activated delivery. Do not replay an uncertain
installation or delivery. Only inert artifact uploads retry transient transport
loss automatically, at most three attempts.

The entry rejects unknown paths and changed Pi/MCP runtimes instead of silently
omitting them. Deploy those surfaces with their existing protected component
lifecycle; use the general release path when that diff includes multiple runtime
families. It does not inspect or restart unrelated phone MCP services.
It is for an already activated Host Core, not initial cutover, database recovery,
replacement or secret rotation. Component workflows retain independent locks;
coordinate with other running production operations before dispatch.

## Finish

Check public `/api/bootstrap`, find the new venue, and open its subscription
sheet. Do not send a verification code or create a real test subscription.
Confirm natural observations and the configured natural cycles. Record exact
component SHAs, workflow URL and remaining observations in Issue #39. Natural
business acceptance is separate from the deployment workflow: immediately after
activation even healthy venues may not have a new report in that acceptance
window. Do not turn that timing into another release gate. Missing
natural email/WeChat receipts remain `pending`; they do not hold the release,
disable delivery or justify synthetic sends. Re-run only
`production-host-core.yml` with `operation=acceptance` and the deployed SHA to
refresh that evidence, without redeploying.
