# Changelog

This project follows Semantic Versioning. Entries describe user-visible runtime
and operational changes.

## Unreleased

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
- Run the synchronous WeChat sender as an independent, pinned, non-root
  Compose service with automatic restart and health checks.
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

### Removed

- Retired DAGs, archived experiments, duplicate utilities, legacy direct Appium
  notification code, Cloudflare sender gateway code, and unrelated SCF, Dify,
  Nginx, and database scripts that were not part of the production DagBag.
- The unused duplicate sender requirements file; the reproducible sender image
  uses `docker/sender/requirements.lock`.
