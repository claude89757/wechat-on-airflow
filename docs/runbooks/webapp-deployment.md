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

Set them with Wrangler secret commands. The Airflow
`WEBAPP_OBSERVATION_API_TOKEN` value must exactly match
`AIRFLOW_PUSH_TOKEN`. Do not print either value.

## Apply

1. Run `make verify`.
2. Apply D1 migrations with `npm run cf:migrate:remote`.
3. Set or verify all Worker secrets.
4. Deploy with `npm run cf:deploy`.
5. Configure the three Airflow publisher Variables.
6. Deploy the exact pushed Airflow commit through the standard deployment
   runbook.

## Verify

- `/api/healthz` returns `ok: true`.
- `/api/bootstrap` returns seven venues and no email addresses.
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
