# Changelog

This project follows Semantic Versioning. Entries describe user-visible runtime
and operational changes.

## [Unreleased]

### Changed

- The Raspberry Pi deployment and diagnostic workflows log in with an SSH key.
  `PI_DEVICE_SSH_PRIVATE_KEY` in the protected `production` Environment is tried
  first by `scripts/pi_ssh_auth.py`; `PI_DEVICE_SSH_PASSWORD` is only the migration
  fallback, used when the key is missing, unusable or rejected. A network or
  host-key failure is never retried with the password. This covers the YDMap and
  Appium MCP deployments, the remote-operations MCP deployment, tunnel diagnosis and
  the device-network preflight. `pi_device_ssh_sync` no longer requires the password.
  Turning off the Pi's SSH password login now needs only the key authorized there.
- Operations MCP sign-in is automatic for agents. `scripts/ops_mcp.py` opens the
  Cloudflare Access authorization in the workstation's browser, which completes it
  without a click when it already holds a session, then reuses and refreshes the
  stored token. Agents no longer ask the person to log in or paste links first.
- The Dashah inspection DAG can log into the Raspberry Pi with an SSH key. When
  `PI_DEVICE_SSH` carries a `private_key` it is tried first, and the password is used
  only if the key is unusable or rejected; a network failure is never retried with
  the password. `pi_device_ssh_sync` keeps an existing `private_key`. With no key
  configured nothing changes.
- A failed Sender operation now reports the step it stopped at, its exit code and the
  install script's fixed error message. Other remote output stays withheld.
- The Sender deploy now opens one SSH connection and reuses it for every upload,
  the remote operation and cleanup. Opening it retries, because the host's sshd
  drops new connections while it is being probed with failed logins. No remote
  command is replayed.
- Adding a venue now takes one line in `src/wechat_airflow/venue_catalog.json`.
  Python, the web app, production health and browser QA read that file, and no
  check or document pins a venue count. The `all26VenueObservations` health check
  is now `allVenueObservations`, and `expected_venue_count` is gone from
  `config/runtime-target.yaml`.
- Operations MCP now runs commands as root straight after Cloudflare OAuth through
  `ops_exec`, replacing `ops_request` and its browser approval page. Commands can
  run for up to an hour and in parallel, and the audit log records their text.
- Clients without MCP tools now say so and point to the setup before falling back
  to GitHub diagnostics.
- Phone MCP preflight no longer requires `zacks-agent.service`, which no component
  uses and which has been disabled since 2026-11-02. The unit itself is untouched.
- `make release` now updates Airflow and Sender first and switches Host Core last, so
  consumers keep delivering until the switch and an earlier failure no longer pauses
  notifications. Activation retries once. A `summary` job states the failed stage, its
  effect on delivery and the next step, and `make release-resume` continues a run
  without repeating the stages that succeeded.
- Sender and the WeChat consumer now check a shared protocol version instead of an
  identical commit, so Sender deploys only when it or the consumer changed.
- Changed Pi/MCP runtimes no longer block `make release`; they are listed as not
  deployed by this workflow.
- `make release` now runs from a full delivery pause, so a fix can ship after a failed
  release. Its activation turns delivery back on. The email recovery mode, with WeChat
  off, still uses `recovery-upgrade`.

### Removed

- Remove the named 理想时段 presets (工作日晚间, 午休局, 周末上午, 周末下午,
  自定义). The create form now sets a reminder with 选择打球星期 and
  希望打球的时间段 only, still starting at Monday–Friday 19:00–22:00.
- Remove the preset label and the 改成周末上午 action from My Subscriptions, along
  with `PATCH /api/subscriptions/{id}` and the `preferencePreset` and
  `preferenceLabel` API fields. To change a window, cancel the reminder and
  create another.
- Existing subscriptions and email matching are unchanged. Reminder email now
  refers to 打球时间段 instead of 理想时段.

## [0.10.0] - 2026-11-06

### Added

- Let verified subscribers pause reminders for specific playing dates across
  their venue subscriptions, select multiple dates in My Subscriptions, restore
  individual dates, and undo the dates changed by their latest action. Preferences
  persist by email in Host Core and use the Asia/Shanghai calendar.
- Add a playing-date link to subscriber reminder emails. The website preselects
  that date and preserves the selection through email verification; opening a
  link never changes notification preferences by itself.
- Fence date changes against observation matching, queue claims and final email
  dispatch. Release unused claims for definitely-unsent cancelled reminders;
  preserve submitted or uncertain sends and all subscription history. Restoring
  a date requalifies only eligible pause-cancelled reminders on a fresh natural
  observation without resetting event identity or original creation timestamps.
- Extend the rollback-only production API probe with authenticated pause/list/
  restore, idempotency, anonymous denial, and no-subscriber-mail checks.
- Add a brief email-subscription guide to each WeChat group's first natural
  morning court alert (06:00–12:00 Asia/Shanghai). Durable per-group history
  prevents repeats across venues and restarts; safe retries and uncertain sends
  retain the existing delivery safeguards. No extra message is sent.

- Productize the existing subscription window as named ideal-time presets.
  New subscriptions created in the web app default to 工作日晚间
  (Monday–Friday, 19:00–22:00), narrower than the previous every-day evening
  default. The other presets are 午休局 (Monday–Friday 12:00–14:00), 周末上午
  (Saturday–Sunday 08:00–12:00), 周末下午 (Saturday–Sunday 14:00–18:00), and
  自定义. Button copy and `preferenceLabel` use these same words.
- Email is sent only when a free slot overlaps that personal window. WeChat
  group delivery stays venue-level: any active subscription for the venue
  opens the gate, and group messages are not filtered by the personal window.
- This phase adds no subscription column and no multi-window jsonb. A second
  window is a second subscription. Labels are derived from the stored weekday
  mask and clock.
- Changing an existing window from the subscription list asks for confirmation
  first, because the change can cancel pending or retry reminder email.
  Submitted mail and WeChat rows are left as they are.
- Integrate 深湾竞界网匹中心 (`swjj`, PosPal store `6149033`) as a one-minute
  venue DAG. Publish its seven standard and VIP wind-rain courts across the
  store's full seven-day booking window, drop the singles court, and append the
  `深湾竞界智享订场` mini-program link to WeChat alerts. This raises the active
  catalogue to 27 venues.
- Register `swjj` in the Host Core venue catalog, the Worker and Vite venue
  catalogs, the WeChat dedupe map and the quiesce scope. First successful
  observation seeds `SWJJ_NOTIFICATION_BASELINE` without delivering.
- Make `lookahead_days` and the dedupe cache capacity per venue. 深湾竞界 looks
  seven days ahead and needs a larger cache because the shared 100-entry default
  cannot hold one sweep; an evicted still-free slot would re-alert on the next
  run.

### Fixed

- Include allowlisted systemd state when a protected phone check finds an
  inactive existing service, preserving the original failure and never changing
  service state or printing raw service output.
- Identify protected phone preflight failures with fixed stage/error-code pairs,
  retaining every check without exposing exception messages or command output.
- Pass the Pi interruption option only during apply. Readiness preflight remains
  read-only and no longer rejects an apply-only option before connecting.
- Let a recovery upgrade replace a stopped WeChat consumer that is still on an
  older image. The live API and email worker must still match, and no WeChat
  consumer may be running. A failed recovery check now reports its fixed guard
  name instead of only `RuntimeError`.

- Trim PosPal classroom names before they become court keys. Four 深湾竞界 courts
  arrive with a trailing tab, which previously would have reached WeChat text.
- Treat an in-window PosPal response with no `validClassRooms` as a failure for
  venues that opt in. PosPal answers a stale `projectUid` or `STOREID` with
  `successed: true`, so the empty payload used to look like a healthy empty
  venue forever.

### Changed

- Keep required CI on lint, types, unit tests and the web unit check. Browser
  interaction runs are no longer a release gate.
- Release preflight checks that the Pi scraper and WeChat sender are alive.
  It does not pause Dashah, run three browser cycles, or install a sender
  candidate. Apply may replace the scraper while one inspection is in progress.
- Tag a full ship after worker activation. Missing natural venue cycles or
  email/WeChat receipts no longer hold the pipeline, block the tag, or pause
  delivery.
- Align the README license badge and license statement with the MIT `LICENSE`.
- State current acceptance as all 26 active venue DAGs. The count matches the
  runtime target, public venue cards, and architecture. Dated incident records
  keep their historical counts.
- Disable Dependabot automatic rebasing. Routine version-update pull requests
  stay closed to the merge queue.
- Type the shared HTTPS proxy watcher and remove it from the strict mypy
  exclusion list. The remaining six adapters stay the bounded typing backlog.

- Show only the email-subscription link on a group's first morning WeChat alert;
  omit its venue booking link without consuming the booking-link cooldown.
  Other alerts keep their booking links, including safe retries that no longer
  qualify for the morning guide, subject to the existing cooldown.

## [0.9.1] - 2026-11-01

### Changed

- Withdraw the Bao'an Tennis Center integration from PR #263 at the owner's
  request after the incomplete 0.9.0 rollout. Restore the 26-venue active
  catalogue and retire Bao'an collection and new subscriptions. Exclude the
  retired venue from delivery while retaining stored subscriptions and history.
- Limit the protected YDMap scraper rollout and real-page acceptance to
  Dashah. Retain its booking correctness, browser-state, locking, identity,
  drain, rollback and evidence safeguards, and preserve unrelated MCP changes.

### Fixed

- Add an explicit protected recovery upgrade for an already-migrated runtime
  with active email and paused WeChat. Require the recorded runtime commit and
  control timestamp, unchanged existing schema, fresh email ownership and
  passing exact-commit CI before fencing and aligning every release component.
- Keep normal routine-upgrade checks, exact Sender identity, transaction
  rollback probes and natural-delivery acceptance unchanged. A healthy release
  awaiting natural receipts remains pending without a release tag.
- Restore email through the existing consumer with stale reminders expired by
  normal policy, preserving deduplication and uncertain-send records.

This entry describes the recovery candidate. Production completion requires the
protected workflow's final evidence and is not asserted by this changelog.

## [0.9.0] - 2026-10-31

### Added

- Integrate the Bao'an Tennis Center inspection from PR #262, retaining the
  contributor's attribution. Cover today and tomorrow across the three YDMap
  products, with Host Core observations and Web venue status.
- Add protected exact-commit Pi scraper preflight, deployment, health and
  inspection operations. Validate an isolated candidate against real Dashah
  and Bao'an pages before activation, with source identity and rollback checks.
- Collect bounded, read-only booking-renderer definitions and public cell
  samples only during candidate preflight. Record coverage and redaction
  explicitly; source identity or diagnostic collection alone does not certify
  bookability.

### Fixed

- Use the page's read-only booking predicate to exclude empty cells that lack
  prices, are not open for online booking, or represent merged/special ranges.
  Preserve the original browser startup warm-up and retain bounded challenge
  evidence for Pi preflight diagnosis.
- Require source venue, product name and freshly loaded booking date evidence
  before accepting a court grid. Reject stale rows, incomplete product groups,
  access verification pages and old scraper responses instead of publishing
  misleading healthy observations.
- Quote the complete SSH curl URL so venue and day parameters reach the Pi,
  preserve curl failures, and publish observations before claiming alerts.
- Enqueue only validated availability lines. Add booking links at delivery time
  and release Bao'an dedupe claims when enqueue fails or delivery is suppressed.
- Handle midnight interval endings and booking dates across New Year.
- Serialize Dashah and Bao'an tasks in a single-slot Airflow pool so simultaneous
  schedules cannot compete for the shared Chromium scraper.
- Start the keyboard-dismiss regression gesture on settled, noninteractive
  footer padding so it tests the intended gesture instead of an input click.

### Operations

- Pause and drain only affected YDMap DAGs during scraper replacement, then
  restore their recorded pause states. Preserve existing shared-group delivery
  restrictions, notification history and unrelated device services.
- Require exact-main CI and real-page preflight before the Pi update can unblock
  Airflow and Web release. Production acceptance remains a separate evidence gate;
  this changelog does not assert that deployment has completed.

## [0.8.7] - 2026-10-31

### Changed

- Restore Dashah free-court availability alerts exclusively to
  `Zacks_大沙河限定免费`. Pause new automatic alerts to the two
  existing shared Zacks groups in `SZ_TENNIS_CHATROOMS` without removing
  their configuration or redirecting unrelated venues to the dedicated group.
- Apply the shared-group block before the durable WeChat enqueue operation,
  including overlaps in other chatroom lists. Fail closed when the paused
  recipient set cannot be read.
- Align redacted diagnosis and explicitly approved probe targets with the new
  active route. Keep existing polling, Web observations, subscriptions and
  historical dedupe data unchanged; do not replay queued historical messages.


## [0.8.6] - 2026-10-27

### Changed

- Route Dashah River free-court alerts to the existing shared Zacks chatrooms
  in `SZ_TENNIS_CHATROOMS`, retiring the dedicated free-court group route.
  Align diagnostic and explicitly approved probe targets with the shared list,
  preserving per-recipient deduplication and existing venue notification history.

### Fixed

- Stage all exact locked ARM32 CPython 3.11 wheels through the protected runner
  using reviewed HTTPS sources, hashes, sizes and tags. Candidate and installer
  independently validate the complete private wheelhouse before offline,
  binary-only installation with pip configuration sources disabled. Preserve
  the existing timeout, isolated environments and dependency/image gates.
- Report bounded Sender candidate-install failure categories, exact locked failed
  requirements and pip ABI evidence without exposing package-index output. The
  diagnostic does not change dependencies, install policy or active services.
- Preserve bounded partial pip output on candidate timeout as fixed network and
  progress evidence plus the last observed locked requirement. Keep timeout as
  the primary failure and retain the existing 300-second installation limit.
- Preserve the explicitly retired Shenzhen Bay fourth-day observation as visible
  historical evidence without requiring it to keep polling. The exact retirement
  is validated against the active task manifest; all other stored observation
  scopes and every venue, cycle and delivery gate remain required.
- Pin Pillow 13.0.0 in both sender installation paths and isolate the systemd
  Python 3.11/3.12 environment from distribution packages. Verify the actual imported
  version, origin and screenshot/OCR operations before activation and in health.
- Preserve the active sender environment on dependency/preflight failure instead
  of restoring an unrelated retained rollback environment.

### Operations

- Gate the coupled release on a non-activating sender dependency preflight using
  the actual host architecture and existing service interpreter. Stage the complete
  candidate lock
  in a temporary isolated venv; never modify the active service during this check.
- Preserve existing identities, network settings, PostgreSQL and sender ledger;
  reuse the supported Python 3.11/3.12 already running the service, never replace
  the OS interpreter; require coupled runtime identity and natural-cycle acceptance,
  without synthetic
  email or WeChat sends.

- Keep technically healthy delivery active while natural-message acceptance is
  pending; do not tag or complete a release until all original evidence arrives.
  Same-run failed-job retries preserve the acceptance window and per-attempt
  artifacts, and cannot move a newer runtime back to an older checkout.
- Collect only fixed read-only preflight business aggregates; dirty production
  worktrees now block preflight rather than being implicitly repaired.

## [0.8.5] - 2026-10-20

### Changed

- Poll Shenzhen Bay every two minutes and Greater Bay Area every three
  minutes, only from 08:00 inclusive to 21:00 exclusive in Asia/Shanghai.
  Keep the interval schedules and internal healthy empty observations outside
  that window to refresh status and clear stale availability.
- Rotate the three shared CRLand accounts independently by each venue's
  scheduled round. Each account recurs every six minutes for Shenzhen Bay
  and every nine minutes for Greater Bay Area during uninterrupted polling.
  Preserve the selected account across date tasks, booking areas and retries.
- Check the active window before each upstream attempt and final publication;
  discard partial results and publish one idle empty observation when the
  window closes, without attempting reminders from that round.
- Limit Shenzhen Bay inspection to today and the next two calendar days, as
  explicitly requested. Retire `check_and_notify_day_3` and align the active
  task manifest, bounded diagnosis and three-day account-rotation coverage.
- Align the Web cadence labels and documented policy while preserving DAG IDs,
  retained task IDs, booking areas and notification eligibility rules.

### Operations

- Add owner-only protected read-only commands for exact-commit Airflow health
  and bounded CRLand inspection evidence. Report scheduled runs, task states,
  account rotation slots and allowlisted error codes without exporting raw
  logs, credentials or recipient data.
- Read dated scheduled-run metadata in the existing index order and retain
  strict read-only transaction and timeout limits. Classify collection errors
  using fixed stages, exception types and SQLSTATE values without exposing
  database queries, parameters or exception text.
- Verify three successful natural polling rounds inside the active window for
  each venue, including account rotation, after exact-commit Airflow and Web
  deployment. Off-hours no-query successes do not replace polling evidence.

## [0.8.4] - 2026-10-19

### Changed

- Rotate three CRLand accounts in shared one-minute rounds for Shenzhen Bay
  and Greater Bay Area. Both venues inspect every minute; each account is
  selected once per three minutes. Keep the same account for every date and
  booking area within a scheduled round, including delayed tasks and retries.
- Preserve the existing DAG/task identities, date coverage, concurrency and
  notification rules. Keep the one-minute policy and Web labels consistent.
- Prefer the sensitive `SZW_API_AUTHORIZATIONS` three-account pool, retaining
  the single `SZW_API_AUTHORIZATION` fallback only when the pool is absent.

### Operations

- Add a protected `szw_authorization_sync` operation for the shared account
  pool. Validate all three accounts against Shenzhen Bay outdoor, covered and
  Greater Bay Area queries before replacing the Airflow Variables, and verify
  the transaction without exposing credentials or account identifiers.
- Require exact-commit CI and the existing production Environment for the
  credential sync and release. Verify three natural successful cycles after
  deployment without sending synthetic email or WeChat notifications.

## [0.8.3] - 2026-10-01

### Fixed

- Require coordinated Host Core and Sender publication when either runtime changes.
  A Sender-only upgrade can pass device readiness while the exact-version consumer
  refuses every notification; partial release scopes now reject this combination.
- Include the shared-phone lease and synchronized idle-session cleanup from #225,
  retaining durable idempotency and unknown-submission quarantine.
- Extend protected read-only inventory with current PostgreSQL WeChat queue counts,
  bounded 24-hour error categories and lifetime outcomes. Never expose recipients,
  message bodies or raw exception text; historical uncertainty remains visible.

### Operations

- Recover the split deployment documented in #226 using the existing protected
  `scope=all sender=true` ship lifecycle after exact-SHA CI, then verify natural
  venue cycles and actual delivery before publishing the immutable release.
- Preserve PostgreSQL, Sender SQLite, subscriptions, credentials and historical
  failed/unknown records. Do not replay stale alerts or emit synthetic messages.

## [0.8.2] - 2026-09-07

### Fixed

- Include the mainline PosPal enrollment-overlay fix (#216); occupied activity courts
  are no longer advertised as directly bookable whole courts.
- Exclude already-started Dashah free slots using Asia/Shanghai and reject malformed
  upstream collections instead of publishing a false healthy-empty result.
- Require a durable observation acknowledgement before claiming WeChat notices;
  stale lines no longer block unrelated valid lines at enqueue or dispatch.
- Distinguish sender preparation from irreversible UI submission with a durable
  checkpoint; only proven-unsent outcomes retry (bounded), never ambiguous sends.
  Remove click-level stale-element retries and preserve privacy-safe error codes.
- Reconcile uncertain transport outcomes with the sender ledger using the exact
  payload hash; only confirmed sent records are finalized, never replayed.
- Explain inactive/expired personal subscriptions separately from global email
  delivery. Existing disabled subscriptions remain untouched.
- Run the fenced Host Core lifecycle and natural-delivery acceptance for every
  scope=all ship, not only 0.7.0. Reject Host Core changes under a partial scope.

### Operations

- Ship with `scope=all sender=true` after exact-SHA CI. All runtime components
  must pass production acceptance before the immutable release is published.
- Preserve historical unknown outcomes, subscriptions, credentials and the D1
  archive. No synthetic emails or WeChat messages are sent for verification.

## [0.8.1] - 2026-09-06

### Fixed

- Canonicalize contiguous Dashah International (`dsh`) scraper cells into stable
  maximal availability ranges before publishing them to Host Core. A poll that
  reports `21:00-21:30` plus `21:30-22:00` now has the same subscriber-email
  event identity as a later poll that reports `21:00-22:00`, preventing the
  duplicate reminder reproduced on 2026-09-06.
- Use the same canonical availability shape for Web subscription observations
  and the existing WeChat notification path, with regression coverage for the
  split-half-hour versus merged-one-hour representation.

### Operations

- This is an Airflow-only patch. It does not change Web assets, Sender runtime,
  polling cadence, PostgreSQL schema, subscription data, or provider credentials,
  and release acceptance must not emit synthetic email or WeChat notifications.

## [0.8.0] - 2026-09-05

### Court Studio

- Rebuild the responsive Web dashboard with an editorial tennis identity,
  a clear first-use explanation, an always-reachable create action, and a
  narrow-left / wide-right desktop workspace.
- Add local venue search, subscribed/attention filters and actionable empty
  states without adding background API polling or displaying bookable slots.
- Keep the tested email-verification, subscription, coffee invitation, tier,
  community and admin flows; clarify booking-time labels and add time presets.
- Clear a verification challenge when its email changes, preserve quick-venue
  selection, distinguish unknown/stale/healthy data, and preserve priority
  weather behavior, masking, keyboard and reduced-motion support.
- Expand CI to all browser suites and gate Web publication on read-only public
  desktop/mobile/small-screen checks with archived screenshots. No test mail
  or WeChat notifications are generated.
- This is a Web-only release. Host Core/Airflow/Sender keep their accepted
  0.7.0 runtime identity; no database migration or notification restart occurs.

## [0.7.0] - 2026-09-04

### Host Core production hardening (2026-09-05)

- Remove legacy Cloudflare/D1 runtime and automatic fallback; protected, fenced
  Host Core-only cutover preserves the source database and host backup.
- Fix durable verification attempt counting, expired subscription recreation,
  concurrent limits and cancellation; serialize coffee claims.
- Add per-booking-date weather, stale intent expiration, pre-dispatch attempts,
  unknown-result quarantine, provider reconciliation leases and precise readiness.
- Move WeChat device I/O into a dedicated PostgreSQL worker with per-device
  durable SQLite idempotency on the Sender.
- Preserve invitation cryptography and migrate/reconcile all 15 source tables.
- Add real PostgreSQL regression tests, exact-commit business acceptance and
  an operator-only production transaction-rollback API probe.


### Added

- Add the PostgreSQL-backed Airflow-host subscription, observation, notification,
  migration, and delivery runtime, including an exact-commit API service and a
  leased notification worker.
- Add a protected shadow-migration and cutover workflow that transfers existing
  D1 state and Tencent SES configuration without exposing plaintext credentials
  to GitHub or sending synthetic notifications.
- Add a stateless Cloudflare edge gateway that serves the Web assets while
  proxying API calls to the host after cutover.

### Changed

- Make PostgreSQL schema `zacks` the authoritative durable store for identities,
  subscriptions, event deduplication, quotas, email Outboxes, and provider state.
- Move subscriber email matching, Tencent SES delivery, retry, and reconciliation
  from Cloudflare to the Airflow host.
- Move the venue-level WeChat subscription gate from D1 to local PostgreSQL while
  retaining the existing Airflow-to-Android delivery path.
- Reduce Cloudflare to DNS/TLS/WAF, static assets, a stateless API proxy, and
  Tunnel ingress; retain D1 read-only for the rollback window.
- Preserve every active venue polling cadence and isolate existing email and
  WeChat delivery from Cloudflare D1 availability.

## [0.6.6] - 2026-08-31

### Added

- Add a dedicated desktop browser workspace for viewports at 900px and above
  while continuing to use the existing mobile state, validation, API, and
  subscription logic.
- Add a 1180px two-column layout with a high-density venue grid and a sticky
  subscription task pane so users can monitor courts and create reminders in
  parallel.

### Changed

- Present shared mobile bottom sheets as centered, viewport-safe desktop dialogs
  with multi-column form controls, internal scrolling, and Escape-key dismissal.
- Restore desktop pointer, hover, scrollbar, visible keyboard-focus, and reduced-
  motion behavior without changing the protected narrow-screen runtime.
- Keep viewports below 900px on the existing compact/mobile interaction model and
  cover the 899/900px breakpoint plus the 1440px workspace in Chromium tests.

## [0.6.5] - 2026-08-30

### Added

- Replace the mobile venue status rows with compact, touch-friendly cards that
  retain inspection health, configured cadence, status-sync age, follower count,
  and the latest confirmed reminder delivery.
- Open a venue-prefilled quick subscription flow directly from each card while
  preserving email verification, weekday, time-window, and term controls.

### Changed

- Use three venue-card columns on typical phones and two below 360px, with
  keyboard activation, visible focus, subscription-count and limit states, and
  post-creation card highlighting.
- Keep the existing full multi-venue creation flow available through “添加其他场地”.

## [0.6.4] - 2026-08-30

### Changed

- Keep the normal 30-second Web display refresh on the existing 120-second
  client and edge cache path, while making an explicit manual refresh fetch
  current dashboard data and report completion to the user.
- Prioritize verified users' personal subscription and delivered-email metrics,
  label global metrics explicitly, and rename the first-level support action to
  ‘支持 Zacks’.

### Fixed

- Derive fallback venue totals from the full 26-venue catalog so initial and
  degraded states no longer display the obsolete 15-venue total.
- Require confirmation before cancelling a subscription, restore visible
  keyboard focus, increase key mobile status text above 9px, and align browser
  and source contracts with the removed subscriptions footer entry.

## [0.6.3] - 2026-08-30

### Changed

- Merge the standalone header help button into the existing More menu, keeping
  the same help sheet while simplifying the narrow-screen header to support
  author and More actions only.
- Add mobile interaction coverage for opening Help from More and preserving the
  320px header layout.

## [0.6.2] - 2026-08-30

### Added

- Let Web subscribers choose one or more weekdays, including one-tap daily,
  weekday, and weekend presets. Existing subscriptions continue to run every
  day.
- Celebrate successful subscription creation with a short reduced-motion-aware
  firework effect, and add clear spam-folder guidance for verification and
  reminder email.
- Add the public GitHub repository to the header More menu.

### Changed

- Order the public venue list and subscription selector by unique active
  follower count, with a deterministic name/ID tie-breaker and visible
  popularity labels.

### Fixed

- Distinguish each venue's configured Airflow inspection cadence from the most
  recent Cloudflare-backed status synchronization time, so a cached “4 minutes
  ago” record is not mistaken for a missed one-minute poll.
- Keep the display correction within the existing five-minute observation
  heartbeat and 120-second edge/client dashboard caches, adding no Worker route,
  D1 read/write, cron, or venue polling change.

## [0.6.1] - 2026-08-30

### Added

- Add FFTENNIS Qianhai International Tennis Center (`fft_qianhai`) to the Web
  subscription catalog and a one-minute Airflow inspection DAG backed by its
  public, TLS-verified PosPal V2 availability API.
- Publish only courts 1–6 / standard double courts from FFTENNIS and exclude
  non-standard singles and ball-machine courts before Web observation or
  WeChat. Warm-start the first WeChat notification baseline without delivery.

## [0.6.0] - 2026-08-30

### Added

- Add ten Fansibote chain tennis venues to the Web subscription catalog and
  30-second Airflow inspection DAGs: 棕榈泉, 观湖, 坂田, 沙河, 保税, 南油,
  新桥, 壹方城, 麒麟, and 茅洲河.

### Changed

- Drop 非标 and 发球机 courts from the shared PosPal adapter, in addition to
  小场, 匹克, and 练习, so only standard tennis / 风雨场 courts are published.

## [0.5.3] - 2026-08-30

### Added

- Append booking mini-program footers for Dashah International (威逊文体),
  Fuzhongfu (泛思博特), and PICKLE POP Bao'an (PICKLEPOP宝安摩天轮馆).

### Changed

- Narrow Shenzhen Sports Center WeChat alerts on weekends from 16:00-21:00
  to 17:00-21:00. Weekdays stay 18:00-21:00. Web email windows are unchanged.
- Before 12:00 Asia/Shanghai, inspect only the four already released Dashah
  International booking dates. Restore the rolling fifth date at noon so its
  pre-release disabled cells cannot be published or pushed as false availability.

## [0.5.2] - 2026-08-29

### Changed

- Restore newly introduced target DAGs as unpaused even when a previous
  failed rollout left them paused in Airflow metadata, so apply no longer
  preserves that leftover and immediately fails health.

## [0.5.1] - 2026-08-29

### Changed

- Treat a newly declared DAG whose completed runs are all successful but
  still fewer than the required observation cycles as apply-time healthy
  warming-up, so 30-second venue DAGs are not rolled back after their first
  one or two successes.

## [0.5.0] - 2026-08-29

### Added

- Add five Fansibote chain tennis venues to the Web subscription catalog and
  30-second Airflow inspection DAGs: 深云, 蛇口, 新安, 正中, and 安托山.
- Keep only standard tennis / 风雨场 courts from the shared PosPal V2 payload
  and drop 小场, 匹克, and 练习 courts before Web observation or WeChat.

### Changed

- Treat a successful PosPal V2 response with zero bookable rooms as a healthy
  empty result so these stores can stay green until online booking opens.

## [0.4.0] - 2026-08-29

### Added

- Add PICKLE POP Bao'an (`ppba`) to the Web subscription catalog and a
  30-second Airflow inspection DAG on the same public PosPal booking API as
  TOPS and Fansibote Fuzhongfu.
- Publish tennis-only availability to the Web app and send best-effort WeChat
  alerts to the shared Zacks chatrooms. Pickleball courts stay out of tennis
  observations.

## [0.3.0] - 2026-08-29

### Added

- Add paid Dashah International Tennis Center (`dsh`) to the Web subscription
  catalog and a 3-minute Airflow inspection DAG.
- Collect five booking days from the Raspberry Pi Chromium scraper, publish raw
  slots to the Web app, then send best-effort WeChat alerts to the shared Zacks
  chatrooms.
- Seed Airflow Variable `PI_DEVICE_SSH` from GitHub `production` Environment
  secrets through the protected `pi_device_ssh_sync` operation.

### Changed

- Treat a newly declared DAG with no run history as healthy at apply time so
  the first natural cycles can occur after unpause.
- Restore newly introduced target DAGs as unpaused instead of leaving them
  paused by the missing-state default.
- Classify Raspberry Pi scrape-host files as release metadata so they do not
  force a WeChat sender deployment.

## [0.2.4] - 2026-08-28

### Changed

- Submit priority-user venue reminder digests before standard-user digests and
  keep a full ten-second lead after the latest priority submission attempt
  completes, including across concurrent Cloudflare Worker drains.
- Keep email verification and subscription-expiry messages outside the reminder
  priority gate, preserve every existing venue polling schedule, and defer a
  standard reminder instead of submitting it early when priority work remains
  active beyond one bounded Worker wait.

## [0.2.3] - 2026-08-23

### Changed

- Plan and validate release scope before waiting for CI, so a missing sender
  approval or unsafe manually narrowed scope fails immediately instead of after
  a potentially long queued check.
- Expose requested scope, resolved scope, and the actual Web, Airflow, and sender
  component operations in the one authoritative production-control report.

### Fixed

- Give only the exact current `main` head a short 60-second check-registration
  grace, avoiding a race immediately after merge while historical SHAs with no
  CI record continue to fail immediately.

## [0.2.2] - 2026-08-23

### Changed

- Route owner-approved release, tag, and production-operations comments through
  one `Production Control` workflow so one command produces one authoritative
  Action run and one final report.
- Add `/release ship <version> <sha>` to validate the named release, deploy the
  required components, verify production health, and create the immutable tag
  and GitHub Release in one run.
- Plan CI and production deployment scopes from changed files. Web-only patches
  no longer rebuild or replace Airflow, control-only releases deploy no runtime,
  and stale pull-request CI runs are cancelled automatically.
- Make Web apply mode run its own build, Wrangler dry-run, and migration listing
  before mutation, so routine low-risk releases do not need a separate preflight
  workflow run.

### Fixed

- Remove overlapping `issue_comment` listeners that made `/release tag` look
  like a failed production release even when the dedicated tag workflow passed.
- Remove the duplicate 30-minute CI wait from ChatOps; the exact-SHA production
  gate remains the only authority for queued, successful, failed, or missing CI.
- Reject a manually narrowed release scope when it omits a detected runtime
  component, and require explicit `sender=true` approval for sender deployment.

## [0.2.1] - 2026-08-23

### Fixed

- Prevent the mobile dashboard from entering its drag or rubber-band state when
  the pointer moves from the top-right More trigger into the opened menu.

## [0.2.0] - 2026-08-23

### Added

- Add a header coffee-support sheet with the supplied WeChat QR and a
  server-timed easter egg that issues one 30-day priority invite per verified
  email after the QR has remained visible for five seconds.
- Monitor 泛思博特福中福 tennis availability on the same PosPal booking API as
  TOPS, publish observations to the Web app, and send best-effort WeChat alerts
  to the shared Zacks chatrooms.
- Add protected GitHub workflows for Cloudflare Worker/D1 deployment, exact-SHA
  Web health checks, and one release gate spanning Web, Airflow, and the sender.
- Notify `Zacks_大沙河限定免费` for Dashah River free-court availability after
  the Web observation and WeChat dedupe cache are written.
- Append venue booking mini-program links to WeChat availability alerts, at most
  once per chat and mini-program every two hours, with Shenzhen Bay and Greater
  Bay Area sharing the 未来荟 card.

### Changed

- Reboot the Zacks WeChat sender phone every two days instead of daily, keeping
  the 05:00 Asia/Shanghai slot.
- Move My Subscriptions, User Community, and Admin into an accessible header
  More menu, and shorten the coffee entry to “☕ 支持作者” while retaining a
  full accessible label and compact narrow-screen behavior.
- Fail the production gate immediately when an older target SHA has no CI check
  record, while continuing to poll checks that are queued or in progress.
- Treat Airflow deploy plus full production health as one transaction: if the
  new containers start but the complete health gate fails, automatically
  restore the pre-deploy SHA, verify the restored version, and fail the release.
- Restore the Airflow image and provider pins to the supported 3.3.0 runtime
  contract, and make CI reject Dockerfile, provider, Compose, or manifest
  version drift before deployment.
- Reduce the standard subscriber reminder cap from 30 to 10 digest emails per
  Shanghai calendar day; the priority cap remains 100.
- Make GitHub the only production delivery control plane: workstations keep
  only GitHub authentication, CI owns the release gate, and production health
  compares against an explicit workflow target SHA instead of local `HEAD`.
- Remove local Wrangler production commands and the unrelated workstation
  database-backup requirement from reversible application preflights.
- Reuse a warm Appium session in the WeChat sender and honor an idempotency key
  so Airflow retries do not double-send after a late HTTP timeout.
- Filter Greater Bay Area WeChat alerts to weekday 18:00-21:00 and weekend
  12:00-21:00, query the booking API only until 21:00, and keep the shared Zacks
  chatrooms used by Shenzhen Bay.
- Wait up to 150 seconds for the single WeChat device lock, floor Airflow send
  timeouts at 210 seconds, and retry `device_busy` with a 15-second pause so
  overlapping venue DAGs queue instead of immediately writing the fallback outbox.
- Accept `dsh_free:N` as a protected WeChat probe selector so the dedicated
  Dashah free-court group can be smoke-tested without other Zacks chats.
- Expose the Airflow 3 UI and API through a managed Cloudflare Tunnel at
  `airflow.claude89757.cc`, trust reverse-proxy headers, and bind the origin
  port to loopback only.
- Serve Airflow directly from the hostname root and enforce the matching
  private `/execution/` route in configuration and production checks.

## [0.1.0] - 2026-07-19

### Changed

- Migrate the target runtime from Airflow 2.10.5 to Airflow 3.3.0.
- Use the official Airflow image, API Server architecture, Standard Provider
  operators, Task SDK authoring API, CeleryExecutor, and FAB Auth Manager.
- Move notification and Android-host clients from the DAG scan path into the
  installable `wechat_airflow` package.
- Move venue, proxy refresh, and device maintenance implementations into the
  installable package, leaving production DAG files as schedule-and-wiring wrappers.
- Verify active DAG source files and task IDs against the machine-readable
  manifest, and include the Airflow 3 DagBag check in `make verify`.
- Keep venue recipient lists independent and make email and WeChat failure
  outboxes explicit.
- Add Agent-Native manifests, deterministic verification commands, production
  health checks, migration runbooks, and CI.
- Run the synchronous WeChat sender as an independent, exact-commit, non-root
  systemd service with automatic startup, restart, and readiness checks; retain
  Compose as an alternate development runtime.
- Add metadata relation sizes, disk headroom, and managed-service status to the
  read-only production health gate.
- Pin Android-host SSH keys by SHA-256 fingerprint and disable legacy
  `ssh-rsa` SHA-1 negotiation.
- Start Airflow 3 with a fresh metadata database, preserve the Airflow 2 data
  for rollback, and migrate only contract-declared configuration and continuity
  caches.
- Reset fallback outboxes without replay during the fresh start and verify
  imported Variable values without logging them.
- Pin PostgreSQL and Redis by pullable registry manifest digests instead of
  host-local image configuration IDs.
- Bundle production DAGs into the pinned Airflow image and verify their
  readability in production health checks.
- Read Variable health state directly from the metadata database so Airflow 3
  task-context APIs cannot cause false missing-configuration reports.
- Make the private Execution API URL explicit and probe its route so a public
  API path prefix cannot make every Celery task fail with a pre-execution 404.
- Use the Airflow 3 Task SDK `Variable.get(default=...)` contract throughout
  venue, notification, proxy, and device tasks.
- Isolate failures from individual public proxy sources so one removed list
  cannot abort an entire proxy refresh.
- Evaluate production run history using each DAG's declared latest-run or
  multi-cycle verification contract.
- Derive WeChat readiness from the configured sender endpoint and record the
  Android device host as the service runtime owner.
- Add a fail-closed, default-read-only Airflow application deployment command
  with exact-commit images, automatic application rollback, and stateful-service
  isolation.
- Verify production deployment identity dynamically against local Git HEAD
  instead of storing a self-invalidating commit hash in the component manifest.
- Drain active task instances and preserve DAG pause state during application
  deployment so worker replacement cannot interrupt venue or proxy tasks.
- Batch deployment pause-state changes through the Airflow CLI and restore
  scheduling on SSH hangup instead of issuing one long-lived command per DAG.
- Move metadata cleanup out of the Airflow 3 Task SDK execution boundary into
  a default-read-only deployment-manager command with explicit deletion
  confirmation and backup checks.

### Removed

- Retired DAGs, archived experiments, duplicate utilities, legacy direct Appium
  notification code, Cloudflare sender gateway code, and unrelated SCF, Dify,
  Nginx, and database scripts that were not part of the production DagBag.
- The unused duplicate sender requirements file; the reproducible sender image
  uses `docker/sender/requirements.lock`.
