# Web Application Deployment

## Scope

The production application is a single Cloudflare Worker with static assets,
API routes, a D1 binding, and two bounded cron paths. Its custom domain is
`zacks.claude89757.cc`.

Venue DAG polling frequency is an Airflow contract and must not be reduced to
control Cloudflare usage. Each Airflow task publishes a stable observation
scope. The Worker suppresses an identical payload after an indexed D1
fingerprint lookup, while forwarding every real availability, health, or error
change immediately. An unchanged observation is still forwarded at least every
five minutes so the ten-minute venue-health freshness contract remains
satisfied. Older publishers without an explicit scope fail open to a shared
compatibility scope until the matching Airflow commit is deployed.

The configured venue schedules produce at most 48,000 observation requests per
day before task runtime and scheduler overlap reduce the actual count. This is a
request-budget constraint, not a reason to slow venue polling. Alert at 80,000
total Worker requests per day so the production account retains margin below the
Workers Free daily hard limit.

The Worker cron paths are intentionally separated:

- `*/5 * * * *` runs the recent-first delivery-status reconciler with a batch of
  five per queue;
- `17 * * * *` runs legacy housekeeping, expiry reminders, outbox maintenance,
  and cleanup once per hour without overlapping the five-minute cron.

`/api/bootstrap` responses use a private Cloudflare Cache API key on the Worker
custom-domain origin, separated by a one-way digest of the verification receipt,
for at most 120 seconds. The receipt never appears in the cache URL. Browser
responses remain `Cache-Control: no-store`; the edge cache exists only to avoid
repeating the same personalized D1 dashboard queries and identity writes during
the UI's refresh loop.

The browser client independently coalesces bootstrap network requests for the
same identity for 120 seconds and reuses the last value while the page is hidden.
Subscription create/cancel and priority redemption invalidate both client and
edge caches. Dashboard counters can be up to two minutes old; venue polling and
notification generation are unaffected.

## Local Verification

```text
make webapp-setup
make webapp-check
cd webapp && npm run test:runtime
```

Local Worker tests use mocks and development-only values. Production Worker
credentials stay in Cloudflare Worker Secrets and are not downloaded into the
repository.

## Production Secrets

The Worker requires:

- `TENCENT_SECRET_ID`
- `TENCENT_SECRET_KEY`
- `EMAIL_FROM_ADDRESS`
- `EMAIL_REPLY_TO`
- `EMAIL_TEMPLATE_ID`
- `VERIFICATION_PEPPER`
- `AIRFLOW_PUSH_TOKEN`

Set them in Cloudflare Worker Secrets through a separately approved
configuration procedure. The Airflow
`WEBAPP_OBSERVATION_API_TOKEN` value must exactly match
`AIRFLOW_PUSH_TOKEN`. Do not print either value.

The GitHub `production` Environment separately stores the scoped deployment
identity names `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`. Those values
allow Worker and D1 deployment only; they are not Worker runtime secrets and
must never be downloaded to a workstation.

## Apply

1. Push the exact commit and require the GitHub `CI / verify` check to pass.
2. Dispatch `production-release.yml` in `preflight` mode with that full SHA.
3. Review unapplied D1 migration output and all component preflight results.
4. Dispatch the same workflow in `apply` mode. The Web job applies D1
   migrations, deploys the Worker with `DEPLOYMENT_COMMIT=<full-sha>`, and runs
   read-only production probes before Airflow deployment begins.
5. Observe natural Airflow publication cycles and record the GitHub run.

The Worker and Airflow publisher changes in this repair must ship from the same
exact commit. The short Web-before-Airflow interval is safe: an older publisher
without `observation_scope` is accepted and forwarded rather than rejected.

For isolated diagnosis, `production-webapp.yml` supports `health`,
`deploy_preflight`, and `deploy_apply`. `make webapp-deploy` and
`make webapp-health` only dispatch those GitHub operations; they do not use
local Cloudflare authentication. Local Wrangler production deploy and remote
D1 migration commands are intentionally unsupported.

## Verify

- `/api/healthz` returns `ok: true` and the exact release commit.
- `/api/bootstrap` returns fourteen venues and no email addresses.
- An unauthenticated observation write returns HTTP 401.
- Natural venue DAG runs keep their existing 15-second, 30-second, and one-minute
  schedules.
- A changed slot set reaches D1 immediately; an unchanged set produces at most
  one full ingest per venue/task observation scope every five minutes.
- A slot set that disappears and then reappears is forwarded on the first
  matching poll rather than suppressed by the heartbeat throttle.
- A continuously open visible browser identity makes no more than 720 bootstrap
  network requests per 24 hours; a hidden page stops periodic network refreshes
  after it has a cached dashboard.
- Browser layout and the create-subscription flow pass mobile visual checks.
- Cloudflare Worker `exceededCpu` stays at zero during the observation window.
- Total Worker requests stay below the 80,000/day operational warning threshold.
- D1 daily rows read and written remain below the configured free-tier safety
  thresholds documented in the incident record.
- A controlled verification email can be sent only when explicitly authorized.

Do not create a fake subscription or inject a production slot during routine
checks. Notification outbox failures are retained for diagnosis and are retried
only by the Worker with bounded attempts.

The Worker groups pending slot rows by recipient into one concise delivery and
caps venue-reminder deliveries at 1,000 per Shanghai calendar day. This
reserves provider capacity for verification codes. The cap does not weaken
slot or subscription deduplication; rows remain in the D1 outbox until a later
bounded drain.
