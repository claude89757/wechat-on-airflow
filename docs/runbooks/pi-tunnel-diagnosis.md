# Read-only Pi tunnel diagnosis

After owner approval and exact-main CI, comment on issue 39:

```text
/ops pi-tunnel-diagnose <full-main-sha>
```

The manual, protected `production` workflow uses only existing
`PI_DEVICE_SSH_*` Environment Secrets and the existing SHA256 host-key pin.
It connects directly to the stored host and port, so it does not require the
public Cloudflare SSH tunnel. The stored route must be reachable from GitHub
Actions; timeout, rejected authentication, or a host-key mismatch is a blocker,
not permission to change credentials, trust a different key, or reconfigure a
route. No public IP override is accepted.

This is a diagnostic code change, not a runtime deployment. The workflow must
be merged to main and pass the exact-SHA CI gate before execution. It has no
schedule. An `ok` result means evidence was collected, not that RSSHub recovered.

The Pi runs a bounded in-memory Python probe. It reads uptime, free disk space,
up to eight cloudflared systemd units and eight cloudflared containers. It
collects only state fields, exit/restart counters, and fixed error categories
from up to 1,000 recent lines per source in the last six hours. Raw logs,
container names/IDs, process arguments, environment/configuration, and secret
values are never returned. Unknown state strings are replaced with `unknown`.
Journal/Docker permission failures are reported without elevating privileges.
No files, services, containers, DNS, firewall rules, tunnel settings, or runtime
credentials are changed. No notification probes are sent.

If no cloudflared service/container is found, log permissions are insufficient,
or SSH is unavailable, report that limitation. Do not infer host downtime from
an unreachable runner route. Restart or repair requires separate approval.
