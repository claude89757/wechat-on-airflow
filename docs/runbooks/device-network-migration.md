# Device network migration

## Read-only preflight

Run through the owner-only issue-39 router after exact-main CI:

```text
/ops device-network-preflight <full-main-sha>
```

This command records the *actual* API, worker, sender and control identities,
including drift, rather than substituting a Git worktree or release tag for
runtime identity. The target SHA identifies the reviewed probe code; it does
not assert that all existing runtime components already run that commit.

The public SSH routing hostname and reviewed client version/digest are in
`config/device-network.json`. That file contains public routing metadata only,
never login credentials. Existing `PI_DEVICE_SSH_*` production Environment
credentials authenticate the new connection. The original pinned SHA-256 host
key must match; the probe never accepts a new host key. Optional
`DEVICE_TUNNEL_ACCESS_CLIENT_ID` and `DEVICE_TUNNEL_ACCESS_CLIENT_SECRET`
Environment Secrets are consumed by cloudflared through its service-token
environment variables. An Access rejection is a blocker, not permission to
remove an Access policy or initiate an interactive login.

The probe opens SSH direct-tcpip channels to the Pi's loopback sender and scraper
and performs GET readiness/liveness requests only. It never sends a test message,
runs an inspection, changes a Variable, restarts a service, or stops FRP. Reports
contain health booleans, component commits, counters and error classes, not
addresses, passwords, tokens, device serials or raw upstream responses.

## Cutover boundary

A passing preflight is NOT a completed cutover. Application/runtime SSH clients,
production deployment access, effective Variables and any overriding environment
values must all use the reviewed new route. A synchronous sender request must
not simply be moved behind the public HTTP proxy: its bounded device wait and
submission can outlast the HTTP proxy read timeout. Preserve the sender's durable
ledger, result reconciliation and unknown-outcome quarantine.

Keep Appium and the scrape endpoint on loopback. Preserve original host-key
trust when changing SSH transports. An HTTP request carried inside authenticated
SSH avoids the public HTTP proxy's request-time limit, but Cloudflare remains
an intentional transport dependency; do not claim Cloudflare independence.

Do not stop FRP or release ECS until all application clients and deployment
clients pass new-route acceptance and the external JsRPC/client inventory is
complete. No automatic retirement, secret rotation or real test notification
is authorized by this preflight command.
