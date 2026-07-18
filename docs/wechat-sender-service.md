# WeChat Sender Service

The sender is a synchronous HTTP service that controls one Android device
through Appium. It is independent from Airflow and does not use Cloudflare.
The production endpoint and device identifier are runtime configuration and
must not be committed to this repository.

## HTTP Contract

`POST /v1/wechat/send`

```json
{
  "receiver": "chat name",
  "messages": ["first message", "second message"],
  "device_name": "configured-device"
}
```

Success:

```json
{
  "success": true,
  "device_name": "configured-device",
  "receiver": "chat name",
  "sent_count": 2
}
```

The endpoint is intentionally public and has no token authentication. Network
exposure is an operational decision; do not expose the Appium port itself.

## Runtime

Production runs the service directly on the Android device host under systemd.
It does not run on the Airflow host or depend on the Airflow containers. Store
the two runtime settings in `/etc/wechat-sender.env`, owned by root with mode
`600`:

```bash
WECHAT_ALLOWED_DEVICE_NAME=<device>
WECHAT_APPIUM_URL=http://127.0.0.1:6002
```

Deploy an exact pushed commit. The command is read-only unless `--apply` is
present:

```bash
sudo scripts/install_wechat_sender.sh --target-commit <full-sha>
sudo scripts/install_wechat_sender.sh --apply --target-commit <full-sha>
```

The installer creates an unprivileged `wechat-sender` account, installs locked
dependencies, enables `wechat-sender.service`, and waits for readiness. The unit
starts exactly one Uvicorn worker and restarts it automatically. The in-process
device lock is only valid with one process. A multi-process or multi-host
deployment requires an external distributed lock.

`docker-compose.sender.yml` remains a supported development and alternate-host
runtime, but it is not the production process manager.

`/healthz` is the service liveness probe. `/readyz` performs a read-only
Appium `/status` request and is the production readiness gate; it never opens
WeChat or sends a message. Production health derives this readiness URL from
the configured `WECHAT_SEND_API_URL`; it never prints the endpoint value.

## Airflow Configuration

Airflow calls the service through `wechat_airflow.notifications.wechat`.
Configure the endpoint and device in Airflow Variables:

- `WECHAT_SEND_API_URL`
- `WECHAT_SEND_DEVICE_NAME`
- `WECHAT_SEND_TIMEOUT_SECONDS`
- `WECHAT_SEND_RETRY_COUNT`
- `WECHAT_SEND_RETRY_DELAY_SECONDS`
- `WECHAT_SEND_FALLBACK_MAX_ITEMS`

Variable values are sensitive runtime data and are never included in source
control. Venue DAGs persist their detection cache first, deliver email
independently, and then attempt WeChat. Failed chat sends are deduplicated in
`WECHAT_SEND_FALLBACK_OUTBOX`; they do not fail the DAG and are not retried
automatically by the outbox.

The outbox is an incident record, not a retry queue. Never automatically replay
it: venue detection state is persisted before delivery, so blind replay can
create stale or duplicate notifications. Resolve the sender fault, verify
`/healthz`, and let new detections use the restored channel.

## Behavior

- The sender checks visible recent chats before using search.
- It cleans stale Appium sessions for the configured device before a send.
- `409 device_busy` means another request owns the device lock.
- `403 device_not_allowed` means the requested device does not match runtime
  configuration.
- `503` from `/readyz` means Appium is unavailable or not ready.
- `504 appium_timeout` means the UI did not become ready before the deadline.
- Tests and automated smoke checks must use fakes and must not send real
  messages. A real send requires explicit human approval.
