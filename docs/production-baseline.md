# Production Baseline

Observed on 2026-07-16 before the Airflow 3 migration.

## Latest Read-only Refresh

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

## Runtime

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
committed. The full migration and restore-based rollback rehearsal completed on
2026-07-17; see [`migration-rehearsal-2026-07-17.md`](migration-rehearsal-2026-07-17.md).
Production migration approval remains blocked by the report's storage and
external-service gates.

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

Only 16,957,681,664 bytes were free on the root filesystem. This is less than
the metadata database and also less than the `task_instance` relation that the
Airflow 3 UUID migration rewrites. An in-place production migration is
therefore blocked until reliable disk capacity is added or a separately
approved restore-based compact migration is rehearsed.

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

## Migration Gates

Before production migration:

1. Produce and verify an encrypted PostgreSQL backup outside the failed
   secondary filesystem.
2. Restore it into an isolated PostgreSQL instance.
3. Run Airflow 3 and FAB migrations against the copy.
4. Prove all active DAGs import with zero errors.
5. Run no-delivery contract and smoke tests.
6. Record migration duration and disk growth.
7. Prepare and verify database restore commands.
8. Obtain approval before the production major-version database migration.
