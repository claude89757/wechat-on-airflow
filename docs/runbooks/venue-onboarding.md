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
make release
```

This dispatches **Production Business Update** (`production-business.yml`) for the
current main; pass `TARGET_COMMIT=<full-main-sha>` to pin one. The workflow reads
the live Host Core SHA as its diff base, checks exact-main CI, and reuses the
existing protected lifecycle:

1. Airflow `deploy_recovery`, allowing short interruptions without a long drain;
2. Sender `apply`, only when the Sender or the WeChat consumer changed;
3. Host Core `routine-upgrade`, including backup, preflight and stateless edge;
4. `activate-workers`, including the transaction-rollback API probe, retried once;
5. an independent read-only public Host Core / edge / catalog health check.

No version bump, tag, separate component dispatches or synthetic notification
is required.

Consumers keep delivering until step 3, so a failure in steps 1 and 2 does not pause
notifications. Step 3 stops them and step 4 starts them again. Only if activation
fails twice does the workflow keep delivery paused, because the state is then
genuinely unverified. Observation reports never turn off activated delivery. Do
not replay an uncertain installation or delivery. Only inert artifact uploads
retry transient transport loss automatically, at most three attempts.

The run's `summary` job states the failed stage, its effect on delivery and the
next step. Resume without repeating the stages that succeeded:

```sh
make release-resume RUN_ID=<run-id>
```

Main may advance during a release. The run still targets its exact CI-verified
ancestor, and a changed production identity fails closed instead of activating a
stale target. If a release must be resumed by hand, activation can also be run with
`production-host-core.yml`, `operation=activate-workers` and the deployed SHA.

The Sender and consumer may run different commits. They must share a protocol
version: bump `PROTOCOL_VERSION` in `sender_agent/app.py` and
`SENDER_PROTOCOL_VERSION` in `wechat_worker.py` together for an incompatible change.
Until both sides match, WeChat messages wait in the durable queue.

Changed Pi/MCP runtimes are not deployed here. The gate lists them as
`notDeployedHere`; use their component lifecycle. Unknown paths are rejected. It does
not inspect or restart unrelated phone MCP services. It is for an already activated
Host Core, not initial cutover, database recovery, replacement or secret rotation.
Component workflows retain independent locks; coordinate with other running
production operations before dispatch.

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
