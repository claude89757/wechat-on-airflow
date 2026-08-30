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

### Changed

- Order the public venue list and subscription selector by unique active
  follower count, with a deterministic name/ID tie-breaker and visible
  popularity labels.

## [0.5.3] - 2026-08-30

### Added

- Append booking mini-program footers for Dashah International (å¨é€Šæ–‡ä½“),
  Fuzhongfu (æ³›æ€åšç‰¹), and PICKLE POP Bao'an (PICKLEPOPå®å®‰æ‘©å¤©è½®é¦†).

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
  30-second Airflow inspection DAGs: æ·±äº‘, è›‡å£, æ–°å®‰, æ­£ä¸­, and å®‰æ‰˜å±±.
- Keep only standard tennis / é£é›¨åœº courts from the shared PosPal V2 payload
  and drop å°åœº, åŒ¹å…‹, and ç»ƒä¹  courts before Web observation or WeChat.

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
- Keep email veri™¥…Ñ¥½¸…¹ÍÕ‰ÍÉ¥ÁÑ¥½¸µ•áÁ¥Éäµ•ÍÍ…•Ì½ÕÑÍ¥‘”Ñ¡”É•µ¥¹‘•È(€ÁÉ¥½É¥Ñä…Ñ”°ÁÉ•Í•ÉÙ”•Ù•Éä•á¥ÍÑ¥¹œÙ•¹Õ”Á½±±¥¹œÍ¡•‘Õ±”°…¹‘•™•È„(€ÍÑ…¹‘…ÉÉ•µ¥¹‘•È¥¹ÍÑ•…½˜ÍÕ‰µ¥ÑÑ¥¹œ¥Ğ•…É±äİ¡•¸ÁÉ¥½É¥Ñäİ½É¬É•µ…¥¹Ì(€…Ñ¥Ù”‰•å½¹½¹”‰½Õ¹‘•]½É­•Èİ…¥Ğ¸((ŒŒlÀ¸È¸Ít€´€ÈÀÈØ´Àà´ÈÌ((ŒŒŒ¡…¹•((´A±…¸…¹Ù…±¥‘…Ñ”É•±•…Í”Í½Á”‰•™½É”İ…¥Ñ¥¹œ™½È$°Í¼„µ¥ÍÍ¥¹œÍ•¹‘•È(€…ÁÁÉ½Ù…°½ÈÕ¹Í…™”µ…¹Õ…±±ä¹…ÉÉ½İ•Í½Á”™…¥±Ì¥µµ•‘¥…Ñ•±ä¥¹ÍÑ•…½˜…™Ñ•È(€„Á½Ñ•¹Ñ¥…±±ä±½¹œÅÕ•Õ•¡•¬¸(´áÁ½Í”É•ÅÕ•ÍÑ•Í½Á”°É•Í½±Ù•Í½Á”°…¹Ñ¡”…ÑÕ…°]•ˆ°¥É™±½Ü°…¹Í•¹‘•È(€½µÁ½¹•¹Ğ½Á•É…Ñ¥½¹Ì¥¸Ñ¡”½¹”…ÕÑ¡½É¥Ñ…Ñ¥Ù”ÁÉ½‘ÕÑ¥½¸µ½¹ÑÉ½°É•Á½ÉĞ¸((ŒŒŒ¥á•((´¥Ù”½¹±äÑ¡”•á…ĞÕÉÉ•¹Ğµ…¥¹€¡•…„Í¡½ÉĞ€ØÀµÍ•½¹¡•¬µÉ•¥ÍÑÉ…Ñ¥½¸(€É…”°…Ù½¥‘¥¹œ„É…”¥µµ•‘¥…Ñ•±ä…™Ñ•Èµ•É”İ¡¥±”¡¥ÍÑ½É¥…°M!Ìİ¥Ñ ¹¼(€$É•½É½¹Ñ¥¹Õ”Ñ¼™…¥°¥µµ•‘¥…Ñ•±ä¸((ŒŒlÀ¸È¸Ét€´€ÈÀÈØ´Àà´ÈÌ((ŒŒŒ¡…¹•((´I½ÕÑ”½İ¹•Èµ…ÁÁÉ½Ù•É•±•…Í”°Ñ…œ°…¹ÁÉ½‘ÕÑ¥½¸µ½Á•É…Ñ¥½¹Ì½µµ•¹ÑÌÑ¡É½Õ (€½¹”AÉ½‘ÕÑ¥½¸½¹ÑÉ½±€İ½É­™±½ÜÍ¼½¹”½µµ…¹ÁÉ½‘Õ•Ì½¹”…ÕÑ¡½É¥Ñ…Ñ¥Ù”(€Ñ¥½¸ÉÕ¸…¹½¹”™¥¹…°É•Á½ÉĞ¸(´‘€½É•±•…Í”Í¡¥À€ñÙ•ÉÍ¥½¸ø€ñÍ¡„ù€Ñ¼Ù…±¥‘…Ñ”Ñ¡”¹…µ•É•±•…Í”°‘•Á±½äÑ¡”(€É•ÅÕ¥É•½µÁ½¹•¹ÑÌ°Ù•É¥™äÁÉ½‘ÕÑ¥½¸¡•…±Ñ °…¹É•…Ñ”Ñ¡”¥µµÕÑ…‰±”Ñ…œ(€…¹¥Ñ!ÕˆI•±•…Í”¥¸½¹”ÉÕ¸¸(´A±…¸$…¹ÁÉ½‘ÕÑ¥½¸‘•Á±½åµ•¹ĞÍ½Á•Ì™É½´¡…¹•™¥±•Ì¸]•ˆµ½¹±äÁ…Ñ¡•Ì(€¹¼±½¹•ÈÉ•‰Õ¥±½ÈÉ•Á±…”¥É™±½Ü°½¹ÑÉ½°µ½¹±äÉ•±•…Í•Ì‘•Á±½ä¹¼ÉÕ¹Ñ¥µ”°(€…¹ÍÑ…±”ÁÕ±°µÉ•ÅÕ•ÍĞ$ÉÕ¹Ì…É”…¹•±±•…ÕÑ½µ…Ñ¥…±±ä¸(´5…­”]•ˆ…ÁÁ±äµ½‘”ÉÕ¸¥ÑÌ½İ¸‰Õ¥±°]É…¹±•È‘ÉäµÉÕ¸°…¹µ¥É…Ñ¥½¸±¥ÍÑ¥¹œ(€‰•™½É”µÕÑ…Ñ¥½¸°Í¼É½ÕÑ¥¹”±½ÜµÉ¥Í¬É•±•…Í•Ì‘¼¹½Ğ¹••„Í•Á…É…Ñ”ÁÉ•™±¥¡Ğ(€İ½É­™±½ÜÉÕ¸¸((ŒŒŒ¥á•((´I•µ½Ù”½Ù•É±…ÁÁ¥¹œ¥ÍÍÕ•}½µµ•¹Ñ€±¥ÍÑ•¹•ÉÌÑ¡…Ğµ…‘”€½É•±•…Í”Ñ…€±½½¬(€±¥­”„™…¥±•ÁÉ½‘ÕÑ¥½¸É•±•…Í”•Ù•¸İ¡•¸Ñ¡”‘•‘¥…Ñ•Ñ…œİ½É­™±½ÜÁ…ÍÍ•¸(´I•µ½Ù”Ñ¡”‘ÕÁ±¥…Ñ”€ÌÀµµ¥¹ÕÑ”$İ…¥Ğ™É½´¡…Ñ=ÁÌìÑ¡”•á…ĞµM!ÁÉ½‘ÕÑ¥½¸(€…Ñ”É•µ…¥¹ÌÑ¡”½¹±ä…ÕÑ¡½É¥Ñä™½ÈÅÕ•Õ•°ÍÕ•ÍÍ™Õ°°™…¥±•°½Èµ¥ÍÍ¥¹œ$¸(´I•©•Ğ„µ…¹Õ…±±ä¹…ÉÉ½İ•É•±•…Í”Í½Á”İ¡•¸¥Ğ½µ¥ÑÌ„‘•Ñ•Ñ•ÉÕ¹Ñ¥µ”(€½µÁ½¹•¹Ğ°…¹É•ÅÕ¥É”•áÁ±¥¥ĞÍ•¹‘•ÈõÑÉÕ•€…ÁÁÉ½Ù…°™½ÈÍ•¹‘•È‘•Á±½åµ•¹Ğ¸((ŒŒlÀ¸È¸Åt€´€ÈÀÈØ´Àà´ÈÌ((ŒŒŒ¥á•((´AÉ•Ù•¹ĞÑ¡”µ½‰¥±”‘…Í¡‰½…É™É½´•¹Ñ•É¥¹œ¥ÑÌ‘É…œ½ÈÉÕ‰‰•Èµ‰…¹ÍÑ…Ñ”İ¡•¸(€Ñ¡”Á½¥¹Ñ•Èµ½Ù•Ì™É½´Ñ¡”Ñ½ÀµÉ¥¡Ğ5½É”ÑÉ¥•È¥¹Ñ¼Ñ¡”½Á•¹•µ•¹Ô¸((ŒŒlÀ¸È¸Át€´€ÈÀÈØ´Àà´ÈÌ((ŒŒŒ‘‘•((´‘„¡•…‘•È½™™•”µÍÕÁÁ½ÉĞÍ¡••Ğİ¥Ñ Ñ¡”ÍÕÁÁ±¥•]•¡…ĞEH…¹„(€Í•ÉÙ•ÈµÑ¥µ••…ÍÑ•È•œÑ¡…Ğ¥ÍÍÕ•Ì½¹”€ÌÀµ‘…äÁÉ¥½É¥Ñä¥¹Ù¥Ñ”Á•ÈÙ•É¥™¥•(€•µ…¥°…™Ñ•ÈÑ¡”EH¡…ÌÉ•µ…¥¹•Ù¥Í¥‰±”™½È™¥Ù”Í•½¹‘Ì¸(´5½¹¥Ñ½ÈƒšÎošw–6k&çš?²¤Ñ•¹¹¥Ì…Ù…¥±…‰¥±¥Ñä½¸Ñ¡”Í…µ”A½ÍA…°‰½½­¥¹œA$…Ì(€Q=AL°ÁÕ‰±¥Í ½‰Í•ÉÙ…Ñ¥½¹ÌÑ¼Ñ¡”]•ˆ…ÁÀ°…¹Í•¹‰•ÍĞµ•™™½ÉĞ]•¡…Ğ…±•ÉÑÌ(€Ñ¼Ñ¡”Í¡…É•i…­Ì¡…ÑÉ½½µÌ¸(´‘ÁÉ½Ñ•Ñ•¥Ñ!Õˆİ½É­™±½İÌ™½È±½Õ‘™±…É”]½É­•È½Ä‘•Á±½åµ•¹Ğ°•á…ĞµM!(€]•ˆ¡•…±Ñ ¡•­Ì°…¹½¹”É•±•…Í”…Ñ”ÍÁ…¹¹¥¹œ]•ˆ°¥É™±½Ü°…¹Ñ¡”Í•¹‘•È¸(´9½Ñ¥™äi…­Í–’ŸšÊgšÊÏ¦fC–ºk–5€™½È…Í¡… I¥Ù•È™É•”µ½ÕÉĞ…Ù…¥±…‰¥±¥Ñä…™Ñ•È(€Ñ¡”]•ˆ½‰Í•ÉÙ…Ñ¥½¸…¹]•¡…Ğ‘•‘ÕÁ”…¡”…É”İÉ¥ÑÑ•¸¸(´ÁÁ•¹Ù•¹Õ”‰½½­¥¹œµ¥¹¤µÁÉ½É…´±¥¹­ÌÑ¼]•¡…Ğ…Ù…¥±…‰¥±¥Ñä…±•ÉÑÌ°…Ğµ½ÍĞ(€½¹”Á•È¡…Ğ…¹µ¥¹¤µÁÉ½É…´•Ù•ÉäÑİ¼¡½ÕÉÌ°İ¥Ñ M¡•¹é¡•¸	…ä…¹É•…Ñ•È(€	…äÉ•„Í¡…É¥¹œÑ¡”ƒšr«šv—šÆ…É¸((ŒŒŒ¡…¹•((´I•‰½½ĞÑ¡”i…­Ì]•¡…ĞÍ•¹‘•ÈÁ¡½¹”•Ù•ÉäÑİ¼‘…åÌ¥¹ÍÑ•…½˜‘…¥±ä°­••Á¥¹œ(€Ñ¡”€ÀÔèÀÀÍ¥„½M¡…¹¡…¤Í±½Ğ¸(´5½Ù”5äMÕ‰ÍÉ¥ÁÑ¥½¹Ì°UÍ•È½µµÕ¹¥Ñä°…¹‘µ¥¸¥¹Ñ¼…¸…•ÍÍ¥‰±”¡•…‘•È(€5½É”µ•¹Ô°…¹Í¡½ÉÑ•¸Ñ¡”½™™•”•¹ÑÉäÑ¼ƒŠsŠbT€æ”¯æŒä½œè€…â€ while retaining a
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
- Pin PostgreSQL and Redis by pulaable registry manifest digests instead of
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
