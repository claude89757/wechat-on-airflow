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
the two runtime settings as root-owned systemd credential source files:

```bash
install -d -o root -g root -m 700 /etc/wechat-sender/credentials
install -o root -g root -m 600 /secure/input/device \
  /etc/wechat-sender/credentials/wechat_allowed_device_name
install -o root -g root -m 600 /secure/input/appium-url \
  /etc/wechat-sender/credentials/wechat_appium_url
```

The device credential is the exact serial reported by `adb devices`, not
the marketing model name. The same value must be used by
`WECHAT_SEND_DEVICE_NAME` and the Zacks entry in `APPIUM_SERVER_LIST`.

The Android host must provide Appium, ADB, and Chinese OCR data:

```bash
sudo apt-get install python3-pil tesseract-ocr tesseract-ocr-chi-sim
adb devices -l
appium driver doctor uiautomator2
```

The systemd installer creates its virtual environment with system site packages
so ARM hosts can use the distribution-built Pillow package. The Docker image
continues to install the pinned Pillow wheel from
`docker/sender/requirements.lock`.

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

Apply mode also installs the repository-managed Appium systemd override. Appium
binds only to `127.0.0.1:6002`, overrides stale sessions, starts ADB before
accepting work, uses bounded journal logging, and restarts automatically. The
sender remains public on port 7001; Appium and ADB must not be exposed publicly.

`docker-compose.sender.yml` remains a supported development and alternate-host
runtime, but it is not the production process manager.

`/healthz` is the service liveness probe. `/readyz` is the production readiness
gate. It verifies Appium, the configured ADB serial, Android boot completion,
and the installed WeChat package. It never opens WeChat or sends a message.
Production health derives this readiness URL from the configured
`WECHAT_SEND_API_URL`; it never prints the endpoint value.

Production diagnosis and bounded recovery are exposed only through the
protected GitHub Environment:

```bash
make sender-diagnose
make sender-recover
```

Diagnosis suppresses serials and reports state categories. Recovery restarts
ADB, Appium, and the sender, then waits for `/readyz`; it never reboots the phone
or sends a message. A missing USB ADB interface remains a physical-device
incident and is not hidden by restarting services.

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
control. Venue DAGs publish raw observations to the Web subscription service,
persist their WeChat detection cache, and then attempt WeChat. Failed chat
sends are deduplicated in `WECHAT_SEND_FALLBACK_OUTBOX`; they do not fail the
DAG and are not retried automatically by the outbox.

The outbox is an incident record, not a retry queue. Never automatically replay
it: venue detection state is persisted before delivery, so blind replay can
create stale or duplicate notifications. Resolve the sender fault, verify
`/healthz`, and let new detections use the restored channel.

## Behavior

- The sender checks visible recent chats before using search.
- UiAutomator selectors remain the primary path. If WeChat exposes an empty
  accessibility hierarchy, the sender uses local screenshots and Tesseract to
  identify the visible chat, search result, and send button.
- The visual send path clears any existing draft with batched ADB key events,
  locates the green send control by color before falling back to OCR, and
  verifies that the send control disappears after the tap.
- Visual recognition runs entirely on the Android host; screenshots and
  recognized message content are not logged or retained.
- It cleans stale Appium sessions for the configured device before a send.
- Each send wakes the display, dismisses a non-secure keyguard, and collapses
  the notification shade before opening WeChat. It also sends one Android back
  action before launch to close Huawei USB-mode and similar system dialogs.
- `409 device_busy` means another request owns the device lock.
- `403 device_not_allowed` means the requested device does not match runtime
  configuration.
- `503` from `/readyz` means Appium or the configured Android device is not
  ready.
- `504 appium_timeout` means the UI did not become ready before the deadline.
- Tests and automated smoke checks must use fakes and must not send real
  messages. A real send requires explicit human approval.

For a dedicated, USB-powered phone, apply mode configures stay-awake on USB,
disables window animations, and exempts WeChat from Android idle mode. Huawei
power management still needs manual confirmation that WeChat is allowed to run
in the background and that USB debugging authorization survives reconnects.
