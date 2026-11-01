# Agent Operations

## Routing

The user talks to an agent. The agent chooses the channel; the user does not
need to choose among component workflow files.

| Intent | Primary route | Fallback / evidence |
| --- | --- | --- |
| Host resources | MCP `ops_status` | Protected GitHub host diagnostics |
| Service / container states | MCP `ops_diagnose` | Protected GitHub diagnostics |
| Available phones | Phone MCP `phone_devices` | Protected phone diagnosis |
| Missing email / WeChat | MCP service inspection, then structured business diagnostics | Existing protected email / delivery diagnostics |
| One necessary host command | MCP `ops_request`, human approval, `ops_result` | Protected operation, never automated approval |
| Code release | GitHub exact-commit CI and protected deployment | Issue #39 and Actions evidence |
| MCP release | `production-mcp.yml` | Existing component workflows for recovery |
| MCP unavailable | GitHub protected diagnostics | Do not disable Access or share tokens |

`ops_diagnose` runs only fixed `systemctl show` queries and, on VPS, a bounded
Docker container-state query. It returns allowlisted states, not logs, arbitrary
configuration, command output, phone content, credentials or recipient details.
Unavailable checks are reported as unavailable, not healthy. This is service
inspection, not end-to-end notification acceptance or a database probe.

## Releases

MCP runtime components are `remote_ops` (Pi and VPS) and `pi_mcp` (phone bridge).
They are included in the normal component plan and cannot be omitted by a manual
scope. A business `all` scope includes detected MCP changes, but does not force
an unchanged phone bridge restart.

For an independent MCP patch, use the **Production MCP Lifecycle** workflow:
select the reviewed full main SHA, component, and `preflight` or `apply`.
`apply` runs preflight, apply and an independent health process in order, stopping
on the first failure. Pi host is completed before VPS. The phone bridge is not
restarted for a host-only patch. The existing protected `production` Environment,
main-ancestry/CI gates and scoped credentials remain in each component worker.

For business releases retain `/release ship` and its Host Core, Sender alignment,
natural-cycle and delivery acceptance gates. Do not pass the latest repository
SHA as a deployed business identity: each component has its own release identity.
Never deploy via MCP shell commands or approve one's own operation.

## Coordination And Audit

MCP command serialization applies only inside that MCP process. It is not a
shared lock with GitHub deployment workers. Before requesting a mutation, check
Actions for a running release on the same host; wait until it completes. Do not
start another release while an approved MCP mutation is running. This is an
operating restriction, not a claim of technical exclusion against root admins.

Record meaningful incidents, approved changes and releases in Issue #39 with:
component, exact runtime identity, bounded result, workflow link (when applicable),
remaining risks and follow-up. Never publish secrets, raw logs, approval cookies,
OAuth grant material or phone content. Fixed read-only inspections need not spam
the issue. High-risk actions retain their explicit approval requirements.

GitHub diagnosis stays available even when Cloudflare OAuth, Tunnel, or the MCP
server itself fails. Existing diagnostic workflows are retained, not deleted
merely because their daily entry moved to MCP. The retired PR #188 formatter
and its pull-request write permission have been removed.
