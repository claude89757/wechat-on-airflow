# Pi Appium MCP

An isolated deployment of `appium-mcp` 1.99.1, using the existing Pi Appium
servers and the shared `/run/wechat-device` ownership contract. The service
binds to `127.0.0.1:3333/mcp`. Public traffic goes through a dedicated Cloudflare
Tunnel and an Access application allowing one dedicated machine service token.
The connector also validates the Access JWT audience. Appium itself is not
published by this service.

The default Pi Node installation is not changed. The service uses a verified,
isolated Node 22.23.4 ARM32 runtime and a locked npm dependency tree. The
optional documentation/ML stack is omitted. No phone session is created at
service startup, during health checks, or while listing tools/devices.

## Client

Connect a Streamable HTTP MCP client to:

```text
https://appium-mcp.claude89757.cc/mcp
```

Configure these headers from the client's secret store:

```text
CF-Access-Client-Id: <dedicated-client-id>
CF-Access-Client-Secret: <dedicated-client-secret>
```

The dedicated token does not authorize other Access applications. Never put
its values in source, tool arguments, chat, build artifacts, or logs. OAuth is
a future alternative for interactive clients that cannot set custom headers;
the service-token deployment is for a trusted autonomous agent.

1. Call `phone_devices` to obtain configured aliases and online status.
2. Call `appium_session_management` with `action=create` and `device=phone_1`.
3. Pass the returned `sessionId` explicitly on every Appium tool call.
4. Call `appium_session_management` with `action=delete` and that `sessionId`.

Sessions cannot attach to another controller's session or select an implicit
active session. A phone stays locked throughout its MCP session. Different
phones can operate independently; the same phone cannot run concurrent tools.
Idle sessions close after 30 seconds, and leases stop accepting actions after
120 seconds. Cleanup must confirm session removal before releasing the lock.
Busy devices return `device_busy`; do not restart Appium or delete foreign
sessions to bypass this result.

Any unconfirmed session creation retains its phone lock, even if Appium's
session list is still empty: the remote request may still be running. Recovery
requires operator diagnosis. Apply, rollback and withdrawal stop only the new
MCP Tunnel first, then wait for all known MCP sessions to close. Unknown or
undrained session state aborts the change and restores the old Tunnel; it never
forces a running phone controller to exit. Public health probes receive only
client credentials, not the SSH or Cloudflare management-token environment.

The custom registry delegates to upstream tool implementations. Its integration
uses the fixed 1.99.1 registry module layout, so version changes must pass the
registry/import and ownership tests. Raw shell, host file transfer, application
installation/removal, and permission-management tools are not part of this
deployment's tool allowlist. Existing Sender operations retain their durable
idempotency contract; generic UI actions do not gain exactly-once semantics.

## Verification And Recovery

`make pi-mcp-setup` installs locked dependencies with lifecycle scripts and
optional native/documentation packages disabled. Appium 3 is an import-time
dependency of the upstream package only; it is never started as a server.
The complete dependency tree, including unused embedded driver imports, is locked.
The Pi continues to use its existing Appium 2 servers.

Runtime audits run locally, in CI and before release staging. Zod is pinned to
4.6.7. The transitive `@puppeteer/browsers` override selects Google's maintained
3.2.6 package, removing its old vulnerable ZIP/proxy chain. Its Node 22 baseline
and exported API are exercised by upstream transport/import tests; browser
download tools remain outside this deployment's allowlist. See the
[upstream changes](https://github.com/puppeteer/puppeteer/blob/main/packages/browsers/CHANGELOG.md).

`make pi-mcp-check` uses fake drivers and temporary flock files, never real phones.
The repository-wide shell release tests require GNU Bash/coreutils. On macOS,
use those tools on PATH for `make verify`, and place worktrees under the Docker
VM's shared `/Users` mount so Compose can read its isolated test secret files.
The deployment verifies service startup, the MCP handshake, tools/list,
phone_devices, absent/invalid Access credentials, and authenticated access.
It must not create a phone session or send a real notification as a smoke test.
Verify the old Sender and both Appium health endpoints before and after apply.

Device configuration lives in `/etc/pi-appium-mcp/devices.json`, outside Git.
Keep stable aliases across reinstallations. Only phones actually found by ADB
are added; two Appium listeners do not prove two phones are connected.

Stop the dedicated MCP and tunnel units to withdraw the endpoint. Keep the
previous application directory and Node runtime for rollback. Do not restart,
upgrade, or reconfigure the existing Sender, agent, Appium, or Pi tunnel.

## Release

Use the protected `production-appium-mcp.yml` workflow on an exact reviewed main
commit after `CI / verify`. Workstation dispatchers are read-only by default:

```text
make pi-mcp-deploy DEPLOY_ARGS="--target-commit <full-sha>"
make pi-mcp-deploy DEPLOY_ARGS="--apply --target-commit <full-sha>"
make pi-mcp-health TARGET_COMMIT=<full-sha>
```

The runner stages a complete offline npm cache and the SHA-256-verified ARM32
Node archive. Candidate import/transport tests run on the actual Pi before
activation. Preflight may create the isolated runtime/user but never starts a
phone session or changes existing services. Apply provisions a dedicated Access
application, 90-day service token and remotely managed tunnel. DNS is published
only after Access and the connector's JWT-audience check are configured.

Cloudflare provisioning requires Access applications/policies/service-token,
Tunnel and zone DNS edit permissions on the protected Actions API token.
Missing permission must fail closed; do not weaken Access to get a healthy URL.
New client credentials are stored only in root-owned
`/etc/pi-appium-mcp/cloudflare.json` on the Pi. A trusted agent administrator
must transfer them through an approved secret store, not chat or Git. Give each
additional agent its own token and app-scoped policy. Tokens expire after 90
days; renewing or rotating them is a separate owner-approved operation.

`withdraw` disables only the two new MCP units. The protected `rollback`
operation restores the recorded previous candidate, or withdraws the two new
units when no previous release exists. Failed Appium session cleanup requires operator diagnosis; never
delete a foreign session or restart Appium to clear a busy lock.
