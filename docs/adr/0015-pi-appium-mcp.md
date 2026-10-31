# 0015: Guarded Pi Appium MCP Through Cloudflare

Date: 2026-10-31. Status: accepted design; production acceptance requires the
protected workflow evidence for the exact release SHA.

## Decision

Run a pinned `appium-mcp` adapter as one isolated systemd process, using the
existing remote Appium 2 listeners. Do not replace the Pi's Node 16 runtime or
install a second phone automation daemon. Use an independently verified ARM32
Node 22 runtime because the Pi has an aarch64 kernel but 32-bit Raspbian userland.

Expose Streamable HTTP through a new remotely managed Cloudflare Tunnel and an
application-scoped Access Service Auth policy. A dedicated 90-day service token
is the initial unattended-agent credential. The connector validates Access JWTs
with the new app's audience. Origin traffic stays on loopback. Configure Access
before DNS publication and verify both anonymous denial and authenticated MCP.
For interactive cloud agents, enable Cloudflare Access Managed OAuth on the same
application rather than distributing service-token headers. Add only the pinned
owner's email selector, resolved privately from their Cloudflare user ID, with
the existing Cloudflare login-method requirement. No account-wide or Everyone
policy is allowed. Keep the machine policy for protected health automation.
Use PKCE S256/DCR, loopback and explicit ChatGPT/Cursor/Grok callbacks, 15-minute access
tokens and a seven-day refresh grant. The origin continues to receive the signed
Access assertion validated by cloudflared; no new Worker or phone daemon is needed.
This uses Cloudflare's Beta Managed OAuth feature and requires a compatible
client and initial owner login; it is not reuse of the management plugin's token.

Browser Integrity Check is incompatible with some legitimate programmatic
clients. Skip that product alone on the exact dedicated MCP hostname using an
owned custom rule; keep Access and all other WAF/custom rules intact. Do not
disable BIC zone-wide or disguise probes as browser user agents. Preserve
unrelated rules and reverse only the rule created by this operation on failure.

Wrap actual upstream tool callbacks, including their failure paths. Share the
existing per-device flock for the full MCP session, reject foreign sessions,
require explicit owned session IDs, keep phone routes/capabilities operator-only,
and bound idle and maximum lease lifetimes. Never start a phone session during
startup or health verification. Do not expose shell, host files, permission
changes, application installation/removal or application data clearing.

## Consequences

Independent phones can operate concurrently. One physical phone cannot accept
simultaneous control by MCP, the Sender and the agent. A lease may delay WeChat
by up to its duration plus in-flight cleanup, so interactive work should release
promptly. This is bounded contention, not a promise of zero notification delay.
Email delivery remains independent. Unknown session creation/cleanup outcomes
fail closed and require diagnosis rather than overriding another session.

Only one phone was observed online at initial inspection. A second Appium port
does not establish a second device. Device aliases must remain stable when a
second phone is connected and configured.

The existing public Appium hostname responded to unauthenticated read-only
status and session-list queries on 2026-10-31. New MCP authentication does not
close this legacy route or direct public ports. Do not claim whole-phone access
is secured until their callers, ownership and restriction are resolved. Do not
change legacy routes silently as part of additive MCP installation.

## Operations

Use [the component runbook](../../pi_host/appium_mcp/README.md). The protected
GitHub Environment supplies pinned Pi SSH and scoped Cloudflare deployment
identities. Stage a complete offline npm cache and verified Node archive, test
on the actual Pi, then activate the exact reviewed main commit. Preserve the
previous application and existing services. Public acceptance is read-only and
must not send notifications or open phone sessions.
