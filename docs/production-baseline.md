# Production Baseline

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
