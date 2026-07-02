# WeChat Direct Send Service

## Architecture

```text
Caller
  -> http://47.115.144.127:7001/v1/wechat/send
  -> sender-agent on 47.115.144.127
  -> Appium http://127.0.0.1:6002
  -> Android device 971bd67c0107
  -> WeChat Zacks
```

The current runtime path does not depend on Airflow or a Cloudflare Worker. Callers reach the sender-agent directly through the public IP.

## Sender-Agent Environment

Run the sender-agent on `47.115.144.127` with one Uvicorn worker. The in-process device lock is valid only when the service is a single process.

Current deployment directory:

```bash
/home/claude/wechat-sender-agent
```

Install the minimal runtime dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-sender-agent.txt
```

```bash
export WECHAT_ALLOWED_DEVICE_NAME="971bd67c0107"
export WECHAT_APPIUM_URL="http://127.0.0.1:6002"
uvicorn sender_agent.app:app --host 0.0.0.0 --port 7001 --workers 1
```

The sender endpoint is intentionally public and does not require a token.

For the current Raspberry Pi deployment, the process is started with `nohup` and tracked by `sender-agent.pid`:

```bash
cd /home/claude/wechat-sender-agent
set -a
. ./.env
set +a
nohup .venv/bin/python -m uvicorn sender_agent.app:app --host 0.0.0.0 --port 7001 --workers 1 > sender-agent.log 2>&1 &
echo $! > sender-agent.pid
```

The current frpc mapping exposes the sender-agent publicly:

```ini
[wechat-sender-agent]
type = tcp
local_ip = 127.0.0.1
local_port = 7001
remote_port = 7001
```

The previous `appium-6002` public frp mapping is disabled in the current Raspberry Pi deployment. The sender-agent reaches Appium through `127.0.0.1:6002`; exposing `6002` publicly lets legacy Airflow callers create competing Appium sessions against the same phone.

## Local Sender-Agent Smoke Test

Run from a machine that can reach `47.115.144.127:7001`:

```bash
curl -sS -X POST "http://47.115.144.127:7001/v1/wechat/send" \
  -H "Content-Type: application/json" \
  -d '{
    "receiver": "文件传输助手",
    "messages": ["sender-agent smoke test"],
    "device_name": "971bd67c0107"
  }'
```

Expected response:

```json
{
  "success": true,
  "device_name": "971bd67c0107",
  "receiver": "文件传输助手",
  "sent_count": 1
}
```

`wechat.claude89757.cc` is a DNS-only Cloudflare A record pointing to `47.115.144.127`, but requests using that Host header are currently intercepted by Aliyun's ICP filing block page. Use the public IP endpoint until the domain is filed or the endpoint is moved behind a proxy/tunnel that avoids this Host-header block. Keep the explicit `:7001` port in direct calls.

## Airflow DAG Caller Configuration

Airflow DAGs call the sender-agent through `utils.wechat_send_api`. Keep the endpoint in Airflow Variables, not in DAG code.

Required variables:

- `WECHAT_SEND_API_URL`: full sender-agent endpoint URL.
- `WECHAT_SEND_DEVICE_NAME`: allowed device name, currently `971bd67c0107`.

Optional variables:

- `WECHAT_SEND_TIMEOUT_SECONDS`: request timeout, default `120`.
- `WECHAT_SEND_RETRY_COUNT`: attempts per send, default `3`.
- `WECHAT_SEND_RETRY_DELAY_SECONDS`: delay between attempts, default `5`.

Text sends previously routed through `send_wx_msg_by_appium`, `send_wx_msg`, or `ZACKS_UP_FOR_SEND_MSG_LIST` now call the synchronous sender API directly. Media sends still use the existing Appium media helper because `/v1/wechat/send` currently accepts text messages only.

## Legacy Cloudflare Worker Environment

The Worker path below is not used by the current public endpoint. Keep it only if a token-protected gateway is needed again later.

Non-secret configuration is committed in `cloudflare/wechat-worker/wrangler.jsonc`:

- `ALLOWED_DEVICE_NAME=971bd67c0107`
- `SENDER_AGENT_URL=http://47.115.144.127:7001`

Set Worker secrets with Wrangler:

```bash
cd cloudflare/wechat-worker
npx wrangler secret put PUBLIC_API_TOKEN
npx wrangler secret put SENDER_AGENT_TOKEN
```

`PUBLIC_API_TOKEN` authenticates callers to Cloudflare. `SENDER_AGENT_TOKEN` authenticates Cloudflare to sender-agent.

## Worker Smoke Test

Current Worker URL:

```bash
https://wechat-send-gateway.claude89757.workers.dev
```

```bash
curl -sS -X POST "${WECHAT_WORKER_URL:?set WECHAT_WORKER_URL}/v1/wechat/send" \
  -H "Authorization: Bearer ${PUBLIC_API_TOKEN:?set PUBLIC_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "receiver": "文件传输助手",
    "messages": ["cloudflare worker smoke test"],
    "device_name": "971bd67c0107"
  }'
```

Expected response has `success: true` and `sent_count: 1`.

If `workers.dev` resolves to a non-Cloudflare address or TLS fails before the request reaches Cloudflare, verify DNS with a trusted resolver or attach a custom domain to the Worker.

## Operational Notes

- The direct endpoint is intentionally public. Anyone who can reach it can request a WeChat send from this device.
- Do not expose Appium `6002` as the public API.
- Expose only sender-agent `7001`.
- Keep sender-agent at one process unless an external lock is introduced.
- The sender-agent cleans stale Appium sessions for device `971bd67c0107` and restarts UiAutomator2 state before opening a new session.
- `409 device_busy` means another request is currently controlling the phone.
- `502 upstream_unavailable` means Cloudflare cannot reach sender-agent.
- Log request IDs and error codes at the caller side.
