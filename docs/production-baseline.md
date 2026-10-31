# Production Baseline

## Baoan candidate debugging on 2026-10-31, 08:01 UTC

[PR #274](https://github.com/claude89757/wechat-on-airflow/pull/274) corrected
availability classification using the page's pure `isAvailableStatic` predicate
and restored the old four-second initial browser warm-up. Exact-main commit
`ae1f8dc8aa3aa48aceb6a291698dbf5682fe4961` passed
[CI 41182616409](https://github.com/claude89757/wechat-on-airflow/actions/runs/41182616409).
Its protected [Pi preflight 41182781096](https://github.com/claude89757/wechat-on-airflow/actions/runs/41182781096)
successfully verified all five Dashah dates (October 31 through November 4).
The live pure predicate matches the previously inspected provider implementation;
renderer coverage remains incomplete and `bookability_verified` remains false.
This run reached Baoan but failed with `scrape_not_verified`, no retained source
exception code and no source snapshot. This is different from the earlier Dashah
captcha failure; it does not establish a Baoan captcha or successful Baoan parsing.
No apply, release tag or synthetic notification occurred.

The pre-change [Airflow health 41182042963](https://github.com/claude89757/wechat-on-airflow/actions/runs/41182042963)
passed for `c3fb88ccdef7a381643f6df5e3dac4ccc63e06e5`. Public and origin Host Core
health endpoints report `9cca72d73eb05c502446bd1d947c4307d7f73f35`, while the remote
repository is at the Airflow commit. A [read-only Host Core check 41182464849](https://github.com/claude89757/wechat-on-airflow/actions/runs/41182464849)
using the API's SHA was consequently rejected by the remote-worktree identity
guard. Neither component SHA alone satisfies all existing health identities;
the coupled release must reconcile them, without reimporting D1.

The following [preflight 41183535577](https://github.com/claude89757/wechat-on-airflow/actions/runs/41183535577)
on `2723b8e3a3efa71b530b66a6e5711bd1b6f4d3f5` stopped at Dashah with
`schedule_not_ready`: document complete, no schedule component, zero cells,
and both challenge text/mask flags false. It did not reach Baoan. A single
successful Dashah run therefore does not establish reliable source availability
or prove that the warm-up change resolved all earlier failures. Diagnostic
preflight now inspects both independent venues once while retaining a failed
overall gate if either fails; production activation requirements remain unchanged.

## Cursor MCP Callback Repair On 2026-10-31

The owner reported `redirect_uri is not allowed by the account configuration`
from Cursor/Grok. Cursor's public client metadata at
`https://cursor.com/oauth/mcp-client.json` declares exact agents, bot, Grok and
loopback callbacks. The desktop DCR also supplies the owner-reported
`cursor://anysphere.cursor-mcp/oauth/callback`. A standard MCP SDK registration
probe with this callback set failed with `InvalidClientMetadataError` before
login. Existing protected health run
[41180959376](https://github.com/claude89757/wechat-on-airflow/actions/runs/41180959376)
passed with 18 tools, one online phone and no phone sessions.

The repair adds only these four non-loopback callback URIs to the existing
allowlist. Localhost/loopback were already enabled. Owner-only login, PKCE,
grant duration, machine credentials and installed Pi runtime are unchanged.
Deployment and repeat DCR acceptance must be recorded before claiming repair;
the owner must still complete the real client login. No phone sessions or
notifications are permitted during verification.

## Baoan YDMap Production Acceptance Blocked On 2026-10-31

The external Baoan contribution [PR #262](https://github.com/claude89757/wechat-on-airflow/pull/262)
was integrated through [PR #263](https://github.com/claude89757/wechat-on-airflow/pull/263),
with follow-ups [#265](https://github.com/claude89757/wechat-on-airflow/pull/265)
and [#267](https://github.com/claude89757/wechat-on-airflow/pull/267). The resulting main commit
`302d90a3a0b8f1f07b31c5a4b71039b1c641b8c2` passed its complete
[exact-main push CI 41178652599](https://github.com/claude89757/wechat-on-airflow/actions/runs/41178652599).
The original PR is closed as superseded, with its contributor attribution retained in the integrated commit.
Merged code and passing CI do not establish production availability acceptance.

The first protected [Pi preflight 41177429612](https://github.com/claude89757/wechat-on-airflow/actions/runs/41177429612),
against `9758330d9fcdc462c442a513479b8814c94b37a5`, returned generic
`operation_failed` with no inspections. Its original exception class was not retained.
Code review and a local executable-lookup reproduction found that the isolated
candidate's restricted PATH omitted `/usr/sbin`, while its launcher used bare
`runuser`. PR #267 switched both launch sites to the checked absolute executable
and retained bounded, allowlisted exception/stage diagnostics. The local reproduction
supports this cause; the first production report did not itself record `FileNotFoundError`.

The second protected [Pi preflight 41179031523](https://github.com/claude89757/wechat-on-airflow/actions/runs/41179031523),
against `302d90a3a0b8f1f07b31c5a4b71039b1c641b8c2`, passed the exact-main/CI gate
and reached candidate venue inspection. It stopped on Dashah (`dsh`) with
`failure=access_verification`, `sourceFailure=captcha`, page host `wxsports.ydmap.cn`,
zero cells and `inspections=[]`. Baoan was not reached. No validated renderer source
or bookability evidence was obtained; neither empty availability nor Baoan access
success can be inferred. Presence flags only indicate diagnostic keys existed.

No Pi YDMap apply, Baoan production release, `0.9.0` release tag or test notification
was performed. The post-attempt protected
[health run 41179265173](https://github.com/claude89757/wechat-on-airflow/actions/runs/41179265173)
passed at 2026-10-31 07:07 UTC against expected and deployed
`c3fb88ccdef7a381643f6df5e3dac4ccc63e06e5` (release `0.8.7`). It reported healthy
services, 29 existing DAGs, zero import errors and no recent failed DAG runs. The
paid Dashah DAG's latest three scheduled runs succeeded. These runtime checks do
not supply the missing candidate source or Baoan bookability evidence.

A separate read-only [Host Core observation diagnosis 41179428118](https://github.com/claude89757/wechat-on-airflow/actions/runs/41179428118)
used that Airflow SHA as its expected identity and stopped at
`local host-core deployment identity mismatch`. It emitted no business report,
actual Host Core SHA, venue observation or scope timestamps. The failed identity
expectation does not establish a new production fault or a common component
version. Verify actual component identities before the next coupled release;
do not treat this attempt as evidence of healthy persisted observations.

Provider requests and apply remain stopped at this access-verification blocker.
Resume only after legitimate provider access is available, through the existing
exact-main CI and protected-environment gates, isolated candidate preflight for both venues and actual
source/bookability review. A subsequent apply must retain the bounded scoped DAG
pause/drain/restore, rollback, installed-version and live-inspection checks; downstream
release, natural-cycle acceptance and tagging retain their existing full gates.
Do not bypass access verification or automatically repeat the blocked requests.

## 2026-10-31: Dedicated Free-Court Group Restored, Shared Groups Paused

Per the user's latest request, new Dashah free-court messages now target
`Zacks_大沙河限定免费` alone. The two existing shared Zacks groups remain
stored in the `SZ_TENNIS_CHATROOMS` Airflow Variable for possible future
resumption but are filtered before new durable WeChat enqueue operations from
every automated venue watcher. Other independent group recipients remain
untouched. Do not replace the shared variable with the dedicated group name,
as that would redirect unrelated venue alerts into the free-court-only group.

The read-only delivery diagnosis and explicitly approved probe aliases reflect
active recipients and count paused recipients without disclosing their names.
Verify deployment, three natural free-court cycles and expiry of the old
five-minute queued-intent window before declaring the old recipient path
inactive. Retain historical outbox and dedupe state; send no synthetic alerts.

## Pi MCP OAuth Acceptance On 2026-10-31

The canonical MCP endpoint `https://appium-mcp.zacks.vision/mcp` now supports
owner-only Cloudflare Managed OAuth. Operations commit
`dfa1cabf41606a7c53d7488dc9df1bae4dcbf49c` passed
[exact-main CI 41178012459](https://github.com/claude89757/wechat-on-airflow/actions/runs/41178012459),
[protected preflight 41178608944](https://github.com/claude89757/wechat-on-airflow/actions/runs/41178608944)
and [protected apply 41178679434](https://github.com/claude89757/wechat-on-airflow/actions/runs/41178679434).
The installed Pi runtime remains `837f7efe35ae5a7042584509c0859879407e5903`.
All five monitored host service start identities remained unchanged, and no
credential was rotated. There are still 18 tools, one configured/online phone
and zero active phone sessions; a second phone is not established by this work.

Live Access configuration has exactly the dedicated machine policy plus the
pinned owner's Allow policy through the existing Cloudflare login provider.
Other account members are not phone operators. Access tokens last 15 minutes,
with a seven-day refresh grant. DCR permits loopback/localhost and the documented
ChatGPT callback paths only. The sole new WAF rule matches the exact MCP hostname
and skips `bic` only, retaining Access, unrelated hostnames and other WAF checks.
The application audience, Tunnel, DNS and existing machine credentials are unchanged.

[Post-apply health 41178756304](https://github.com/claude89757/wechat-on-airflow/actions/runs/41178756304)
and [idempotent preflight 41178811262](https://github.com/claude89757/wechat-on-airflow/actions/runs/41178811262),
followed by [health 41178967478](https://github.com/claude89757/wechat-on-airflow/actions/runs/41178967478),
passed: RFC 9728 discovery, PKCE S256 advertisement, anonymous/invalid machine
and invalid Bearer denial, authenticated read-only MCP and unchanged host runtime.
The repeated preflight made no configuration writes. A separate standard MCP SDK
probe, without authentication headers, successfully registered a public OAuth
client and prepared a resource-bound PKCE authorization request. It stopped
before login: zero user tokens, phone sessions or external test notifications
were acquired/created/sent. The first real client still requires the owner to
complete Cloudflare login/consent; no end-to-end user OAuth login is claimed.

[Post-change Airflow health 41178931979](https://github.com/claude89757/wechat-on-airflow/actions/runs/41178931979)
passed against the unchanged `c3fb88ccdef7a381643f6df5e3dac4ccc63e06e5`
business release. This MCP control-plane change does not deploy the separate
venue/YDMap work concurrently merged into the repository.

Managed OAuth remains a Cloudflare Beta. Existing connector DNS-refresh timeout
categories remain observable with readiness true and zero restarts; this release
does not claim to fix them. Existing 23 moderate npm runtime audit advisories and
the separate legacy public raw Appium surface are unchanged.

## Pi MCP OAuth Policy On 2026-10-31

The first OAuth-only attempt at operations commit
`bf33e578750db53727d9a029ca2a55f509524752` passed
[exact-main CI](https://github.com/claude89757/wechat-on-airflow/actions/runs/41175526455)
and [read-only preflight](https://github.com/claude89757/wechat-on-airflow/actions/runs/41176146352).
[Apply 41176227450](https://github.com/claude89757/wechat-on-airflow/actions/runs/41176227450)
was not accepted. Zone HTTP/security analytics identified nine `/mcp` 403s from
Browser Integrity Check during the attempt, including the OAuth discovery
retries; no discovery endpoint was reached. Audit records confirm that the
requested owner-only OAuth settings were stored and then disabled again.
The original machine-only policy was restored and independently verified through
[protected previous-operations health 41176381601](https://github.com/claude89757/wechat-on-airflow/actions/runs/41176381601).
The automatic rollback flag was
false because Cloudflare added inactive default DCR fields to disabled OAuth;
that structural comparison did not prove an authorization restore failure.
The follow-up requires an exact-host, BIC-only skip rule, semantic disabled-OAuth
restore checks and fixed non-secret failure reasons. No service was restarted,
phone session created or test notification sent. That attempt did not establish
OAuth acceptance; the successful follow-up is recorded above.

The owner approved managed OAuth for Codex-like agents instead of manually
copying Access service-token headers. The protected OAuth-only
operation enables owner-only Cloudflare login on the existing application,
with 15-minute access tokens and a seven-day refresh grant. It preserves the
dedicated machine token/policy, application audience, DNS, Tunnel and installed
runtime. The owner identity is resolved only inside the protected runner;
other account members are not phone operators. Managed OAuth remains Beta.
Passing discovery and machine-auth probes is not evidence of a completed owner
OAuth login; that final client action must be recorded separately. No phone
sessions or notifications may be created for OAuth acceptance.

## Pi MCP Domain Policy On 2026-10-31

The owner requested `https://appium-mcp.zacks.vision/mcp` as the canonical
endpoint, replacing the previous `claude89757.cc` hostname below. Use the
protected `domain_preflight` / `domain_apply` lifecycle from the component
runbook, with explicit operations-code and installed-runtime commits. This
changes Access destinations, the dedicated Tunnel's remote ingress and owned
DNS records only; the installed MCP runtime, Access audience, machine credentials
and host units remain unchanged. Authenticate and verify the new endpoint before
retiring the old route, and restore the captured state on a failed cutover.
Successful protected operation/health reports establish acceptance; changing a
URL in configuration alone does not establish a completed migration. Historical
runtime acceptance below remains valid for that runtime, not proof of the new
hostname's acceptance.

## Pi MCP Production Acceptance On 2026-10-31

The independent MCP service runs
`837f7efe35ae5a7042584509c0859879407e5903`, not the Airflow component's release.
Its [exact-main CI](https://github.com/claude89757/wechat-on-airflow/actions/runs/41133807591),
[ARM32 preflight](https://github.com/claude89757/wechat-on-airflow/actions/runs/41134545238)
and [protected apply](https://github.com/claude89757/wechat-on-airflow/actions/runs/41135173127)
passed. Public acceptance at `https://appium-mcp.claude89757.cc/mcp` rejected
absent and invalid credentials, and verified authenticated MCP handshake,
18 tools, one configured/online phone and zero active phone sessions. No real
phone session or test notification was created. The dedicated tunnel reported
four healthy edge connections; DNS was published only after connector readiness.
Existing credentials were reused, not rotated. Sender, device agent and old Pi
tunnel start timestamps remained unchanged. Only one physical phone was observed;
a second phone still requires attachment, ADB authorization and explicit mapping.

Three subsequent protected health checks passed:
[41136107257](https://github.com/claude89757/wechat-on-airflow/actions/runs/41136107257),
[41136216778](https://github.com/claude89757/wechat-on-airflow/actions/runs/41136216778)
and [41136473252](https://github.com/claude89757/wechat-on-airflow/actions/runs/41136473252).
Each verified local connector readiness, zero connector restarts, correct public
authorization and one online phone, without creating a phone session. Independent
workstation checks returned HTTP 401 for both absent and invalid credentials.
The [post-apply Airflow health check](https://github.com/claude89757/wechat-on-airflow/actions/runs/41136588394)
passed against its unchanged `c3fb88ccdef7a381643f6df5e3dac4ccc63e06e5` release,
with no recent DAG failures. The Pi-dependent Dashah International venue DAG's
three most recent natural runs all succeeded after MCP activation. Original
Sender and Airflow Tunnel health remained normal.

The original connector failure was not reproduced in this successful attempt;
its exact cause remains unproven. Native readiness and private bounded diagnostics
improve the evidence, not proof that a specific network or authentication fault
was repaired.

The legacy public raw Appium route remains a separate unprotected surface.
New MCP Access authorization does not secure that route, and shared locks only
coordinate participating controllers. Inventory existing callers before an
approved restriction. The Pi had approximately 2.16 GB free after apply;
candidate preflight retains its 2 GB free-space gate and must not delete verified
or ambiguous candidates merely to bypass it.

## Pi MCP Candidate Inspection On 2026-10-31

Release `779e398f694bc4217401dd1d3a4a479604f328e0` passed exact-main CI and
[actual-host preflight 41129486055](https://github.com/claude89757/wechat-on-airflow/actions/runs/41129486055),
including all 11 fake-device tests. [Apply 41130363057](https://github.com/claude89757/wechat-on-airflow/actions/runs/41130363057)
activated the local MCP, then failed waiting for its new Cloudflare connector.
Automatic withdrawal was verified. The dedicated Access app, service token and
remotely managed tunnel were created; no public DNS record was published.
Read-only checks verified the stored token's account/tunnel association, matching
token file, executable permissions and supported flags. The connector ran until
withdrawal but never registered an edge connection; its output had been discarded,
so the exact connection failure remains unproven. The next candidate adds private
rotating warning logs, fixed-category diagnostics and native local readiness,
without rotating credentials or reconfiguring the old tunnel. Existing Sender,
agent and tunnel start timestamps remained unchanged. Zero real phone sessions
or test notifications were created.

Release `419269c00361deae177a225874b5de064406ef3d` passed
[actual-host preflight](https://github.com/claude89757/wechat-on-airflow/actions/runs/41122132103),
then [activation 41123431445](https://github.com/claude89757/wechat-on-airflow/actions/runs/41123431445)
stopped before configuration or service creation. The candidate npm log recorded
exit 0; the retained cache and missing verification marker locate failure in the
following tests. An isolated reproduction with fake devices passed. The original
test output was discarded, so its exact failed assertion is unknown, not fixed
by a successful rerun. Structured, redacted JUnit evidence is now preserved on
failure, without skipping assertions or changing timeouts. Generated incomplete
candidates may be reclaimed through the protected installer only after preserving
sanitized metadata; active, previous, verified and ambiguous directories remain.
Existing services and their start timestamps were unchanged; no real phone
session or test notification was created.

The repaired source passed actual ARM32
[preflight 41117458521](https://github.com/claude89757/wechat-on-airflow/actions/runs/41117458521).
The [first activation](https://github.com/claude89757/wechat-on-airflow/actions/runs/41118215287)
then stopped before service creation or Cloudflare provisioning. Read-only
inspection found a verified candidate and valid device mapping but no active
release, device configuration or new systemd unit. A regression reproduced
`Path.open()` rejecting the unsupported `opener` argument in the private JSON
writer. The repair uses an owner-only temporary file and atomic replacement,
cleans failed writes, exercises that path during preflight, and preserves only
allowlisted remote exception classes. Existing services remained active; zero
phone sessions or external test notifications were created.

The first protected MCP preflight for `577dfae1036f64a05b7bbb20b390108f9a896db6`
passed Cloudflare permissions and pinned SSH, then failed before activation
([run 41113735347](https://github.com/claude89757/wechat-on-airflow/actions/runs/41113735347)).
Read-only inspection confirmed the isolated ARM32 Node worked and existing
Sender, agent and Pi Tunnel remained active. The candidate had no source files.
Running the workflow's archive command from its declared subdirectory reproduced
an empty archive. The repair archives from the repository root and validates
required files both before transfer and before dependency installation. No MCP
public route or phone session was created by this failed preflight.

Read-only inspection found a Raspberry Pi 5 with an aarch64 kernel, 32-bit
Raspbian 12 userland, Python 3.11.2 and Node 16.20.2. Both existing Appium 2.18.0
listeners were ready. The Sender, device agent and existing Pi Tunnel were
active; Sender health/readiness returned HTTP 200. The shared device-lock
directory was configured. ADB and USB enumeration found one authorized phone,
not two. No phone sessions or external notifications were created by inspection.

The legacy public Appium hostname returned Appium readiness and an empty
session list without credentials. This is a pre-existing access-control risk,
not evidence that new MCP access is protected. Inventory existing callers before
restricting that route. New MCP Access credentials must not be reused to provide
unrestricted raw Appium access.

The guarded MCP implementation and dedicated Cloudflare route are a candidate
until exact-main CI, actual ARM32 preflight and positive/negative public-auth
checks pass. This entry does not claim it has been deployed.

## Offline ARM32 Dependency Staging On 2026-10-27

The [protected preflight at 13:28:32 Asia/Shanghai](https://github.com/claude89757/wechat-on-airflow/actions/runs/40454944844/job/122025979634)
for `43e540706bccd23bd8221385333dce6dc320c716` verified the Pillow artifact,
then reached the 300-second full-lock installation limit. The bounded report
observed network retries and retrieval progress. Its last observed locked
requirement was `wsproto==1.3.2`; that is not evidence that this package or a
particular remote host caused the timeout. The active Sender stayed healthy
and unchanged, with zero external test sends. Exact-main
[CI passed](https://github.com/claude89757/wechat-on-airflow/actions/runs/40454919774/job/122025894675).

A public download-only probe resolved all 27 locked wheels for ARM32 CPython
3.11 without installing or executing them. The reviewed manifest at
`config/sender-arm32-wheelhouse.json` records 15,352,728 bytes: 26 wheels matched
to pinned-version official PyPI release metadata, plus the verified piwheels
Pillow artifact. The protected runner stages this complete set in a stored ZIP.
Both host paths independently validate private copies, exact lock closure,
archive structure, sizes, hashes, wheel metadata, native tags and absence of
direct URL dependencies. Only then may the ARM32 install use `--no-index`,
the private wheel directory and binary-only selection, with pip config/environment
sources disabled. Other platforms keep their existing source policy; unsupported
ARM32 interpreters fail before installation. The 300-second candidate limit,
version pins, isolation, image checks and activation gates remain required.
This records the repair and its evidence, not actual-host release acceptance.

## Sender Full-Lock Timeout On 2026-10-27

The [protected candidate preflight](https://github.com/claude89757/wechat-on-airflow/actions/runs/40453041373/job/122019940953)
for `7b90b48cd2468acbda32b89bcd3254e6f3654af2` verified the staged ARM32 Pillow
artifact, then reached the existing 300-second limit during the full-lock pip
installation. The active Sender stayed healthy and unchanged. This establishes
neither a missing package nor a network, build or resolver root cause.

The timeout handler previously discarded the partial stdout/stderr retained by
Python. The diagnostic now decodes only bounded tails and emits fixed network
and progress categories, preserving `timeout` as the primary failure. Progress
and the last observed locked requirement use stdout alone; separate stream
buffers have no shared chronology. An observed requirement is not a proven
failing package. Both producer and CLI validate the fields; raw output, paths,
URLs and credentials remain private. Installation commands, indexes, pins,
timeouts, isolation and activation gates are unchanged.

## Verified ARM32 Wheel Staging On 2026-10-27

The [actual-host preflight at 2026-10-27 12:32:53 Asia/Shanghai](https://github.com/claude89757/wechat-on-airflow/actions/runs/40450223975/job/122010955609)
enabled the Pillow-specific ARM32 source but still reported
`Pillow==13.0.0` with `no_matching_distribution`. That report does not distinguish
bootstrap from full-lock rediscovery and does not establish the host's exact
index response. The active Sender remained healthy and unchanged. The same
`b11d4a9f42528a337adb06c5f976fac90b265ce3` source passed
[all exact-main CI gates](https://github.com/claude89757/wechat-on-airflow/actions/runs/40450203429).

The follow-up makes the known public wheel available as a verified local
artifact: the protected runner downloads the exact HTTPS wheel, checks its
SHA-256 and transfers it through the existing scoped SSH channel alongside the
Git bundle. Both candidate and apply paths create private copies, then verify
the hash, exact lock pin, package metadata and interpreter tag compatibility
before supplying a directory containing only that wheel to the full-lock pip
command. Other dependencies keep their original indexes. The temporary upload
remains available through installation and is removed by the operation's
normal or rollback cleanup; no active dependency directory is copied or reused.

The public wheel metadata confirms Pillow 13.0.0, Python >=3.11 and
`cp311-cp311-linux_armv7l`. Hash and availability were independently checked;
the protected actual-host install, dependency/image checks and full release
acceptance remain required. This section records the staging repair and its
evidence, not a production deployment acceptance.

## ARM32 Pillow Source Repair On 2026-10-27

The [follow-up protected Sender diagnosis](https://github.com/claude89757/wechat-on-airflow/actions/runs/40448846588/job/122006510383)
at 2026-10-27 12:17:36 Asia/Shanghai identified the exact failure as
`Pillow==13.0.0` with `no_matching_distribution` and exit code 1. Candidate
pip 23.0.1 reported ARM32 tags true, ARM64 tags false and a native CPython ABI.
The live service stayed enabled, active and ready; no active environment was
changed and no external test message was sent.

The bounded source repair uses the fixed HTTPS Pillow-only listing at
`https://www.piwheels.org/simple/pillow/` only for a 32-bit interpreter with
compatible ARM32 pip tags. It bootstraps the exact locked Pillow requirement
with `--no-deps` and binary-only selection, then runs the existing full-lock
installation without adding that source to other dependencies. The interpreter,
pin, TLS checks, environment isolation and activation/health gates stay in force.

A separate public download probe selected
`pillow-13.0.0-cp311-cp311-linux_armv7l.whl` (1,317,640 bytes), SHA-256
`49eb06898ec42888e47c1cf1a97cb64b29af2b5d2773be60db1b1ecbbf92c3a6`.
This confirms wheel availability, not actual-host runtime compatibility. The
candidate must still pass the protected full dependency and image-operation
preflight before any production apply. The
[PyPI release files](https://pypi.org/project/pydantic_core/2.46.4/#files)
already supply the locked `pydantic_core` CPython 3.11 ARM32 wheel, so its
package source is unchanged.

## Sender Candidate Install Blocker On 2026-10-27

The protected [Sender dry-run at 2026-10-27 11:59:56 Asia/Shanghai](https://github.com/claude89757/wechat-on-airflow/actions/runs/40447148459/job/122001028089)
targeted `e02b037612bbdf00a297c791c22ec3440a5fd306` and stopped at
`candidate_locked_install_failed`. The actual service uses Python 3.11.2 with
32-bit pointers on Raspbian 12, while its platform reports `linux-aarch64`.
The live Sender remained enabled, active and ready at
`1de8a876c5a5bd00b285262eb59c258f910be298`; `applied` and
`active_environment_changed` were false, and `external_test_sends` was zero.
The temporary candidate did not reach dependency or image-operation validation.

The initial report deliberately withheld raw package-index output and cannot
establish whether the cause is package availability, network access or dependency
resolution. A diagnostic-only follow-up preserves the exact install command,
version locks and activation gates while adding bounded failure categories,
an exact lock-validated failed requirement and pip ABI-tag booleans. It neither
changes platform selection nor upgrades pip. Raw output, URLs and credentials
remain private. The routing and retired-scope fixes are merged, and exact-main
CI for `e8a23a0258d79a5141ca9df5e0c4470462f7fb23`
[passed](https://github.com/claude89757/wechat-on-airflow/actions/runs/40447375080),
but production apply remains blocked pending a successful actual-host preflight.

## Retired Shenzhen Bay Observation Scope On 2026-10-27

The protected
[preflight diagnosis at 2026-10-27 11:49:42 Asia/Shanghai](https://github.com/claude89757/wechat-on-airflow/actions/runs/40446284109/job/121998250113)
found the already-retired `szw:check_and_notify_day_3` observation unhealthy and
stale, with its last observation on 2026-10-20. The other 30 stored observation
scopes were healthy and fresh. The existing business health check still included
that historical row, despite the explicitly approved removal of the fourth-day
task from the active schedule on 2026-10-20.

The follow-up health policy records only that exact retirement in
`config/host-core-contract.yaml` and validates that the task remains absent from
the active manifest. It keeps all stored rows in the acceptance report, adds
checked/retired counts and retirement metadata, and checks every other stored
scope without an allowlist filter. Unknown or active unhealthy/stale observations
still fail, as does an empty active set. Reactivating the task without revising
the retirement policy fails closed. No database record or heartbeat is changed.
All 26 venue checks, three natural cycles, worker and actual delivery evidence
remain mandatory. This records a verified preflight blocker and its repair
contract; it is not production deployment acceptance.

## Dashah Free-Court Routing Change Requested On 2026-10-27

The user requested that `Zacks_大沙河限定免费` stop receiving alerts and that
the same future availability content go to the two existing shared Zacks groups.
The target configuration is `SZ_TENNIS_CHATROOMS`, already used by the other
general tennis watchers, rather than the separate sports-center recipient list.

The protected delivery diagnosis in
[run 32148663652, job 99194737546](https://github.com/claude89757/wechat-on-airflow/actions/runs/32148663652/job/99194737546)
recorded two general targets, three sports-center targets and one dedicated
free-court target on 2026-08-30. This is historical recipient-count evidence;
it does not establish the current deployed routing or expose protected values.

The pre-change protected
[health check at 2026-10-27 11:38:58 Asia/Shanghai](https://github.com/claude89757/wechat-on-airflow/actions/runs/40445217745/job/121994792357)
confirmed Airflow commit `f6843b04a611442739123ed985b298cc866c3d8d`, all 12
services healthy, no missing configuration or import errors, and three successful
natural free-court inspections. It did not report current recipient counts.

The revised watcher and operations scripts resolve free-court recipients from
the existing shared configuration. No dedicated-group fallback remains. Preserve
the observation-before-delivery ordering, booking-link policy and dedupe history;
do not replay historical alerts. Production completion requires exact-commit CI,
protected deployment, current target-count verification and three successful
natural free-court inspection cycles. This section records the requested change,
not a claim that it has already been deployed.

## Shenzhen Bay Three-Day Coverage Authorization On 2026-10-20

The daytime cadence update was applied to Web and Airflow at commit
`1a8bd9815e3c82cca4701efd7066bd4b40577ab4` by
[run 39374041918](https://github.com/claude89757/wechat-on-airflow/actions/runs/39374041918).
The post-deployment
[diagnosis at 05:31:41 UTC](https://github.com/claude89757/wechat-on-airflow/actions/runs/39375337261/job/118472119235)
confirmed matching host/runtime identity and three natural rounds per venue.
Shenzhen Bay intervals were 120 seconds and Greater Bay Area intervals were
180 seconds; each rotated account slots 1, 2, and 3. Shenzhen Bay's `day_0`
through `day_2` each made two successful area queries in every round, while
`day_3` failed with HTTP 200 and API business code 2000 for all three accounts.
Greater Bay Area's three date tasks succeeded in all three rounds. The
independent Airflow health gate failed only on Shenzhen Bay's recent runs;
the applied code was not automatically rolled back and 0.8.5 remained untagged.

A fresh protected
[health check at 11:06:15 UTC](https://github.com/claude89757/wechat-on-airflow/actions/runs/39412385790/job/118593106721)
reconfirmed the same deployed commit before this repair. All 12 services,
imports, DAG registration/pause states and required configuration were healthy.
The only health issue remained Shenzhen Bay's three failed recent runs;
Greater Bay Area's three recent runs were successful. This snapshot confirms
the failure state, without adding task-level evidence or an upstream cause.

At 18:49 Asia/Shanghai, the user explicitly requested removal of Shenzhen
Bay's fourth-day inspection and production deployment. The new approved
coverage is today and the next two calendar days. Retain the existing DAG
and `day_0` through `day_2` task IDs, the 08:00–21:00 window, two-minute
interval, three-account rotation and both booking areas. Retire `day_3` from
the DAG, active manifest and bounded diagnostic task set. This policy change
does not establish the upstream meaning of business code 2000.

Do not delete or rewrite historical task/run records. An immediate deployment
health check can still see failed old runs. Acceptance requires the new exact
commit, three new successful natural daytime rounds per venue after the
deployment cutoff, actual API successes and all three account slots, plus an
independent passing Airflow health check. Only then complete the pending
0.8.5 release tag. New production completion evidence belongs to the follow-up
pull request and protected runs, not to the older failing baseline above.

The retired task's Host Core observation key is
`szw:check_and_notify_day_3` if it has previously been published. At this rollout,
Host Core had no explicit scope-retirement policy. Its full business
acceptance checked every stored scope, so this historical scope could remain
unhealthy/stale even after the active Airflow tasks recover. This component
release does not delete business records, fabricate scope heartbeats, or
claim full Host Core business acceptance. A future Host Core release must
handle retired scopes explicitly while retaining history. Failed observations
clear their availability, and both delivery paths independently reject stale
observations.

## CRLand Daytime Cadence Baseline On 2026-10-20

The protected Airflow health check at `2026-10-20T04:20:23Z`,
[run 39287843611, attempt 2, job 118452073965](https://github.com/claude89757/wechat-on-airflow/actions/runs/39287843611/job/118452073965),
confirmed deployed commit `fc180e806fcb9438fc614a38b1c9d01543303372`
(release `0.8.4`). Airflow 3.3.0, application services, configuration and DAG
imports were healthy. Greater Bay Area had three successful natural runs;
Shenzhen Bay had three failed natural runs. The failure was present before
this schedule change; this report does not establish an upstream cause.

A repeat protected check at `2026-10-20T04:41:56Z`,
[attempt 3, job 118457964761](https://github.com/claude89757/wechat-on-airflow/actions/runs/39287843611/job/118457964761),
confirmed the same deployed commit and the same three-success / three-failure
split. Shenzhen Bay remained the only recent-run health failure.

The protected read-only CRLand diagnosis at `2026-10-20T04:57:39Z`,
[job 118462584534](https://github.com/claude89757/wechat-on-airflow/actions/runs/39372270717/job/118462584534),
and its single retry at `2026-10-20T04:59:28Z`,
[job 118463062486](https://github.com/claude89757/wechat-on-airflow/actions/runs/39372270717/job/118463062486),
localized the Shenzhen Bay failures to `check_and_notify_day_3`. Across the
three account slots, `day_0` through `day_2` each recorded two successful area
queries; `day_3` recorded HTTP `200`, API business code `2000`, and no API
success. These records do not include the upstream business message, so they
do not establish the meaning of that code or the permitted booking horizon
for Shenzhen Bay. Its date coverage remains unchanged.

Both diagnostic attempts identified the old host and runtime commit above.
Their expected new release SHA intentionally differed from production; these
were baseline reads, not successful release acceptance. Greater Bay Area's
metadata collection failed in both attempts and returned no run evidence,
although the independent health checks reported successful Greater Bay Area
runs. No metadata exception category was available in those initial reports;
query timeout or another cause must not be inferred from the generic failure.

The authorized policy change restricts both venues' upstream polling to
`08:00 <= Asia/Shanghai local time < 21:00`, with Shenzhen Bay every two
minutes and Greater Bay Area every three minutes. The existing three-account
pool rotates by each venue's scheduled interval so the three-minute schedule
cannot repeatedly select one account. No credentials are changed.

Acceptance requires exact-commit CI and protected deployment health, matching
Web cadence labels, and three natural successful in-window runs for each
affected venue. Off-hours idle status updates do not prove upstream polling.
Completion evidence belongs to the new release and post-deployment checks;
the baseline above records the pre-change Shenzhen Bay failures.

## CRLand Account Rotation Baseline On 2026-10-19

The pre-change protected Airflow health run
[39274914834](https://github.com/claude89757/wechat-on-airflow/actions/runs/39274914834)
reported deployed commit `1de8a876c5a5bd00b285262eb59c258f910be298`
(release `0.8.3`) at `2026-10-19T15:07:20Z`. Airflow 3.3.0, application
services, the execution API, tunnel and Sender health were available. There
were no import errors, paused active DAGs, missing Variables or missing DAG
sources. The only failing health requirement was recent run history: both
`深圳湾网球场巡检` and `大湾区网球场巡检` had three failed natural runs.
This health result establishes the failure, not its upstream cause.

The authorized repair uses three replacement CRLand accounts in shared
one-minute scheduled rounds. Both DAGs already use the one-minute policy;
the change distributes their requests across accounts while preserving DAG
identities, date coverage and booking areas. Before deploying the pool-aware
runtime, the protected `szw_authorization_sync` operation must validate all
nine account/area combinations and atomically update the pool plus its first
account in the legacy Variable. This keeps the previous runtime usable if an
application rollback is required. No credential values or account claims are
part of this evidence.

Release acceptance requires exact-commit `CI / verify`, a successful protected
configuration sync, and the production Airflow health gate with three natural
successful cycles for both affected DAGs. The per-task rotation log exposes
only account slot `1/3`–`3/3` and scheduled UTC minute for correlation. This
section records the pre-change baseline; completion evidence belongs to the
protected sync and release runs, not to the failing baseline run above.

## Fansibote Chain Ten More Stores On 2026-08-30

Named release `0.6.0` is
`8ec8f53b978f1a7cdb3131b5b088124e357cbb93` (PR #155). Web still runs that
SHA. Airflow was shipped on the same SHA, then a concurrent apply advanced
it to `11783bf6c510eb9ccde982ac4bb68d06a7cca3de` (PR #153, 1-minute venue
default) which still contains the ten new venues. Sender was out of scope
and was not redeployed.

The ten additional PosPal chain tennis venues are on the public catalog:
棕榈泉 (`fsb_zonglvquan` / `泛思博特棕榈泉网球场巡检`), 观湖
(`fsb_guanhu` / `泛思博特观湖网球场巡检`), 坂田 (`fsb_bantian` /
`泛思博特坂田网球场巡检`), 沙河 (`fsb_shahe` / `泛思博特沙河网球场巡检`),
保税 (`fsb_baoshui` / `泛思博特保税网球场巡检`), 南油 (`fsb_nanyou` /
`泛思博特南油网球场巡检`), 新桥 (`fsb_xinqiao` /
`泛思博特新桥网球场巡检`), 壹方城 (`fsb_yifangcheng` /
`泛思博特壹方城网球场巡检`), 麒麟 (`fsb_qilin` /
`泛思博特麒麟网球场巡检`), and 茅洲河 (`fsb_maozhouhe` /
`泛思博特茅洲河网球场巡检`). Unauthenticated `/api/bootstrap` returns
twenty-five venues and no email address. Creating a subscription still
requires email verification; no verification email or live WeChat probe was
sent.

Only standard tennis / 风雨场 courts are published. 小场, 匹克, 练习, 非标,
and 发球机 courts are dropped before Web observation or WeChat. 沙河 is a
distinct store from 上越沙河 (`sysh`).

CI `verify` on the exact `0.6.0` SHA is run `33289008505`. Ship
`33289113704` applied D1 migration `0014_add_fsb_ten_more_venues.sql`,
uploaded the Worker, and replaced Airflow application containers. Post-ship
Web health `33289693249` reported twenty-five venues and the exact
`0.6.0` SHA. After the later 1-minute Airflow apply, health
`33290178426` passed on `11783bf6c510eb9ccde982ac4bb68d06a7cca3de` with no
paused DAGs, no missing Variables, no import errors, and no recent-run
failures. All ten new DAGs produced three consecutive natural successes
around `03:18`–`03:24` UTC and stayed unpaused. Historical WeChat fallback
outbox records remain (`200`) and were not replayed.

Rollback of the named `0.6.0` Web identity remains the previous named
release `0.5.2` (`c962f89b697e9415c85e2ba9164181d667cc126a`). Airflow
rollback of the subsequent 1-minute apply is that same `0.6.0` SHA, not
`0.5.2`. D1 already contains the ten venue rows; rolling Web back hides
them from the catalog but does not delete the rows.

## Fansibote Chain Five Stores On 2026-08-29

Release `0.5.2` is
`c962f89b697e9415c85e2ba9164181d667cc126a` (PRs #102, #103, #104). Web and
Airflow both run that SHA. Sender was out of scope and was not redeployed.

The five PosPal chain tennis venues are on the public catalog: 深云
(`fsb_shenyun` / `泛思博特深云网球场巡检`), 蛇口 (`fsb_shekou` /
`泛思博特蛇口网球场巡检`), 新安 (`fsb_xinan` / `泛思博特新安网球场巡检`),
正中 (`fsb_zhengzhong` / `泛思博特正中网球场巡检`), and 安托山
(`fsb_atuoshan` / `泛思博特安托山网球场巡检`). Unauthenticated
`/api/bootstrap` returns fifteen venues and no email address. The production
UI lists all five as healthy. Creating a subscription still requires email
verification; no verification email or live WeChat probe was sent.

Only standard tennis / 风雨场 courts are published. 小场, 匹克, and 练习
courts are dropped before Web observation or WeChat. A successful PosPal V2
response with zero bookable rooms is a healthy empty result.

The first `0.5.0` ship (`7367a0c64baf504e424f29d2768a19c6bda5f19f`, run
`33256597187`) applied Web and then rolled Airflow back because the new
30-second DAGs had one or two successes, which the health gate treated as
missing history. `0.5.1` (`91fb2c28d9a5988eed8c31e72ecaf0ce3fee9fa0`, run
`33257916867`) treated incomplete all-success history as warming-up, but
apply restored the leftover paused metadata from the first rollback and
failed health on paused active DAGs. `0.5.2` unpauses newly introduced
target DAGs even when leftover metadata marked them paused.

The five 30-second DAGs produced three consecutive natural successes around
`15:07`–`15:09` UTC and stayed unpaused. Web `lastInspectionAt` refreshed
from `15:02:59Z`–`15:03:01Z` to `15:13:30Z`–`15:13:58Z` during the
observation window.

CI `verify` on the exact SHA is run `33258842519`. Ship `33258953775`
uploaded the Worker and replaced Airflow application containers. D1
migration `0012_add_fsb_chain_venues.sql` was already applied by the
`0.5.0` Web apply. Post-observe Web health `33259442440` reported fifteen
venues and the exact SHA. Post-observe Airflow health `33259442569` passed
with no paused DAGs, no missing Variables, and no recent-run failures.
Historical WeChat fallback outbox records remain (`200`) and were not
replayed.

Rollback remains the previous named release `0.4.0`
(`9f43b5c7c885df92da49e4b67ca3a6349978fc8a`) without replacing the Airflow 3
database. Re-apply that commit through the protected Web and Airflow
workflows. D1 already contains the five venue rows; rolling Web back hides
them from the catalog but does not delete the rows.

## PICKLE POP Bao'an On 2026-08-29

Release `0.4.0` is
`9f43b5c7c885df92da49e4b67ca3a6349978fc8a` (PR #96). Web and Airflow both
run that SHA. Sender was out of scope and was not redeployed.

The PosPal venue PICKLE POP宝安 (`ppba` / `PICKLEPOP宝安网球场巡检`) is on
the public catalog. Unauthenticated `/api/bootstrap` returns ten venues and
no email address. The production UI lists the venue as healthy. Creating a
subscription still requires email verification; no verification email or live
WeChat probe was sent.

The 30-second DAG produced three consecutive natural successes
(`13:19:54`, `13:20:24`, `13:20:54` UTC) and published healthy observations.
Web `lastInspectionAt` for `ppba` refreshed from `13:15:30Z` to `13:21:14Z`
during the observation window. Pickleball rooms stay out of tennis
observations. The DAG ID has no space because Airflow 3 `validate_key`
rejects whitespace.

CI `verify` on the exact SHA is run `33253861848`. Ship
`33254286167` applied D1 migration `0011_add_ppba_venue.sql`, uploaded the
Worker, and replaced Airflow application containers. Post-observe Web health
`33254814885` reported ten venues and the exact SHA. Post-observe Airflow
health `33254789784` passed with no paused DAGs, no missing Variables, and
no recent-run failures. Historical WeChat fallback outbox records remain
(`200`) and were not replayed.

Rollback remains the previous named release `0.3.0`
(`5bc7427b2fbfd2d0d65f9d96dc91929ceb597964`) without replacing the Airflow 3
database. Re-apply that commit through the protected Web and Airflow
workflows. D1 already contains the `ppba` venue row; rolling Web back hides
it from the catalog but does not delete the row.

## Dashah International Tennis Center On 2026-08-29

Release `0.3.0` is
`5bc7427b2fbfd2d0d65f9d96dc91929ceb597964` (PR #94). Web and Airflow both
run that SHA. Sender was out of scope and was not redeployed.

The paid Dashah International Tennis Center venue (`dsh` /
`大沙河国际网球中心`) is on the public catalog. Unauthenticated
`/api/bootstrap` returns nine venues and no email address. The production UI
lists the venue and shows a healthy inspection. Creating a subscription still
requires email verification; no verification email or live WeChat probe was
sent.

`PI_DEVICE_SSH` was seeded through the protected `pi_device_ssh_sync`
operation before Airflow apply. The 3-minute DAG
`大沙河国际网球中心巡检` produced three consecutive natural successes
(`12:32`, `12:35`, `12:38` UTC) and published healthy observations. Web
`lastInspectionAt` for `dsh` continued to refresh during the observation
window.

CI `verify` on the exact SHA is run `33252143707`. The first ship attempt
(`33252303428`) applied D1 migration `0010_add_dsh_venue.sql` and uploaded
the Worker, then failed health because the custom domain still served the
previous Worker for a few seconds. After propagation, Web health reported
nine venues and the exact SHA. The successful ship is
`33252429294`. Post-observe Airflow health passed with no paused DAGs, no
missing Variables, and no recent-run failures. Historical WeChat fallback
outbox records remain and were not replayed.

Rollback remains the previous named release `0.2.4`
(`ef12280fbff7b8e367a5fb81573bb8117232fee0`) without replacing the Airflow 3
database. Re-apply that commit through the protected Web and Airflow
workflows.

## Zacks Phone Reboot Every Two Days On 2026-08-23

The `zacks_phone_daily_reboot` schedule changed from daily to every other day
(cron `0 5 * * *` → `0 5 */2 * *`, Asia/Shanghai). The 05:00 slot and the
stable DAG ID are preserved so run history and pause state are untouched; only
the DAG description, the `config/active-components.yaml` schedule contract, and
README/CHANGELOG labels changed.

CI run `32632573625` (`verify`) passed on the exact merged commit
`ee7fdda2411bca2bf6966760f7c603362f71e02a` (PR #71). Production deployed the
same SHA: preflight run `32632839306` and apply run `32632870257` succeeded,
and post-deploy health runs `32633085283` and `32633143219` passed with an
exact commit match. The previous runtime was `616e6dd`.

Observation pending: the scheduler must skip the old daily slot (no reboot run
on 2026-08-24 05:00) and produce the next natural reboot run on
2026-08-25 05:00 Asia/Shanghai, then continue on odd days of the month.
Rollback remains the previous exact commit `616e6dd` without replacing the
Airflow 3 database.

## WeChat Booking Mini-Program Footers On 2026-08-18

Observation and health evidence below were collected on
`cbc87d2b08cd1ca1879dee24380e3cf09d4c4aa8` for both Airflow and the
Android-host WeChat sender. A later documentation-only commit may share this
runtime while keeping Git HEAD aligned with production.

WeChat availability alerts now append the venue booking mini-program as the
last line of the same send, at most once per chat and mini-program every two
hours. Shenzhen Bay and Greater Bay Area share 未来荟. Dashah River uses 南山文体通
and Sports Center uses i深体. Slot dedupe caches remain link-free. A failed send
releases the cooldown claim so a later venue can still attach the card.

CI run `32152721908` passed. Sender apply left systemd enabled, active, and
ready. Airflow apply restored DAG pause state, drained active tasks, preserved
the WeChat outbox, and left six application containers healthy on image
`wechat-on-airflow:3.3.0-cbc87d2`. No real WeChat probe was sent for this
change.

The outbox still held 200 historical records. The newest failure remained
`device_busy` at `2026-08-18T12:32:12Z`. After this deploy, no new WeChat
fallback records accumulated through the observation window. Those 200 records
remain incident evidence and were not replayed.

Post-deploy `make production-health` passed with ten unpaused DAGs, zero import
errors, matching local HEAD, and three consecutive successful proxy runs at
15:20, 15:25, and 15:30 UTC. Venue DAGs including `大沙河免费场巡检` and
`深圳市体育中心网球场巡检` also completed three natural post-deploy successes.
Whether a live evening slot actually carried a mini-program footer depends on
new detections after apply; this window did not include an approved probe.

Rollback remains the previous exact commits without replacing the Airflow 3
database: Airflow and sender
`64d8e0e9c2811a189514ed6f15665c3a112c0c73` with image
`wechat-on-airflow:3.3.0-64d8e0e`.

## GBA Close Time And WeChat Lock Queue On 2026-08-18

Observation and health evidence below were collected on
`f57e5b1aa94cb2a29414c3b9813e106257f288bf` for both Airflow and the
Android-host WeChat sender. A later documentation-only commit may share this
runtime while keeping Git HEAD aligned with production.

Greater Bay Area booking queries now end at 21:00, and WeChat alerts are
limited to weekday 18:00-21:00 and weekend 12:00-21:00 so a 21:00 venue close
cannot appear as a 21:00-22:00 empty court. Shenzhen Bay windows are unchanged.
The sender waits up to 150 seconds for the single-device lock. Airflow floors
the send timeout at 210 seconds, retries `device_busy` with a 15-second pause,
and gives Shenzhen Bay, Greater Bay Area, and Dashah free-court DAG runs a
10-minute timeout so overlapping inspections queue instead of writing the
fallback outbox.

CI run `32145838468` passed. Sender apply left systemd enabled, active, and
ready. Airflow apply restored DAG pause state, drained active tasks, preserved
the WeChat outbox, and left six application containers healthy on image
`wechat-on-airflow:3.3.0-f57e5b1`.

A protected probe with `--target-membership dsh_free:1` sent one acceptance
message in 51.6 seconds via `recent_visual` at `2026-08-18T14:14:35Z` and did
not target other chats. The longer elapsed time followed the sender restart
and does not indicate a failed send.

The outbox still held 200 historical records. The newest failure remained
`device_busy` at `2026-08-18T12:32:12Z`. After this deploy, no new WeChat
fallback records accumulated through the observation window, including the
probe. Those 200 records remain incident evidence and were not replayed.

Post-deploy `make production-health` passed with ten unpaused DAGs, zero import
errors, matching local HEAD, and three consecutive successful proxy runs at
14:15, 14:20, and 14:25 UTC. Venue DAGs including `大沙河免费场巡检`,
`大湾区网球场巡检`, and `深圳湾网球场巡检` also completed three natural
post-deploy successes. The 21:00-22:00 Greater Bay Area exclusion is covered
by unit tests; this deploy landed after the weekday WeChat window, so that
filter was not observed on a live evening slot.

Rollback remains the previous exact commits without replacing the Airflow 3
database: Airflow and sender
`7532025478085fd2026176cdfa7a9edfbf7ef48b` with image
`wechat-on-airflow:3.3.0-7532025`. Free disk stayed just under the 8 GB
fresh-start floor; incremental application deploys still succeeded.

## WeChat Reliability And Venue Routing On 2026-08-18

Observation and health evidence below were collected on
`a8380efdd5d82da47e2f56fb30ccac8f1d759335` for both Airflow and the
Android-host WeChat sender. The runtime change landed in
`548600daf7d11295bc92f3dec28e9bfe101b3d63`; the two follow-up commits only
allowed the protected probe to select `dsh_free:N` and satisfied `ruff format`.
A later documentation-only commit may share this runtime while keeping Git HEAD
aligned with production.

The sender now reuses a warm Appium session and honors an idempotency key so a
late HTTP timeout cannot double-send. Greater Bay Area WeChat uses the same
Zacks chatrooms as Shenzhen Bay, with weekday 18:00-22:00 and weekend
12:00-22:00 windows. Dashah River free-court WeChat is limited to
`Zacks_大沙河限定免费`. The first successful inspection created the empty
`大沙河免费场` dedupe Variable; its value was not copied to a workstation.

A protected probe with `--target-membership dsh_free:1` sent one acceptance
message in 27.9 seconds via `recent_visual` and did not target other chats.
CI run `32140297139` passed. Airflow apply restored DAG pause state, drained
active tasks, preserved the WeChat outbox, and left six application containers
healthy. Sender systemd remained enabled, active, and ready.

The pre-change outbox still held 200 historical records. The newest failure was
`device_busy` at `2026-08-18T12:32:12Z`, caused by concurrent venue DAGs waiting
on the single device lock. After this deploy, no new WeChat fallback records
accumulated through the observation window. Those 200 records remain incident
evidence and were not replayed.

Post-deploy `make production-health` passed with ten unpaused DAGs, zero import
errors, matching local HEAD, and three consecutive successful proxy runs at
13:15, 13:20, and 13:25 UTC. Venue DAGs including `大沙河免费场巡检` and
`大湾区网球场巡检` also completed three natural post-deploy successes. One
earlier health attempt failed only because the Cloudflare Tunnel public UI probe
returned no status while origin and public health stayed HTTP 200; a later check
and a workstation request both saw UI HTTP 200.

Rollback remains the previous exact commits without replacing the Airflow 3
database: Airflow `892872b5c6a18fd3556b568f67e892115061f5c4` with image
`wechat-on-airflow:3.3.0-892872b`, and the sender `abdcaa7083d6ba742fb85c73eee483b30dbb5a19`.
The identity-align deploy can also roll back to
`548600daf7d11295bc92f3dec28e9bfe101b3d63` / `wechat-on-airflow:3.3.0-548600d`.

## Dashah Free-Court And Email Quota Release On 2026-08-16

Commit `ea97edf8589b4fae8d2e19385c943d4665fa07eb` added the NSWTT-backed
`大沙河免费场巡检` DAG and the `dsh_free` Web venue. The watcher requires both an
open calendar date and a non-empty free-court place list before publishing
zero-price slots. A date with no free-court place list is a healthy empty
observation and cannot create subscriber email.

The bounded `NSWTT_API_CONFIG` value is stored in the protected GitHub
`production` Environment and synchronized to its Airflow Variable without
copying the value to a workstation or repository. D1 migration
`0003_add_dashahe_free_venue.sql` was applied, and Cloudflare Worker version
`03624477-a6ca-4065-9efb-781cf7abb27c` was published. The public health endpoint
returned healthy and bootstrap exposed all seven configured venues.

The verification-code incident was traced to one venue email per raw slot.
That behavior exhausted the Tencent SES per-recipient and daily quotas shared
with verification mail. The Worker now groups a recipient's pending venue rows
into one compact email, merges adjacent intervals, counts deliveries by
provider message ID, and caps venue-notification sends at 1,000 per day so
verification capacity remains available.

After the Shanghai midnight quota boundary, D1 recorded one frequency-limit
failure at `00:00:22`, followed by 33 successful provider deliveries with no
pending or retry rows. This confirms the shared delivery channel recovered
without an outbox backlog; verification delivery itself was not invoked during
acceptance.

Airflow deployed the exact implementation commit with all application
containers healthy and the notification outbox preserved. The new DAG was
activated through the protected scheduling operation and completed three
natural 30-second runs successfully; the following full production health
check passed with ten unpaused DAGs and zero import errors. Acceptance used
read-only provider and application checks and did not send a real email or
WeChat message.

The activation exposed a false-negative in the scheduling operation: it
compared eight unique running Compose service names with nine container
instances because the scheduler has two replicas. The operation now validates
the required service-name set from `runtime-target.yaml` and treats the
verified final DAG state as authoritative for idempotent completion.

## Platform-Native Production Secrets

On 2026-08-12 production operations moved from workstation-held credentials to
the protected GitHub `production` Environment. GitHub Actions now authenticates
to the Airflow and Android hosts with separate scoped Ed25519 deployment
identities and pinned host keys. Runtime values remain at their owning service:
Airflow Variables, Cloudflare Worker Secrets, root-owned Compose Secret source
files, and systemd credentials. GitHub stores deployment access, not copies of
application runtime secrets.

Airflow infrastructure credentials were moved to
`/etc/wechat-on-airflow/secrets`; the application services were rebuilt from
commit `67693cfd5294a9b0b3286faefea6bcad7cdc785a` with all six application
containers healthy and the original DAG pause state restored after four active
tasks drained. The sender credentials were moved to
`/etc/wechat-sender/credentials`; commit
`cb6e36b0544a3417b7c2d10febd4c669e95b658e` completed the sender deployment
with its service enabled, active, and ready. No real notification was sent.

After the cutover, the one-time parsers and migration branches were removed.
Normal production deployment now fails closed unless the declared Secret and
credential files already exist with their contracted ownership and modes. The
repository, developer workstation, active Airflow host checkout, and sender
host no longer contain runtime environment files.

The final legacy-removal commit `1308ad618a4dc56cd492e98ead140eef48e4bf52`
was deployed to both production hosts. Subsequent protected diagnostics run
from the pushed `main` commit through GitHub Actions and do not copy production
credentials back to an operator workstation. Local development uses generated,
ignored files under `.local/secrets`; these values are not production data.

## Android USB Incident On 2026-08-12

The protected Airflow phone probe confirmed that `APPIUM_SERVER_LIST` is valid,
SSH authentication succeeds, and `adb devices` executes successfully, but no
online device is returned. The independent sender-host probe confirmed that
`wechat-sender.service` and `appium-6002.service` are active while both the ADB
device list and the kernel USB ADB-interface count are zero. Sender `/readyz`
therefore correctly reports `device_not_ready`.

This isolates the current failure to the physical phone/USB-debugging boundary,
not Airflow configuration, GitHub deployment authentication, Appium process
management, or the no-`.env` migration. The bounded software recovery was not
run because restarting ADB cannot restore an absent USB interface. No phone
reboot, real WeChat send, fallback replay, or metadata deletion was performed.
Venue observations and subscriber email remain independent of this sender
fault by contract.

## Android Host GitHub Connectivity On 2026-08-13

Two protected sender deployment preflights failed before changing production:
the Android host first reported a terminated Git TLS connection and then timed
out connecting to `github.com:443`. The sender service remained enabled, active,
and ready on its previous exact commit; no notification was sent by either
preflight.

Sender deployment no longer requires the Android host to reach GitHub. The
protected workflow verifies `origin/main`, creates a complete Git bundle, and
stages it over the existing pinned SSH connection. The remote deployment then
imports and checks out the requested full commit from that bundle. Standalone
installation retains bounded direct-fetch retries when a commit is not already
available locally.

## Web-Only Subscriber Email

On 2026-07-30 subscriber email ownership moved exclusively to the Cloudflare
Web application. The five Airflow fixed-recipient lists and the Airflow Tencent
SES sender configuration were retired. Venue watchers publish raw observations
before attempting WeChat delivery, so Android device failures cannot delay Web
subscription matching or email.

The retired `EMAIL_SEND_FALLBACK_OUTBOX` remains in Airflow as historical
incident evidence and is excluded from active health evaluation. It is not
replayed or deleted. Production configuration cleanup preserves an encrypted
Variable-row backup outside Git before removing unused fixed-recipient and
sender Variables.

## Cloudflare Tunnel Ingress

On 2026-07-19 a locally managed Cloudflare Tunnel was installed as an enabled
systemd service on the Airflow host. DNS for `airflow.claude89757.cc` routes to
the tunnel, which forwards to the Airflow API server on loopback. The public
health endpoint and UI route were reachable through Cloudflare before the
application ingress hardening deployment.

The first base URL update omitted the existing `/airflow` prefix. Four venue
DAGs then failed during task startup because the private Execution API route no
longer matched the API server mount path. The change was rolled back without
changing metadata, clearing task history, or replaying notification outboxes;
scheduling resumed under the previous configuration. The repository now
serves Airflow from the hostname root, enforces the matching private
`/execution/` route, enables proxy-header support, binds the origin port to
loopback, and checks the tunnel alongside the private Execution API and DAG run
history.

## Airflow 3 Production Cutover

The fresh Airflow 3 cutover completed on 2026-07-17. Production runs Airflow
3.3.0. The initial stabilized cutover used application commit
`85c50ae8ccd6845ec9f6c7c628c2b4711259fa7b`; its CI, local verification,
image-bundled DagBag check, and deployment preflight passed. Current deployment
identity is now verified by protected GitHub health workflows against their
explicit full release SHA rather than a workstation checkout or mutable state
in the component manifest.

Historical Airflow 2 metadata was not migrated. The complete Airflow 2
database, logs, environment file, commit, image, and encrypted backup remain
intact for rollback. Airflow 3 uses three independent named volumes for
PostgreSQL, Redis, and logs.

The final protected configuration export contained 33 Variables, zero
Connections, and the default Pool. All 33 Variable values were imported and
verified exactly without printing them. Venue deduplication and proxy
continuity caches were preserved. Email and WeChat fallback outboxes started
empty and were not replayed.

The first activation exposed two Airflow 3 application compatibility defects:
host DAG files were unreadable by the container UID, and the private Execution
API URL omitted the public `/airflow` path prefix. The deployed image now owns
readable DAG sources, and the Execution API route probe returns the expected
unauthenticated response. A subsequent task-level defect used the Airflow 2
`Variable.get(default_var=...)` keyword through the Airflow 3 Task SDK; all
task-runtime calls now use `default=`, with a regression check.

Post-deploy natural scheduling produced three consecutive successful runs for
all five venue DAGs. Both proxy DAGs completed successfully, and a failed public
proxy source can no longer abort an entire refresh. Email delivery remained
independent while the external WeChat sender was unavailable: the email
fallback outbox remained empty, and five new WeChat failures were isolated in
the WeChat incident outbox without replay.

Eight retained DAGs are unpaused. The sender and Android-host recovery is
recorded below. The failed daily metadata cleanup DAG has been retired and
replaced by a default-read-only deployment-manager command.

## Final 0.1.0 Verification

On 2026-07-19 the final Agent-Native release candidate passed local
`make verify`, GitHub CI, deployment and rollback preflight, exact-commit
production deployment, and post-deploy health checks. Airflow 3.3.0 loaded
exactly eight active DAGs with zero import errors, all nine Compose containers
were healthy, and no required configuration name was missing.

Both five-minute proxy DAGs completed three consecutive post-deploy runs at
17:20, 17:25, and 17:30 UTC. All five venue DAGs continued to complete across
their faster schedules, and the phone maintenance DAG's latest natural run was
successful. The sender host was deployed to the same pushed release candidate;
its systemd service was enabled and active, with a valid main process and
successful `/healthz` and `/readyz` checks.

The email and WeChat fallback outboxes remained unchanged at 4 and 166. Their
latest failure timestamps predated the sender recovery, so they are retained as
historical incident records rather than current health failures. No record was
replayed or deleted, and no real message was sent during verification. The
metadata cleanup command also completed its default dry run against the exact
production commit; it did not delete records.

## Post-cutover Observation

The read-only check on 2026-07-18 found all five venue DAGs and both proxy DAGs
successful for their three most recent completed runs. All nine Airflow
services were healthy, the Execution API probe passed, all DAG sources were
readable, required configuration names were present, and import errors remained
at zero.

Tencent SES accepted later messages after three isolated
`FailedOperation.FrequencyLimit` responses, confirming that email delivery was
operational and independent from the WeChat outage. The three email records
remain diagnostic evidence and are not replayed. The WeChat incident outbox
contained 89 deduplicated send failures across all five venues because the
configured external sender returned an empty HTTP response. No outbox record
was automatically replayed or deleted.

The sender runs on the Android device host, not the Airflow host. Its current
Ed25519 fingerprint has been verified during an authenticated session and is
pinned in the protected Airflow Variable; the fingerprint itself is
intentionally not committed here.

On 2026-07-18 the new default-read-only deployment command applied the latest
pushed commit to all six Airflow application containers. It retained the
existing PostgreSQL, Redis, and log volumes, and the post-deploy check confirmed
that the production commit matched local Git HEAD.

## WeChat Sender Recovery

On 2026-07-19 the Android host was authenticated using the device credentials
stored in `APPIUM_SERVER_LIST`, without logging their values. Its current
Ed25519 fingerprint was verified during the authenticated session and stored
as `login_info.host_key_sha256`. The phone maintenance DAG was then unpaused;
its next natural run completed successfully without a manual trigger.

The sender outage was caused by a manually started process with no process
manager. Appium on the device host remained healthy, but no process listened on
port 7001. Production now runs the sender as an enabled systemd service under a
dedicated unprivileged account, from the exact pushed repository commit, with
one Uvicorn worker and automatic restart. Local and public `/healthz` and
`/readyz` returned HTTP 200. A controlled process termination demonstrated
automatic restart and restored readiness without sending a real message.

The first systemd start exposed a relocated-virtual-environment entrypoint
defect, and a later Git fetch encountered a transient TLS termination. The
service now starts Uvicorn through the virtual environment's Python module
entrypoint, and the installer retries Git fetches with bounded backoff. Both
incidents have regression checks. The Airflow and sender hosts were deployed to
the same pushed commit, all nine Airflow services were healthy, and five venue
plus two proxy DAGs retained their required successful run history. The email
and WeChat fallback outboxes remained at 4 and 166 during the immediate
post-repair observation window; no record was replayed or deleted.

The daily metadata cleanup DAG's second natural Airflow 3 run failed before
cleanup because the Task SDK task subprocess did not receive a usable metadata
database URL, even though the worker service itself was correctly configured.
No rows were deleted. The DAG has been removed from the production bundle and
replaced by `scripts/airflow_db_cleanup.py`, which executes the supported CLI
from the deployment boundary. It defaults to a dry run and is not scheduled.
Applying a cutoff still requires explicit approval because database record
deletion is irreversible.

## Approved Cutover Scope

On 2026-07-17 the migration scope changed to a fresh Airflow 3 metadata
database. Historical Airflow 2 metadata is not required. The old database and
its encrypted backup remain intact for rollback, while contract-declared
configuration, venue deduplication caches, and proxy caches move to the new
system. Fallback outboxes remain incident evidence and are reset without
replay.

The isolated empty-database and configuration-import procedure passed on
2026-07-17. See
[`fresh-start-rehearsal-2026-07-17.md`](fresh-start-rehearsal-2026-07-17.md).

## Pre-cutover Read-only Refresh

The health check at 2026-07-17 11:00 Asia/Shanghai still found Airflow 2.10.5
at commit `2e74766256c97ff0af00f70b0af6ebb2777abe3e`. The metadata database had
grown to 42,475,056,275 bytes, with 16,659,836,928 bytes free on reliable root
storage. All venue, proxy, and cleanup DAGs had three recent successful runs;
the phone reboot DAG showed `success`, `failed`, `failed`.

The remaining gates were unchanged: two stale Appium import errors, missing
`VENUE_EMAIL_FROM_ADDRESS` and `VENUE_EMAIL_REPLY_TO`, an invalid or absent
pinned Zacks host-key fingerprint, an unreachable managed WeChat sender, and
fallback outbox counts of 36 email and 200 WeChat incident records. These
records must not be replayed automatically.

## Pre-cutover Runtime

| Component | Observed state |
| --- | --- |
| Git commit | `2e74766256c97ff0af00f70b0af6ebb2777abe3e` |
| Airflow | 2.10.5 |
| Python | 3.12.10 |
| Executor | CeleryExecutor |
| Airflow image | `bitnami/airflow:2.10.5` |
| PostgreSQL | 17 |
| Redis | 8.6.0 image line |
| Host memory | 7.5 GiB, no swap |
| Root filesystem | 79 GiB, 15.8 GiB free |
| Secondary filesystem | 99 GiB, unusable due to ext4 I/O errors |

The production repository had one unrelated untracked `nohup.out` file. It must
not be committed or removed as part of the migration without establishing
ownership.

The filesystem mounted at `/root/data/disk` repeatedly returned ext4 inode and
directory read errors. It must not be used for backups or migration rehearsal
until the host filesystem is repaired outside this project.

## Migration Backup

An encrypted, consistent custom-format PostgreSQL backup was streamed directly
from the production container to the operator workstation:

- completed: `2026-07-16T15:48:54Z`
- encrypted size: approximately 2.0 GiB
- encryption: AES-256-CBC with PBKDF2; key stored outside the repository
- SHA-256 checksum: verified
- `pg_restore --list`: recognized a PostgreSQL custom archive with 368 TOC
  entries and gzip compression

The exported Airflow Variables, Connections, and Pools configuration is also
encrypted and stored outside the repository. Backup filenames and keys are not
committed. The full historical migration rehearsal completed on 2026-07-17 and
remains evidence, but it is no longer the production deployment path. See
[`migration-rehearsal-2026-07-17.md`](migration-rehearsal-2026-07-17.md).

## Metadata Database

| Metric | Observed value |
| --- | ---: |
| Database size | 42,469,788,819 bytes |
| DAG runs | 2,906,144 |
| Task instances | 11,928,578 |
| XCom rows | 3,737,203 |

Core relation sizes from the read-only health check:

| Relation | Total size |
| --- | ---: |
| `task_instance` | 18,384,207,872 bytes |
| `log` | 14,536,491,008 bytes |
| `dag_run` | 2,464,915,456 bytes |
| `xcom` | 1,636,204,544 bytes |

Only 16,957,681,664 bytes were free on the root filesystem. This prevents the
historical in-place migration, but the approved fresh-start path does not
rewrite or copy the 42 GB database. The old database remains in place and the
new runtime must retain the minimum free-space floor in
`config/runtime-target.yaml`.

The high row count is caused by sub-minute venue schedules combined with a
180-day retention window. It materially increases backup and major-version
migration time. Production retention changes require a backup and explicit
approval because deletion is irreversible.

## Parsed DAGs

Nine DAGs were present in the current DagBag and all were unpaused:

- `airflow_db_cleanup`
- `HTTPS可用代理巡检`
- `HTTPS可用代理巡检_ydmap`
- `TOPS科技园网球场巡检`
- `zacks_phone_daily_reboot`
- `上越沙河网球场巡检`
- `深圳市体育中心网球场巡检`
- `深圳湾网球场巡检`
- `深圳金地网球场巡检`

The five venue DAGs and two proxy DAGs had successful recent runs. The phone
reboot DAG had two recent failures in `resolve_zacks_device_config`; its
Variable shape was present and structurally valid, so the remaining failure is
an external device or SSH/ADB runtime concern.

## Import Errors

The production CLI reported persistent Appium import errors:

- `dags/tennis_dags/wx_msg_watcher_for_zacks.py`
- `dags/utils/appium/wx_appium.py`

The Appium message watcher remains as stale metadata in `DagModel` but is not in
the parsed DagBag. Current venue notification code uses the remote WeChat sender
API instead. This is evidence for removal after the final reference audit.

A full unsafe DagBag scan also imported utility files directly and exposed
missing optional dependencies in non-DAG modules. The Airflow 3 layout must keep
reusable code outside the DAG scan root and install only dependencies needed by
active components.

## Configuration Inventory

Production had no Airflow Connections and only the default Pool. Variable names
are recorded in `config/active-components.yaml`; values are intentionally not
documented.

## External Services

- Public venue booking APIs
- Public proxy source repositories
- GitHub Contents API for proxy list publication
- Tencent SES
- Remote WeChat sender HTTP API
- SSH/ADB Android device host

No additional repository-managed systemd services or Docker services were
observed on this host outside the Airflow Compose stack.

The WeChat sender port had no listener and no persistent service manager.
Read-only fallback aggregation showed 200 WeChat records, all classified as
connection unavailable. Email had 36 records, all classified as provider
frequency or quota limits. Payloads, recipients, endpoints, and credentials
were not inspected or recorded. These outboxes are incident records and must
not be replayed blindly.

## Fresh-start Gates

Before production cutover:

1. Preserve the Airflow 2 database, runtime environment, commit, and images.
2. Produce a final protected configuration export.
3. Prepare the contract-filtered import with no missing required names.
4. Prove all active DAGs import with zero errors.
5. Run no-delivery contract and smoke tests.
6. Verify the new paths and free-space floor.
7. Prepare and verify path-switch rollback commands.
8. Start DAGs paused, import and verify configuration, then activate them.
