# Pi Appium MCP

An isolated deployment of `appium-mcp` 1.99.1, using the existing Pi Appium
servers and the shared `/run/wechat-device` ownership contract. The service
binds to `127.0.0.1:3333/mcp`. Public traffic goes through a dedicated Cloudflare
Tunnel and an Access application allowing owner-only managed OAuth and one
dedicated machine service token for protected automation.
The connector also validates the Access JWT audience. Appium itself is not
published by this service.

The default Pi Node installation is not changed. The service uses a verified,
isolated Node 22.23.4 ARM32 runtime and a locked npm dependency tree. The
optional documentation/ML stack is omitted. No phone session is created at
service startup, during health checks, or while listing tools/devices.

## Client

Connect a Streamable HTTP MCP client to:

```text
https://appium-mcp.zacks.vision/mcp
```

Select OAuth in the client's remote MCP configuration, enter the URL, and
complete the Cloudflare login/consent prompt. Only the pinned owner's identity
through the existing Cloudflare login provider is allowed; being another member
of the Cloudflare account does not grant phone access. This is a separate,
application-scoped authorization, not reuse of the Cloudflare management plugin's
token. Existing Cloudflare browser login can simplify the first login.

For a Codex CLI version supporting remote MCP OAuth:

```text
codex mcp add pi-appium --url https://appium-mcp.zacks.vision/mcp
codex mcp login pi-appium
```

No custom authentication headers or manually copied tokens are needed. Access
tokens expire after 15 minutes; capable clients refresh silently for a grant of
up to seven days. Grant expiry requires another interactive login. A headless
agent must have an initial authorization flow and protected token storage; this
is not permanent unattended access. Managed OAuth is currently a Cloudflare Beta.
Clients must support OAuth discovery, resource indicators, DCR, PKCE S256 and
refresh tokens. Supported redirects are loopback/localhost (Codex desktop/CLI)
and the documented ChatGPT connector callbacks, not arbitrary HTTPS domains.
Use the callback displayed by the actual client; do not disable callback checks
for an unsupported platform.

### Protected machine automation

Existing GitHub health checks retain the dedicated service token. Only an
administrator integrating a non-OAuth trusted client needs these headers,
supplied from that client's secret store:

```text
CF-Access-Client-Id: <dedicated-client-id>
CF-Access-Client-Secret: <dedicated-client-secret>
```

The dedicated token does not authorize other Access applications. Never put
its values in source, tool arguments, chat, build artifacts, or logs. Enabling
OAuth does not rotate, export or replace this token.

### Phone control

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

The existing Airflow maintenance DAG may reboot the phone at 05:00 Asia/Shanghai
on its configured days. That authorized ADB maintenance is outside the MCP
session lock. Clients must handle the offline interval and create a new session
only after the phone is ready again. Do not override a busy or foreign session.
Release acceptance waits for Sender readiness after scheduled maintenance;
it does not change the maintenance schedule or promise uninterrupted sessions.

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

Candidate tests keep all assertions and fail closed. The installer parses JUnit
and retains only case numbers, exit status and fixed failure booleans in a
root-only report, never raw test output. An incomplete test report is a failure.
Before installing another candidate it may reclaim owner-matched, complete-source
directories that have no verified release marker, after saving sanitized metadata.
Current/previous targets, verified releases, symlinks and ambiguous directories
are never reclaimed. Runtime state and credentials are outside this namespace.

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

### Domain-only changes

The canonical hostname is `appium-mcp.zacks.vision`. The previous
`appium-mcp.claude89757.cc` hostname is retired after new-host acceptance.
The protected operation reuses the same Access application, audience, dedicated
service token and Tunnel. It first protects and routes both hostnames, validates
the new URL, then retires only the owned old DNS record and ingress. Failure
restores the captured configuration and verifies the previous working endpoint.
No phone sessions are created, no credentials are rotated and no host units are
restarted. A busy phone controller aborts preflight before Cloudflare writes.

Use separate exact identities for the reviewed operations code and the unchanged
installed runtime. Both must pass their exact CI gate:

```text
make pi-mcp-domain RUNTIME_COMMIT=<runtime-sha> DEPLOY_ARGS="--target-commit <operations-sha>"
make pi-mcp-domain RUNTIME_COMMIT=<runtime-sha> DEPLOY_ARGS="--apply --target-commit <operations-sha>"
make pi-mcp-health TARGET_COMMIT=<operations-sha> RUNTIME_COMMIT=<runtime-sha>
```

### OAuth-only changes

Use protected `oauth_preflight` / `oauth_apply`, preserving the exact installed
runtime as for domain-only changes:

```text
make pi-mcp-oauth RUNTIME_COMMIT=<runtime-sha> DEPLOY_ARGS="--target-commit <operations-sha>"
make pi-mcp-oauth RUNTIME_COMMIT=<runtime-sha> DEPLOY_ARGS="--apply --target-commit <operations-sha>"
make pi-mcp-health TARGET_COMMIT=<operations-sha> RUNTIME_COMMIT=<runtime-sha>
```

The runner resolves the pinned Cloudflare user ID through `/user` or accepted
account membership without logging identity data. The deployment token needs
User Details Read for that owner or Account Settings Read for membership lookup,
in addition to existing Access permissions. Missing permission fails preflight
before any configuration write. Do not fall back to Everyone, account-wide
membership, a different email, or a different login method.

Apply preserves the application audience, dedicated service policy/token,
Tunnel and DNS. It adds exactly one owner Allow policy with the pinned Cloudflare
login-method requirement and bounded OAuth/DCR settings. Failure restores and
verifies the captured application/policies. Host service start identities must
remain unchanged. Acceptance checks anonymous, invalid machine credentials and
invalid Bearer denial, owner policy, discovery, PKCE advertisement and the existing
authenticated read-only MCP probe. These do not prove a user completed OAuth:
reports explicitly retain `oauthLoginVerified: false` until a real client login
and read-only MCP call have been separately verified. No synthetic notification
or phone session is necessary. Only the owner's client stores its resulting
OAuth tokens; never place them in CI logs or artifacts.

References: [Cloudflare managed OAuth](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/),
[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp),
[ChatGPT OAuth callbacks](https://developers.openai.com/plugins/build/auth#redirect-url).

### Application Lifecycle

Application apply refreshes only the dedicated connector unit while retaining its existing
credentials. It waits for cloudflared's loopback-only `127.0.0.1:49393/ready`
before checking Cloudflare status and publishing DNS. Preflight checks the
required flags and the service identity's ability to execute cloudflared.
Warning logs use cloudflared's rotating `--log-directory` (1 MB plus five
backups), in a service-private `0700` systemd LogsDirectory. Debug logging is
never enabled. Only readiness, process counts/status and fixed error categories
can cross the operations boundary; raw logs and credential values cannot.
A previously withdrawn candidate is not an active rollback target.

`withdraw` disables only the two new MCP units. The protected `rollback`
operation restores the recorded previous candidate, or withdraws the two new
units when no previous release exists. Failed Appium session cleanup requires operator diagnosis; never
delete a foreign session or restart Appium to clear a busy lock.
