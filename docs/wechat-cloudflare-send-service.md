# WeChat Cloudflare Send Service

## Architecture

```text
Caller
  -> Cloudflare Worker /v1/wechat/send
  -> sender-agent on 47.115.144.127
  -> Appium http://47.115.144.127:6002
  -> Android device 971bd67c0107
  -> WeChat Zacks
```

The runtime path does not depend on Airflow. Airflow DAGs can keep using their own code paths, but the remote synchronous API calls only the Worker and sender-agent.

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
test -n "${WECHAT_AGENT_TOKEN:?set WECHAT_AGENT_TOKEN before starting sender-agent}"
export WECHAT_ALLOWED_DEVICE_NAME="971bd67c0107"
export WECHAT_APPIUM_URL="http://47.115.144.127:6002"
uvicorn sender_agent.app:app --host 0.0.0.0 --port 7001 --workers 1
```

`WECHAT_AGENT_TOKEN` must match the Cloudflare Worker secret `SENDER_AGENT_TOKEN`.

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

## Local Sender-Agent Smoke Test

Run from a machine that can reach `47.115.144.127:7001`:

```bash
curl -sS -X POST "http://47.115.144.127:7001/v1/wechat/send" \
  -H "Authorization: Bearer ${WECHAT_AGENT_TOKEN:?set WECHAT_AGENT_TOKEN}" \
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

## Cloudflare Worker Environment

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

- Do not expose Appium `6002` as the public API.
- Expose only sender-agent `7001`.
- Keep sender-agent at one process unless an external lock is introduced.
- `409 device_busy` means another request is currently controlling the phone.
- `502 upstream_unavailable` means Cloudflare cannot reach sender-agent.
- Log request IDs and error codes at the caller side; do not log token values.
