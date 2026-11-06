# Web Application Deployment

The production Worker serves responsive React assets at `courts.zacks.vision`
and `zacks.claude89757.cc`. It forwards `/api/*` to Host Core on the Airflow
host. PostgreSQL owns subscriptions, venue observations, quotas and delivery.
The Worker has no D1 binding, business Cron or SES delivery ownership. D1 is
an unbound migration archive; never delete, migrate or reimport it as part of a
routine Web or venue update.

## Choose the update

For a new venue or coupled business change use:

```sh
make release TARGET_COMMIT=<full-main-sha>
```

See [venue-onboarding.md](venue-onboarding.md). It updates Host Core and the Web
edge, Airflow and Sender together, restores consumers and records immediate
acceptance. No version bump, unrelated MCP preflight or natural-mail wait is
required.

For assets or stateless-edge changes alone, use `production-webapp.yml` with
`operation=deploy_apply` and the verified full main SHA. It builds the exact
sources, confirms existing Host Core routing, deploys the stateless Worker and
checks public health. Airflow and Sender keep their own deployed identities.
`deploy_preflight` is available for a separate build and Wrangler dry-run when
needed; `health` is read-only. Workstation Wrangler production deployment is
unsupported. GitHub's protected `production` Environment owns the scoped
Cloudflare deployment identity. Runtime secrets remain in native platform
stores; never download or print them.

## Verification

Use `make webapp-check` locally when the frontend or Worker changes. Main's
exact-SHA `CI / verify` is the release gate. Deployment builds verified sources;
it does not repeat main's unit and type tests.

Public checks must establish:

- `/api/edge-healthz` reports the expected Web SHA, stateless mode and no legacy
  runtime; `/api/healthz` reports healthy Host Core with its own component SHA;
- `/api/bootstrap` has the active catalog, including the new venue, and exposes
  no email addresses or current bookable slots;
- the venue card opens the subscription sheet with that venue selected;
- unauthenticated observation writes remain denied;
- desktop and mobile controls remain usable, without a device picker or overflow.

`webapp/qa/public-acceptance.mjs` compares actual card IDs with
`src/wechat_airflow/venue_catalog.json`, so adding a venue does not require
editing a hardcoded count. It blocks writes and checks the verification button
with a trial click only. Never create a real subscription, send a verification
email or inject availability for routine acceptance.

## Observation behavior

Venue polling cadence belongs to Airflow and is independent of dashboard reads.
The page loads its dashboard on opening and on explicit refresh or identity /
subscription actions. It does not poll while idle. Displayed health is the last
watcher-reported state with its report time; age alone does not make it unhealthy.
A failed Sender must not block observation persistence or subscriber matching.
Check watcher liveness and natural cycles through protected Airflow diagnostics,
and record production evidence in Issue #39. Missing natural delivery receipts
remain pending observation without synthetic notifications.
