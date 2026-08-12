# Troubleshooting

## DAG Import Error

Run `make test-dags`, then inspect the exact file and traceback. Reusable modules
must remain outside `dags/`; do not fix imports by mutating `sys.path`.

## CRLand Inspection Failure

If the Shenzhen Bay DAG runs quickly or appears successful while Web reports the
venue as unhealthy, inspect all `day_0` through `day_3` task logs. An
`UNSAFE_LEGACY_RENEGOTIATION_DISABLED` error means the upstream booking host
still requires legacy TLS server renegotiation. The CRLand client mounts
a compatibility SSL context only for `wlhmobile.crland.com.cn`; certificate
verification remains enabled and the setting must not be applied globally.

The Shenzhen Bay observation merges the outdoor and covered booking areas. A
failure in either request must fail the task and publish one unhealthy `szw`
observation; do not publish a partial result as healthy. The Greater Bay Area
venue uses the same client and authorization but publishes its own `gba`
observation from a separate DAG.

Greater Bay Area business code `2000` with a three-day booking-window message
means the requested date is outside the upstream horizon. The DAG must remain
wired to `day_0` through `day_2`; do not convert this response into healthy
empty availability.

If TLS succeeds but the API returns code `403` with a missing WeChat token
message, the sensitive `SZW_API_AUTHORIZATION` Variable is no longer accepted.
Refresh it through the approved configuration procedure and validate it with a
read-only query. Never print or commit the Variable value.

An upstream booking request failure must publish an unhealthy Web observation
and then fail the Airflow task. A successful task with an unhealthy observation
is a false-success regression. Validate the adapter with the unit tests and a
read-only upstream query; do not trigger email or WeChat delivery during the
check.

The client retries HTTP 403, 429, 5xx, malformed JSON, and transport failures
with a short bounded delay because the upstream intermittently rejects bursts.
Other application business codes fail immediately. Repeated 403 responses after
the bounded attempts still mark the observation unhealthy and fail the task.

## Email Delay or Failure

Check the Airflow Web observation result, Worker logs, D1 notification outbox,
and Tencent SES result category. Do not print addresses or secret values.
Airflow has no fixed email recipient lists and must not send email directly.
An observation or email failure must not fail the venue DAG.

## WeChat Failure

Check sender `/healthz`, `device_busy` responses, Appium availability, device
state, and `WECHAT_SEND_FALLBACK_OUTBOX`. Email must continue independently.
Confirm that Web observation publication completed before the WeChat attempt.
Do not send a live test without approval.

On the Android host, confirm `wechat-sender.service` is both enabled and active.
If Appium is ready but port `7001` has no listener, deploy the exact pushed
commit with `scripts/install_wechat_sender.sh`; a restart alone is not a durable
repair. Preserve the incident outbox and verify new failures stop accumulating.

## Duplicate Notification

Stop manual retries. For subscriber email, inspect the D1
`(subscription_id, event_key)` identity and notification outbox. For WeChat,
verify that the Airflow venue cache was written before delivery and compare the
message identity with its fallback outbox. Check for overlapping DAG runs and
preserve evidence before changing either cache.

## Phone Reboot Failure

Run `make phone-diagnose` first. It reports the latest failed task and filtered,
redacted error signatures through the protected GitHub production Environment;
it never emits Variable values and its current-state probe runs only the
read-only `adb devices` command. It does not reboot the device. Then validate
the `APPIUM_SERVER_LIST` shape by field names only and inspect the identified
SSH or ADB boundary. The DAG must never fall back to an unrelated device when
multiple devices are online.

Every resolved incident should add a regression test or update this runbook,
the component manifest, or an ADR.

## Metadata Cleanup

Do not run `airflow db clean` inside a DAG task. Airflow 3 task subprocesses are
isolated from direct metadata database access. Use `make db-cleanup-check` for
the read-only deployment-manager probe. Apply mode requires explicit approval
for a concrete cutoff and must not be used to make health checks green.
