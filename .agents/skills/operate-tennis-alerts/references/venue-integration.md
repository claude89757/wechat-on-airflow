# Venue Integration

Checklist for adding one Shenzhen tennis venue to the platform. Every venue
touches the same machine-readable contracts, and several counts and sequence
numbers must move together. Re-read the current values instead of reusing the
numbers written here; they drift with every integration.

## 1. Classify The Venue

- **PosPal / 银豹 mini program** → extend the shared adapter in
  `src/wechat_airflow/venues/pospal_venue.py`. Do **not** copy
  `ppba_watcher.py` or `fsb_watcher.py` into a new full adapter; those predate
  the shared base class and are legacy.
- **Any other platform** → write a full adapter modeled on the most recent
  non-PosPal watcher.

A venue is PosPal when its mini program talks to
`https://wxservice<shard>.pospal.cn/wxapi/...`. Confirm by finding `storeId`
and `serverBase` in the package's `app-config.json` under `ext`, then calling
`AppointmentVenue/LoadValidClassRoomApptSettingV2` in guest mode.

## 2. PosPal Venue: Four Files

1. Add one `PosPalVenue(...)` constant in `pospal_venue.py`, alongside
   `FSB_SHENYUN` and friends. Supply `venue_id`, `venue_name`, `store_id`,
   `project_uid`, `cache_key`, `dag_id`, and `proxy_cache_key` when the venue
   must not share the chain proxy cache.
2. Create `src/wechat_airflow/venues/<id>_watcher.py` as a thin wrapper:
   import the constant and `run_check`, define `run_check_tennis_courts()`.
3. Create `dags/tennis_dags/sz_tennis/<id>_watcher.py`, wiring-only, one
   `PythonOperator`, `schedule=timedelta(seconds=30)`, `max_active_runs=1`,
   `catchup=False`.
4. Create `tests/<id>_watcher_test.py`. Cover at least: slot filtering, the
   notification window, deduplication, no direct API call without a proxy, and
   `webapp` publishing preceding `wechat` delivery.

If court filtering needs different rules, extend the base class with a
per-venue field rather than forking the adapter.

## 3. Touch Points Every Venue Needs

| File | Change |
| --- | --- |
| `config/active-components.yaml` | New `active_dags` entry: `direct_modules`, `airflow_variables`, `external_services`, `verification` |
| `config/config-contracts.yaml` | Two Variables: `<ID>_PROXY_CACHE` and `<场馆名网球场>`, both `json_list` + `managed_by_application: true`; add the DAG id to `SZ_TENNIS_CHATROOMS.required_by` |
| `config/runtime-target.yaml` | `expected_venue_count` + 1 |
| `scripts/quiesce_wechat_delivery.py` | DAG id into `WECHAT_DAG_IDS` **and** bump the inline `expected_paused` in the remote script body |
| `tests/ops_scripts_test.py` | Three counts: `len(WECHAT_DAG_IDS)`, the `expected_paused = N` literal, and `paused_wechat_dags` |
| `tests/webapp_notification_test.py` | Add `"<id>_watcher.py": "run_check_tennis_courts"` to the watcher map |
| `src/wechat_airflow/notifications/booking_links.py` | `BookingMiniProgram` constant plus `VENUE_BOOKING_PROGRAMS` entry |
| `tests/booking_links_test.py` | Catalog entry and link assertion |
| `webapp/cloudflare/domain.ts` + `domain.test.ts` | `VENUES` entry, venue count, subscription test |
| `webapp/src/api.ts` | `VENUE_IDS`, `FALLBACK_VENUES`, and **both** `totalVenues` metrics |
| `webapp/src/Prototype.tsx` | `VENUE_ACCENTS` and `VENUE_ICONS` entries |
| `webapp/migrations/00NN_add_<id>_venue.sql` | `INSERT OR IGNORE INTO venue_status`, using the next free sequence number |
| `pyproject.toml` + `src/wechat_airflow/__init__.py` | Bump version in both, always together |
| `CHANGELOG.md`, `README.md`, `README.en.md`, `ARCHITECTURE.md`, `docs/runbooks/configuration.md` | Document the venue and the new Variable |

## 4. Counts And Sequence Numbers

Verify current values before editing; these were correct at `0.5.2` (`aed26b2`):

- `expected_venue_count: 15`
- `WECHAT_DAG_IDS`: 14 entries
- inline `expected_paused = 14`
- `tests/ops_scripts_test.py`: 14 in three places
- newest migration: `0012_add_fsb_chain_venues.sql`

A forgotten count fails `make verify`, not production. A duplicated migration
number is worse: D1 applies migrations by filename order and `INSERT OR IGNORE`
will silently skip a colliding file.

## 5. Court Filtering Trap

Never assume a court name contains 网球. FFTENNIS前海 names its courts
`1号（双打场）`, `7号（非标单打场）`, and similar. Copying a matcher built on
`"网球" in court_name` filters out **every** court, so the venue runs green
forever and never notifies anyone.

Prefer the project name carried on the slot, `classroomInfo.projectName`
(`网球场` for a tennis-only store). The shared base class excludes by
`EXCLUDED_COURT_TOKENS` instead. Whichever rule you use, add a test that would
fail under the other rule.

## 6. Gates And Go-Live

1. `make verify` locally (development evidence only).
2. Commit, push, open a PR, require GitHub `CI / verify` on the exact SHA.
3. Ship with `/release ship <version> <full-sha> scope=auto sender=false`.
   Venue additions touch DAGs, webapp, and migrations, so both `airflow` and
   `webapp` resolve into scope.
4. Observe the `production_cycles` count in `config/runtime-target.yaml` using
   natural runs.
5. Confirm unauthenticated `/api/bootstrap` exposes the new venue count and no
   email address.
