# Changelog

This project follows Semantic Versioning. Entries describe user-visible runtime
and operational changes.

## Unreleased

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
