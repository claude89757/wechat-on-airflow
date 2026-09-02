# Web Application Deployment

## Scope

The production application is a single Cloudflare Worker with static assets,
API routes, a D1 binding, and two bounded cron paths. Its custom domain is
`zacks.claude89757.cc`.

Venue DAG polling frequency is an Airflow contract and must not be reduced to
control Cloudflare usage. Each Airflow task publishes a stable observation
scope. A real availability, health, or error change is forwarded immediately.
After the first successful publication, an unchanged empty observation remains
on the Airflow host indefinitely and does not emit a timed heartbeat.

Observations that still contain available slots keep a cheap indexed rematch
probe on each natural poll. The Worker normally returns after one fingerprint
lookup; if a subscription mutation invalidated that fingerprint, the next probe
runs the complete matching path so a new subscriber can match availability that
was already open. This probe is a subscription-correctness mechanism, not a
liveness heartbeat. Older publishers without an explicit scope fail open to a
shared compatibility scope until the matching Airflow commit is deployed.

Dashboard venue health is the last state reported by the watcher. It is not
derived from the age of a heartbeat. The card displays the age of the stored
report, while operational watcher liveness is verified through protected
Airflow health and diagnosis workflows.

The configured venue schedules produce at most roughly 48,000 observation
attempts per day before task runtime and scheduler overlap reduce the actual
count. Stable empty attempts are stopped locally and never reach Cloudflare.
Persistent available-slot attempts normally perform only an indexed fingerprint
lookup. Alert at 80,000 total Worker requests per day so the production account
retains margin below the Workers Free daily hard limit.

The Worker cron paths are intentionally separated:

- `*/5 * * * *` runs the recent-first delivery-status reconciler with a batch of
  five per queue and refreshes the Web-owned WeChat subscription gates;
- `17 * * * *` runs legacy housekeeping, expiry reminders, outbox maintenance,
  and cleanup once per hour without overlapping the five-minute cron.

These cron paths are delivery and maintenance jobs. They are not venue or
browser heartbeats.

`/api/bootstrap` responses use a private Cloudflare Cache API key on the Worker
custom-domain origin, separated by a one-way digest of the verification receipt,
for at most five minutes. The receipt never appears in the cache URL. Browser
responses remain `Cache-Control: no-store`.

The browser loads the dashboard once when the application opens. It does not
schedule a periodic refresh. The top refresh control requests
`/api/bootstrap?refresh=1` with `cache: no-store`, bypassing both client and edge
caches. Verification, identity changes, subscription create/cancel, and priority
redemption invalidate the relevant caches and refresh as part of the user's
action. Venue polling and notification generation are independent of dashboard
reads.

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
configuration procedure. The Airflow `WEBAPP_OBSERVATION_API_TOKEN` value must
exactly match `AIRFLOW_PUSH_TOKEN`. Do not print either value.

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

The Worker and Airflow publisher changes in this policy must ship from the same
exact commit. The short Web-before-Airflow interval is safe: an older publisher
without `observation_scope` is accepted and forwarded rather than rejected.

For isolated diagnosis, `production-webapp.yml` supports `health`,
`deploy_preflight`, and `deploy_apply`. `make webapp-deploy` and
`make webapp-health` only dispatch those GitHub operations; they do not use
local Cloudflare authentication. Local Wrangler production deploy and remote
D1 migration commands are intentionally unsupported.

## Verify

- `/api/healthz` returns `ok: true` and the exact release commit.
- `/api/bootstrap` returns twenty-six venues and no email addresses.
- An unauthenticated observation write returns HTTP 401.
- Natural venue DAG runs keep their configured schedules.
- A changed slot, health, or error state reaches D1 on the first matching poll.
- An unchanged empty observation produces no later Cloudflare request merely
  because time elapsed.
- An unchanged available-slot observation performs only the indexed rematch
  path unless a subscription mutation invalidated the Worker fingerprint.
- A slot set that disappears and later reappears is forwarded on the first
  matching poll.
- Opening the page performs one dashboard read; leaving it open schedules no
  additional reads.
- Clicking the refresh control requests `/api/bootstrap?refresh=1` and returns a
  newly generated dashboard.
- Venue status is shown as last-known state with its report age; it is not marked
  unhealthy solely because the report is old.
- Browser layout and the create-subscription flow pass mobile visual checks.
- Weekday subscriptions persist a non-empty ISO weekday selection, existing
  subscriptions remain all-days, and matching uses the booking slot's
  Asia/Shanghai calendar weekday.
- Venue status and selection surfaces are ordered by unique active follower
  count with deterministic ties.
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
