# WeChat Cloudflare Send Service Design

Date: 2026-06-28

## Goal

Expose the existing personal WeChat text-send capability as a remotely callable service without depending on Airflow.

The service will keep Cloudflare as the public entry point and deploy a lightweight sender service on `47.115.144.127`, where the current Appium server and Android device are reachable.

## Confirmed Decisions

- The service is synchronous: callers wait for the WeChat send attempt to finish and receive success or failure in the same HTTP response.
- The sender service is deployed on `47.115.144.127`.
- Cloudflare may call the sender service directly over HTTP or HTTPS.
- The service targets the existing Appium setup:
  - `appium_url`: `http://47.115.144.127:6002`
  - `device_name`: `971bd67c0107`
  - `wx_name`: `Zacks`
- Airflow is not part of the runtime path.
- Cloudflare does not call Appium WebDriver directly. It calls only the sender-agent API.

## Architecture

```text
Caller
  -> Cloudflare Worker
  -> sender-agent on 47.115.144.127
  -> Appium http://47.115.144.127:6002
  -> Android device 971bd67c0107
  -> WeChat account Zacks
```

Cloudflare Worker is the public gateway. It handles request authentication, input validation, request normalization, timeout control, and forwarding to the sender-agent.

The sender-agent is the execution boundary. It owns all Appium-specific behavior, device locking, WeChat UI automation, and conversion of low-level exceptions into stable API errors.

Appium remains an internal dependency of the sender-agent. External callers must not interact with Appium directly.

## API Contract

### Worker Endpoint

`POST /v1/wechat/send`

Headers:

- `Authorization: Bearer <public_api_token>`
- `Content-Type: application/json`

Request body:

```json
{
  "receiver": "文件传输助手",
  "messages": ["hello"],
  "device_name": "971bd67c0107"
}
```

Success response:

```json
{
  "success": true,
  "device_name": "971bd67c0107",
  "receiver": "文件传输助手",
  "sent_count": 1
}
```

Failure response:

```json
{
  "success": false,
  "error": "send_failed",
  "message": "具体错误"
}
```

### Error Codes

- `invalid_request`: Missing or invalid payload.
- `unauthorized`: Missing or invalid Bearer token.
- `device_not_allowed`: Requested device is not on the allowlist.
- `device_busy`: Another send task is already using the same device.
- `appium_timeout`: Appium did not respond or the UI operation timed out.
- `wechat_not_ready`: WeChat is not on a usable page and could not be recovered.
- `contact_not_found`: The receiver could not be found in WeChat search or recent chats.
- `send_failed`: The send button or message input operation failed.
- `upstream_unavailable`: Cloudflare could not reach sender-agent.

## Sender-Agent

The sender-agent will be a small Python HTTP service on `47.115.144.127`, preferably FastAPI because the repository already lists FastAPI and Uvicorn in `requirements.txt`.

It exposes:

`POST /v1/wechat/send`

Headers:

- `Authorization: Bearer <agent_token>`

The sender-agent validates:

- Token is valid.
- `device_name` equals `971bd67c0107`.
- `receiver` is a non-empty string.
- `messages` is a non-empty list of non-empty strings.

The sender-agent then acquires a per-device in-process lock. If the lock is already held, it returns `409 device_busy`.

When the lock is acquired, it calls the extracted Appium send function and releases the lock in a `finally` block.

The first version must run sender-agent as a single process, for example one Uvicorn worker, so the in-process lock is authoritative. If the service later needs multiple worker processes or multiple hosts, replace the in-process lock with an external lock such as Redis or a database-backed lease.

## Refactoring Requirement

The current Appium send logic lives under Airflow DAG utilities. It must be extracted so the sender-agent can use it without importing Airflow.

Required changes:

- Move reusable Appium send code into an Airflow-free module, for example `wechat_sender/`.
- Keep a compatibility wrapper for existing DAG imports if needed.
- Make send failures raise exceptions instead of only printing stack traces.
- Return a structured result with `sent_count`, `receiver`, and `device_name`.

The current `send_wx_msg_by_appium()` catches exceptions and only logs them. The service must change this behavior because a synchronous remote API cannot report success when the underlying send failed.

## Cloudflare Worker

The Worker will:

- Verify caller Bearer token.
- Validate request payload.
- Enforce the same `device_name` allowlist as sender-agent.
- Forward the request to sender-agent using a separate `agent_token` stored as a Worker secret.
- Apply a request timeout. Initial target: 60 seconds.
- Map sender-agent responses to the public API response.

No D1, Queue, or Durable Object is required for the first version because the user chose a synchronous, simple architecture. These can be added later if queueing, job history, retries, or asynchronous delivery become necessary.

## Security

Minimum security controls:

- Do not expose Appium `6002` as the public API.
- Expose only sender-agent.
- Use separate Bearer tokens for public caller-to-Worker and Worker-to-agent authentication.
- Store Cloudflare tokens as Worker secrets.
- Store sender-agent token in an environment variable or local secret file on `47.115.144.127`.
- Allow only `device_name=971bd67c0107`.
- Log request IDs and error codes, but do not log tokens.

Optional hardening:

- Put sender-agent behind HTTPS.
- Restrict sender-agent firewall access to Cloudflare IP ranges or use Cloudflare Tunnel later.
- Add request body size limits.
- Add rate limiting at Worker level.

## Timeouts And Concurrency

The first version uses synchronous execution with no queue.

- Worker timeout target: 60 seconds.
- Appium element waits should remain bounded.
- Sender-agent returns `device_busy` immediately if the device is already locked.
- Sender-agent runs as a single process in the first version so its in-process lock protects the device correctly.
- The caller may retry `device_busy` later.

This avoids accidental concurrent control of the same WeChat UI and keeps the runtime behavior easy to reason about.

## Testing

Implementation should include focused tests:

- Worker validation rejects missing token, wrong token, invalid receiver, invalid messages, and wrong device.
- Worker forwards valid requests with the agent token and maps agent errors correctly.
- Sender-agent validation rejects invalid payloads and wrong device.
- Sender-agent lock returns `device_busy` for concurrent requests.
- Appium send wrapper raises on failure and returns structured success on success.

Manual smoke test:

1. Start sender-agent on `47.115.144.127`.
2. Confirm Appium `http://47.115.144.127:6002` can control device `971bd67c0107`.
3. Call Worker endpoint with receiver `文件传输助手`.
4. Verify the message appears in WeChat.
5. Verify response contains `success: true` and `sent_count`.

## Future Extensions

- Add D1 job history if audit trails are needed.
- Add Cloudflare Queue if sync sends become too slow or callers need reliable buffering.
- Add image/video send support after text send is stable.
- Add multiple device support by expanding the device allowlist and per-device locks.
