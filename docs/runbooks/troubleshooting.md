# Troubleshooting

## DAG Import Error

Run `make test-dags`, then inspect the exact file and traceback. Reusable modules
must remain outside `dags/`; do not fix imports by mutating `sys.path`.

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

Validate the `APPIUM_SERVER_LIST` shape by field names only, then inspect remote
SSH reachability and `adb devices` state. The DAG must never fall back to an
unrelated device when multiple devices are online.

Every resolved incident should add a regression test or update this runbook,
the component manifest, or an ADR.

## Metadata Cleanup

Do not run `airflow db clean` inside a DAG task. Airflow 3 task subprocesses are
isolated from direct metadata database access. Use `make db-cleanup-check` for
the read-only deployment-manager probe. Apply mode requires explicit approval
for a concrete cutoff and must not be used to make health checks green.
