# Remote Operations MCP

## Connections

Daily entry and fallback routing: [Agent Operations](agent-operations.md).

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

### Authentication Dependency Failures

On 2026-11-01, Pi's Node default public-key fetch repeatedly timed out at five
seconds, while six explicit IPv4 HTTPS probes succeeded in about 1.3-1.7 seconds.
The old catch-all handler mislabeled dependency failures as `403 request_rejected`.
This is a reproduced failure path, not proof of the cause of every historical 403.

Host MCP now fetches only the fixed Cloudflare public-key URL over IPv4 with
normal TLS verification, a 64 KiB response limit and at most two six-second
attempts. JWT signature, issuer, audience, expiry and algorithm validation remain
mandatory. Keys are cached for ten minutes; expired caches are not a fallback
during outages. Unknown-key rotation retains the verifier's refresh cooldown.
Dependency failures return `503 authentication_dependency_unavailable` with
`Retry-After`; invalid credentials remain denied. Failure records contain only
a correlation ID, fixed category and status, never tokens or exception text.

Protected host installation and independent health verify three fresh public-key
resolvers, in addition to authenticated MCP calls and anonymous/invalid-token
denial. This prevents a warm key cache from masking outbound network failures.
Machine health does not certify a particular user's OAuth grant, and machine
identities cannot run commands. Never replay an uncertain administrator command
automatically.
Phone MCP uses its existing Tunnel Access validation, not this Node verifier;
check its independent public health without creating sessions or notifications.

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

Agents whose client has no MCP tools use the repository client instead. It needs
no human step when the browser already holds a Cloudflare Access session:

```text
python scripts/ops_mcp.py login pi        # pi, vps or phone
python scripts/ops_mcp.py call vps ops_status '{}'
python scripts/ops_mcp.py exec pi --reason "read-only check" check.sh
```

It registers a public client, opens the authorization URL with PKCE in the
default browser (`--browser chrome` picks one) and receives the code on a
one-shot localhost listener. The token is stored per endpoint in
`~/.config/zacks-ops-mcp/` (mode 0600, override with `ZACKS_OPS_MCP_TOKEN_DIR`),
reused while valid and refreshed when rejected. It is never printed and never
leaves the workstation. A browser without a session shows the Cloudflare login
page; the person signs in there, and the agent never types credentials.

Share only authorized destinations. Initial tests list tools and call
`ops_status` or `phone_devices`; they never run commands or create phone sessions.

## Administrator Operations

- `ops_status`: resource health and exact operations runtime identity.
- `ops_diagnose`: allowlisted service/container states; no logs, secrets or changes.
- `ops_exec`: runs a command as root immediately. `timeoutSeconds` is at most 3600;
  a command still running after `waitSeconds` (at most 90) returns `state=running`.
- `ops_result`: the requesting identity's state and output, kept for 15 minutes.
- `ops_github`: protected GitHub release/operations entry points.

Completing Cloudflare OAuth as a human member of the host's Access group is the
only gate; there is no per-command confirmation ([ADR 0018](../adr/0018-authenticated-direct-mcp-administration.md)).
Machine identities cannot run or read commands. Up to eight commands run in
parallel. Restart discards results and kills running commands, which are never
replayed; treat a lost or `unknown` command as uncertain and inspect the host.

This is **root administrator access**, not a sandbox. Commands can
affect the whole host, detach processes or change the controls themselves.
Only trusted administrators belong in these groups. Result redaction covers
obvious credentials but cannot guarantee arbitrary output is secret-free.
Never request secrets or bulk raw configuration/log dumps. Review results before
sharing. Database deletion/restore, key rotation and real notification sends
still require the owner's explicit consent, now as a rule the agent must follow
rather than a technical control. Repository releases remain
subject to exact-SHA CI and protected GitHub deployment.

Audit records persist under `/var/log/zacks-ops-mcp/audit.jsonl`: timestamp,
hashed identity, request ID, command text and reason with obvious credentials
redacted, state and exit code. A command does not run if its audit record cannot
be written. Output is not recorded; results keep the last 256 KiB.

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

Prefer [Production MCP Lifecycle](https://github.com/claude89757/wechat-on-airflow/actions/workflows/production-mcp.yml)
for routine MCP patches. One apply runs preflight, apply and independent health.
The component workflows below remain recovery and implementation interfaces.

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
