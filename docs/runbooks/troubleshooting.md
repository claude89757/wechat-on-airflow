# Troubleshooting

## DAG Import Error

Run `make test-dags`, then inspect the exact file and traceback. Reusable modules
must remain outside `dags/`; do not fix imports by mutating `sys.path`.

## Email Delay or Failure

Check the venue-specific recipient Variable name, sender configuration names,
Tencent SES result code, and `EMAIL_SEND_FALLBACK_OUTBOX` count. Do not print
addresses or secret values. A failure must not fail the venue DAG.

## WeChat Failure

Check sender `/healthz`, `device_busy` responses, Appium availability, device
state, and `WECHAT_SEND_FALLBACK_OUTBOX`. Email must continue independently.
Do not send a live test without approval.

## Duplicate Notification

Stop manual retries. Verify that the venue dedupe cache was written before
delivery, compare the message identity with outbox entries, and check for
overlapping DAG runs. Preserve evidence before changing cache state.

## Phone Reboot Failure

Validate the `APPIUM_SERVER_LIST` shape by field names only, then inspect remote
SSH reachability and `adb devices` state. The DAG must never fall back to an
unrelated device when multiple devices are online.

Every resolved incident should add a regression test or update this runbook,
the component manifest, or an ADR.
