# Web Application Deployment

## Scope

The production application is a single Cloudflare Worker with static assets,
API routes, a D1 binding, and a one-minute outbox cron. Its custom domain is
`zacks.claude89757.cc`.

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

For isolated diagnosis, `production-webapp.yml` supports `health`,
`deploy_preflight`, and `deploy_apply`. `make webapp-deploy` and
`make webapp-health` only dispatch those GitHub operations; they do not use
local Cloudflare authentication. Local Wrangler production deploy and remote
D1 migration commands are intentionally unsupported.

## Verify

- `/api/healthz` returns `ok: true`.
- `/api/healthz` reports the exact release commit.
- `/api/bootstrap` returns eight venues and no email addresses.
- An unauthenticated observation write returns HTTP 401.
- Natural venue DAG runs publish fresh inspection timestamps.
- Browser layout and the create-subscription flow pass mobile visual checks.
- A controlled verification email can be sent only when explicitly authorized.

Do not create a fake subscription or inject a production slot during routine
checks. Notification outbox failures are retained for diagnosis and are retried
only by the Worker with bounded attempts.

The Worker groups pending slot rows by recipient into one concise delivery and
caps venue-reminder deliveries at 1,000 per Shanghai calendar day. This
reserves provider capacity for verification codes. The cap does not weaken
slot or subscription deduplication; rows remain in the D1 outbox until a later
bounded drain.
