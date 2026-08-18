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
  "device_name": "configured-device",
  "idempotency_key": "optional-stable-key"
}
```

Success:

```json
{
  "success": true,
  "device_name": "configured-device",
  "receiver": "chat name",
  "sent_count": 2,
  "navigation_path": "recent_visual",
  "session_reused": false
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

The protected production workflow stages a verified Git bundle over SSH before
running these checks. This keeps exact-commit deployment available when the
Android host cannot connect to GitHub directly. A standalone installation still
uses the configured repository remote when the target commit is not available
locally.

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
- A currently open chat whose title strictly matches the requested receiver is
  reused before the sender navigates back to the recent-chat list.
- Visible-chat detection combines accessibility text with OCR even when WeChat
  exposes only a partial accessibility tree. It never scrolls the recent-chat
  list while selecting a receiver.
- Candidate names allow bounded OCR substitutions and short truncation. Exact
  and higher-confidence rows are attempted before earlier similar rows. A
  visible numeric suffix must match; when display truncation hides the entire
  suffix, the row is only a candidate and the complete chat title must still
  match before message input is touched.
- A high-confidence visible-chat row with an unambiguous numeric suffix may be
  verified by its transition into a WeChat chat activity when Huawei title OCR
  is unavailable. Search results never use this fallback and still require a
  matching chat title.
- OCR coordinates are tied to a fingerprint of the source chat-name row. The
  sender captures a fresh frame immediately before tapping; if an incoming
  message reordered the chat list during OCR, it discards every coordinate
  from that frame and rescans instead of tapping or falling back to search.
- An accessibility search control is accepted when it opens a recognized search
  surface or verifiably leaves the chat list. The known top-right coordinate is
  used only while the main page remains active.
- Search-page verification accepts either the dedicated WeChat search activity
  or a text input located in the top bar. Bottom chat inputs cannot satisfy
  this check.
- Search results are tried in match-confidence order and every candidate must
  open a WeChat chat activity with a title matching the requested receiver.
  Message input is not touched until that verification passes.
- On devices with an empty accessibility tree, that successful strict title
  check is retained for the current navigation only. The input guard verifies
  the package and chat-compatible activity without repeating unstable OCR or
  bottom-navigation color detection on the same frame; any sender-controlled
  navigation clears it.
- UiAutomator selectors remain the primary path. If WeChat exposes an empty
  accessibility hierarchy, the sender uses local screenshots and Tesseract to
  identify the visible chat, search result, and send button.
- The visual send path clears any existing draft with batched ADB key events,
  locates the green send control inside the bottom message-input row before
  falling back to OCR, and verifies that the control disappears after the tap.
  Green outgoing message bubbles are outside this bounded control region.
- Visual recognition runs entirely on the Android host; screenshots and
  recognized message content are not logged or retained.
- It reuses a warm Appium/WeChat session across requests in the single worker.
  A send creates a session only when none is usable. Failed sends discard the
  session; successful sends leave WeChat on the chat list for the next request.
- Duplicate `idempotency_key` values replay the previous success for 10 minutes
  without touching the phone. Airflow retries send the same key derived from
  receiver, device, and message text.
- It cleans stale Appium sessions for the configured device before creating a
  new session. Reused sessions skip this cleanup.
- Each send wakes the display, dismisses a non-secure keyguard, and collapses
  the notification shade before opening WeChat. It also sends one Android back
  action before launch to close Huawei USB-mode and similar system dialogs.
- Concurrent requests wait up to 150 seconds for the single-device lock so
  overlapping venue DAG sends are serialized instead of rejected immediately.
- `409 device_busy` means that bounded queue wait expired. Airflow then waits
  15 seconds and retries up to four times before recording the fallback outbox.
- `403 device_not_allowed` means the requested device does not match runtime
  configuration.
- `503` from `/readyz` means Appium or the configured Android device is not
  ready.
- `504 appium_timeout` means the UI did not become ready before the deadline.
- `navigation_path` reports whether a successful request reused an open chat,
  selected a visible recent chat, or used search. It does not expose message
  content.
- `session_reused` is true when the request used the warm Appium session.
- Tests and automated smoke checks must use fakes and must not send real
  messages. A real send requires explicit human approval.

For a dedicated, USB-powered phone, apply mode configures stay-awake on USB,
disables window animations, and exempts WeChat from Android idle mode. Huawei
power management still needs manual confirmation that WeChat is allowed to run
in the background and that USB debugging authorization survives reconnects.
