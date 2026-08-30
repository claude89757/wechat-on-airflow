# Changelog

This project follows Semantic Versioning. Entries describe user-visible runtime
and operational changes.

## Unreleased

### Added

- Let Web subscribers choose one or more weekdays, including one-tap daily,
  weekday, and weekend presets. Existing subscriptions continue to run every
  day.
- Celebrate successful subscription creation with a short reduced-motion-aware
  firework effect, and add clear spam-folder guidance for verification and
  reminder email.
- Add the public GitHub repository to the header More menu.
- Append booking mini-program footers for Dashah International (威逊文体),
  Fuzhongfu (泛思博特), and PICKLE POP Bao'an (PICKLEPOP宝安摩天轮馆).

### Changed

- Order the public venue list and subscription selector by unique active
  follower count, with a deterministic name/ID tie-breaker and visible
  popularity labels.
- Narrow Shenzhen Sports Center WeChat alerts on weekends from 16:00-21:00
  to 17:00-21:00. Weekdays stay 18:00-21:00. Web email windows are unchanged.

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
