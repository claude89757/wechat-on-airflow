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

## Weather-Gated Venue Reminder Email

The subscriber venue-reminder outbox checks Shenzhen's forecast daily
precipitation total through the Open-Meteo forecast API before it contacts
Tencent SES. The request uses `daily=precipitation_sum`, millimetres, and the
`Asia/Shanghai` calendar date. Open-Meteo does not require an API key for its
free non-commercial endpoint.

The checked-in defaults are:

- `WEATHER_EMAIL_GATE_ENABLED=true`
- `WEATHER_EMAIL_PRECIPITATION_THRESHOLD_MM=2.5`
- `WEATHER_EMAIL_GATE_LATITUDE=22.5431`
- `WEATHER_EMAIL_GATE_LONGITUDE=114.0579`

`2.5 mm/day` is a product heuristic rather than an official tennis standard.
It sits above trace drizzle while remaining within the national 24-hour
"light rain" band of `0.1-9.9 mm` in GB/T 28592-2012. Tune the threshold through
Worker vars after reviewing production suppression logs.

When the forecast total is greater than or equal to the threshold, eligible
venue-reminder rows are marked `suppressed` and are not retried on a later day.
This prevents stale court availability from being delivered after the weather
changes. Email verification codes bypass this gate. Airflow observation
publication and its independent WeChat notification path are unchanged.

The weather lookup has a three-second timeout, caches successful decisions for
ten minutes, and fails open: an Open-Meteo timeout, HTTP error, or malformed
response permits venue-reminder email rather than silently dropping alerts.
Inspect these structured Worker events after deployment:

- `notification_weather_suppressed`
- `notification_weather_gate_fail_open`

The free Open-Meteo endpoint is rate-limited, has no uptime guarantee, and is
licensed for non-commercial use. A commercial deployment must use a suitable
commercial licence/endpoint or a self-hosted weather source before relying on
this integration.

References:

- <https://open-meteo.com/en/docs>
- <https://open-meteo.com/en/pricing>
- <https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=B4A00E4ABCF80F8C6A048C1D0121A97D&refer=outter>

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
- A mocked forecast below `2.5 mm` permits venue email; a mocked forecast at or
  above `2.5 mm` records `notification_weather_suppressed` without contacting
  Tencent SES.
- A mocked weather-provider failure records
  `notification_weather_gate_fail_open` and preserves the existing email path.

Do not create a fake subscription or inject a production slot during routine
checks. Notification outbox failures are retained for diagnosis and are retried
only by the Worker with bounded attempts.

The Worker groups pending slot rows by recipient into one concise delivery and
caps venue-reminder deliveries at 1,000 per Shanghai calendar day. This
reserves provider capacity for verification codes. The cap does not weaken
slot or subscription deduplication; rows remain in the D1 outbox until a later
bounded drain unless the weather gate records them as intentionally
`suppressed`.
