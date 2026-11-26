# Pi YDMap scraper deployment

The private Pi scraper serves Dashah (`dsh`, wxsports.ydmap.cn), three Futian
venues on ftty.ydmap.cn (`xmty`, `hmg`, `lhty`), and Bao'an Tennis Center on
bawtt.ydmap.cn (`baoti_outdoor`, `baoti_indoor`, `baoti_covered`). Each venue
opens its own supported booking URL in its own private profile; the single
scrape lock and the one-slot Airflow `ydmap_browser` pool serialize them. The
Futian venues release the next day at 09:00 and show today and tomorrow, so their
DAGs and the installer's inspections skip them before 09:00 Asia/Shanghai and
read two dates afterwards. They share one host, which showed its slider
challenge on the third back-to-back load during the 2026-11-26 preflight. Their
DAGs therefore run every six minutes at minute offsets 0/2/4 (one ftty page load
every two minutes, the cadence Dashah sustains), and one installer inspection
reads only one of them, rotating by hour. 黄木岗's training walls are scraped
but dropped by its Airflow watcher.

Bao'an Tennis Center (`baoti`) was withdrawn on 2026-11-01 and restored on
2026-11-26. It runs in a physically and scheduling-isolated path: Airflow uses
the dedicated `ydmap_baoti_browser` pool (`slots=1`) on `1-59/5 * * * *` (one
product every five minutes, rotating outdoor, indoor, covered every fifteen
minutes — skipping kids' short court `111318`), and the Pi scraper uses its
dedicated `BAOTI_SCRAPE_LOCK` and `BAOTI_DEBUG_PORT` (`9225`). The scraper runs
direct-first on the Raspberry Pi and maintains a 30-minute circuit breaker: only
if direct access encounters `captcha` or `rate_limited` does it fall back to
validating candidate proxies from `isz_https_proxies.txt` via explicit HTTP/1.1
`CONNECT` + strict TLS before launching Chromium with
`--proxy-server=http://<ip>:<port>`. Bao'an releases the next day at 08:00 and
reads two dates afterwards.

The protected Pi deployment path serves all seven scraper keys (`dsh`, `xmty`,
`hmg`, `lhty`, `baoti_outdoor`, `baoti_indoor`, `baoti_covered`). Changing
pi_host/dsh_ydmap/ is still a runtime change: the release planner selects
pi_ydmap, and production-release.yml deploys it before Web/Airflow. The Appium
MCP, Sender, phone agent and tunnels remain separate services.

## Protected entry point

Run production-pi-ydmap.yml on main with a full target_commit, a unique request_id
and one operation: preflight, apply, health or inspect. The workflow requires
main ancestry and successful CI / verify for that exact commit. Existing
PI_DEVICE_SSH_* credentials come only from the protected production Environment.
The runner checks the configured SHA256 host-key pin, then uses SFTP and a
bounded remote installer. The scraper has no public endpoint.

The owner-only Issue #39 router supports:

    /ops pi-ydmap-preflight <full-sha>
    /ops pi-ydmap-apply <full-sha>
    /ops pi-ydmap-health <full-sha>
    /ops pi-ydmap-inspect <full-sha>

These commands dispatch protected GitHub workflows. Do not use workstation SSH,
copy credentials into artifacts, or run a candidate outside the documented guard.

The one-shot verification interaction remains removed; legacy requests for
`verification` fail before host access. An upstream access challenge remains a
failed inspection; the service performs no automatic verification interaction.

## Candidate and activation

The release pipeline uses `ready` for preflight and `allow_interruption` for
apply. It checks that the live scraper answers, then replaces it without
pausing Dashah or running candidate browser cycles. A manual workflow can still
set `drain_preflight=true` for a deep candidate check. Separate
ports and profiles do not isolate Pi CPU, desktop focus or upstream traffic.
The scoped Airflow guard waits for YDMap work to finish, saves and pauses only
the Dashah, Futian and Bao'an YDMap DAGs, then restores and verifies their original pause flags
after the operation, including after a reported candidate failure. A venue DAG
that Airflow does not have yet (during an initial Pi release) is simply absent from the
proof; Dashah must be present. Unrelated DAGs are outside this guard.

Guarded preflight and apply require the same target-bound, expiring drain proof.
Both active tasks and active DAG runs must be zero. The lease is checked again
after waiting for the live scraper to become idle and before activation.
If the operation channel is lost and candidate completion is unknown, the guard
retains its fence until the lease permits safe restoration.

Preflight stages the exact source and offline regressions below
/opt/pi-ydmap-scraper/releases/. It verifies the source SHA256, Python syntax and
a nonzero count of passing mock tests as the existing unprivileged service user.
The candidate uses HTTP port 18788 and debug port 19224. The live service retains
HTTP port 8788 and debug port 9224.

The candidate must report protocol version 2, the exact deployment commit and
source hash, and all seven supported keys (`baoti_covered`, `baoti_indoor`,
`baoti_outdoor`, `dsh`, `hmg`, `lhty`, `xmty`). During an upgrade the live
service may still report an earlier subset (`dsh` or `dsh/hmg/lhty/xmty`);
readiness accepts those sets, while candidate and installed health require all
seven. Each inspection independently verifies the released Dashah horizon (four
dates before noon in Asia/Shanghai, five from noon onward), from 09:00 two dates
for one Futian venue (rotating by hour), and from 08:00 two dates for one
Bao'an product (rotating by hour) against its own booking host and salesId.
Selected date, query date, source arrays, product identity, court inventory
and provider bookability must agree. Empty availability is valid only when the
complete dated court inventory is verified.

A manual guarded preflight can still run three read-only candidate cycles on
the same service profile, with starts at least 120 seconds apart. The release
pipeline does not. Natural production cycles are observed after deployment and
do not hold the ship.

Apply performs the candidate checks before atomically changing only the dedicated
scraper release link and managed systemd override. It then checks exact live
identity and real inspections of the supported venues. A failure restores the previous link and
override and verifies the original service/protocol/commit/source identity.
Appium, Sender, phone-agent and tunnel identities must remain unchanged.
No notification is generated by these checks.

## Browser state and diagnostics

Chromium uses its native user agent and each venue's supported booking URL. It
opens a fresh browser/driver on that venue's fixed private profile (for example
dsh-main or xmty-main) for each poll.
The previous owned browser closes before another starts. A complete observation
is atomic: any failed date or identity check discards all partial availability.

Guarded candidates and the live service use /tmp/pi-ydmap-service-profile-v2.
The installer accepts only a service-owned 0700 directory with its private 0600
ownership marker, or creates a new marked directory. Foreign owners, symlinks,
unmarked existing directories and broad permissions fail closed. Existing
profiles are not copied, exported or erased. Candidate process cleanup removes
only its own temporary process directory.

If temporary storage is cleared at boot, the service marks only a newly created
profile root. Losing that profile loses its site session; upstream access must
be verified again. Preserving a profile does not establish that unattended
provider access will remain available.

Unquiesced diagnostic preflight can use an isolated temporary profile.
The default-off capture_browser_ui option captures only a bounded public candidate
page after a source-readiness failure. Login/QR instructions, populated login
inputs and contact/IP text suppress capture. The PNG is validated, stored
privately on the Actions runner and retained as a one-day diagnostic artifact.
Image bytes, cookies and profile files never enter workflow logs.

Passive source diagnostics export only bounded public identity fields, numeric
failure categories, sanitized source snippets and hashes. They do not invoke
renderer methods, alter browser trust, remove access masks, replay requests or
prove bookability on their own. The extractor requires the provider's read-only
isAvailableStatic predicate to return a boolean and requires orderInfo to be null.
Missing predicates, non-boolean results and non-court products fail closed.

WebDriver has a per-connection 30-second HTTP timeout, beyond its 20-second
page-load and eight-second script limits. Startup and full-scrape watchdogs
remain bounded, with a 30-second cleanup reserve and five-second cleanup commands.
A transport timeout does not trigger another source request and is not evidence
of a provider challenge.

## Acceptance

1. Record the prior component identities and current production health.
2. Require the protected candidate preflight and retain its bounded report.
3. Apply the exact reviewed scraper before the affected Airflow client deployment
   (`make release` lists Pi as `notDeployedHere`; run production-pi-ydmap.yml
   first, after 09:00 so the Futian inspection runs). Otherwise new Futian DAGs
   receive `unsupported_inspection` and publish unhealthy observations. If a
   natural Futian cycle reports `captcha` or `rate_limited`, pause only those
   three DAGs and leave the scraper and Dashah running.
4. Require health and inspect for the same SHA, then three natural successful
   cycles of each YDMap DAG and fresh correctly attributed observations.
5. Preserve group routing, deduplication and natural delivery policies. The owner
   restored configured shared Zacks groups on 2026-11-01. Do not reintroduce the
   retired shared-recipient pause; keep the free-court group isolated.
6. Record exact identities and any remaining upstream access limitation.

Health establishes service/protocol/source identity. The inspect operation
validates real upstream data without writing observations. Natural DAG and
Host Core acceptance establish fresh business observations and actual delivery.
A candidate pass alone does not establish complete release acceptance.
