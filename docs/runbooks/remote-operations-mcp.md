# Remote Operations MCP

## Connections

These are configured destinations. Successful protected apply/health reports,
not this table alone, establish whether a new endpoint is live.

| Name | URL | Authorization |
| --- | --- | --- |
| Pi administrator | `https://pi-mcp.zacks.vision/mcp` | `Zacks Pi administrators` Access group |
| VPS / Airflow administrator | `https://vps-mcp.zacks.vision/mcp` | `Zacks VPS administrators` Access group |
| Phone operator | `https://appium-mcp.zacks.vision/mcp` | Owner plus `Zacks phone operators` group |
| Cloudflare frontend administrator | `https://mcp.cloudflare.com/mcp` | Official OAuth and account roles |

Use Streamable HTTP and OAuth with discovery/PKCE. Self-hosted applications
allow the documented ChatGPT and exact Cursor/Grok callbacks, including
`cursor://anysphere.cursor-mcp/oauth/callback`, and localhost/loopback.
Never distribute service-token headers, SSH credentials or management tokens.
Complete login in the same browser instance; on `Invalid session`, request a
fresh authorization rather than refreshing an old callback.

Frontend Worker `zacks-tennis-alerts` serves `courts.zacks.vision` and
`zacks.claude89757.cc`. The VPS hosts Airflow, PostgreSQL business services and
notification consumers behind `airflow.claude89757.cc`. The Pi runs scraping
and device connectivity. These have independent runtime/deployment identities.

Example client configuration (OAuth is completed in the client's login UI):

```json
{"mcpServers": {
  "zacks-pi": {"url": "https://pi-mcp.zacks.vision/mcp"},
  "zacks-vps": {"url": "https://vps-mcp.zacks.vision/mcp"},
  "zacks-phone": {"url": "https://appium-mcp.zacks.vision/mcp"},
  "cloudflare": {"url": "https://mcp.cloudflare.com/mcp"}
}}
```

Share only authorized destinations. Initial tests list tools and call
`ops_status` or `phone_devices`; they never run commands or create phone sessions.

## Administrator Operations

- `ops_status`: resource health and exact operations runtime identity.
- `ops_request`: command, reason and timeout (maximum 120 seconds); returns a
  five-minute browser approval URL without executing anything.
- `ops_result`: the requesting identity's bounded operation result.
- `ops_github`: protected GitHub release/operations entry points.

The requesting human opens the approval URL, logs in as the same identity,
reviews the exact command and explicitly confirms. Approval requires a signed
Access browser cookie, matching identity, same-origin POST and a one-use CSRF
challenge. OAuth Bearer requests and machine health credentials cannot approve.
Agents must never automate the approval page. Operations are serialized; an
expired, lost or uncertain request is never blindly retried. Restart discards
pending requests and ephemeral results, never replays them.

This is **root administrator access**, not a sandbox. Approved commands can
affect the whole host, detach processes or change the controls themselves.
Only trusted administrators belong in these groups. Result redaction covers
obvious credentials but cannot guarantee arbitrary output is secret-free.
Never request secrets or bulk raw configuration/log dumps. Review results before
sharing. Database deletion/restore, key rotation and real notification sends
still require explicit approval of the exact action. Repository releases remain
subject to exact-SHA CI and protected GitHub deployment.

Audit records persist under `/var/log/zacks-ops-mcp/audit.jsonl`: timestamp,
hashed identity, request ID, command digest, state and exit code. They do not
contain raw commands/output. Results are ephemeral and bounded to 64 KiB.

## Collaborators

The author edits the relevant named group's explicit email rules in Cloudflare
Zero Trust. Deployments create groups with the author initially and **never
overwrite membership**. Pi, VPS and phone groups are independent; the phone's
separate owner policy remains. Do not use Everyone or entire email domains.

The existing Cloudflare identity provider restricts login to account members.
Collaborators also need accepted account membership with minimal management
roles. Membership alone grants no host/phone access: the relevant Access group
is also required. Do not give ordinary operators Access-policy administration.

Official Cloudflare API MCP permissions come from the user's account roles and
OAuth consent, **not** these groups. Assign the required account/zone roles for
Workers and frontend operations. Some API roles are account-wide, not scoped
to a single Worker; review the actual resource scope. Our hosts store no
Cloudflare management token. Each collaborator authorizes their own client.

Revoke by removing group membership and revoking the user's Access sessions /
OAuth grants through Cloudflare. Group removal alone is not proof that all
existing tokens immediately stop working. Access tokens last 15 minutes and
refresh grants seven days. Emergency `withdraw` disables and stops only the affected host's
operations MCP and connector, not Airflow, Sender, Appium or the other host.
The withdrawn units stay disabled across reboots until an explicit apply.

## GitHub Window

Use [Production Remote Operations MCP](https://github.com/claude89757/wechat-on-airflow/actions/workflows/production-remote-ops-mcp.yml).
Choose target `pi`, `vps` or `phone`, operation and an exact merged SHA with a
successful `CI / verify`. Credentials come only from the protected `production`
Environment. No local SSH/Cloudflare write path is used.

1. `preflight` each target: read-only prerequisites and ownership checks.
2. `apply` Pi/VPS: isolated runtime, dedicated Tunnel/OAuth app, exact-host
   BIC-only rule, and access group. Initial groups contain only the author.
3. `apply` phone: add its group without restarting the phone runtime.
4. `health` each target: exact identity, tools and authentication denial, no commands.
5. Complete actual human OAuth separately and test read-only tools.
6. Record identities, run links and residual risks in the PR and Issue #39.

Node 22.23.4 and npm dependencies are pinned; archives are hash-verified.
Origins bind loopback only. Cloudflared validates Access, and the server also
validates JWT signature, issuer, audience and expiry. No SSH port is exposed.
Root-only host checkpoints allow partial provisioning recovery; never download
or log them. Failed public acceptance withdraws the new admin channel. Failed
local runtime activation restores the previous runtime/config when present.

[Issue #39](https://github.com/claude89757/wechat-on-airflow/issues/39) remains the
common production control window. This channel does not bypass owner checks
or automatically make collaborators repository release administrators.

References: [Cloudflare API MCP](https://developers.cloudflare.com/agents/model-context-protocol/cloudflare/servers-for-cloudflare/),
[Managed OAuth](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/),
[Cloudflare identity provider](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/cloudflare/).
