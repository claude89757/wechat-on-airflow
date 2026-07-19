# Production Baseline

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
identity is verified dynamically by `make production-health` against the local
Git HEAD rather than duplicated as mutable state in the component manifest.

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
