# Configuration Runbook

Airflow Variable names and shapes are authoritative in
`config/config-contracts.yaml`. Values are never stored in Git.

Before deployment, compare the required names with production using read-only
commands. Do not print values. Airflow must not contain or consume fixed venue
email recipient lists; subscriber email configuration belongs to Cloudflare.

`AIRFLOW_EXECUTION_API_SERVER_URL` is a non-secret runtime setting. It must use
the internal API Server host and include the path component of
`AIRFLOW_BASE_URL` before `/execution/`. The production health check validates
the route without credentials and without starting a task.

When adding a Variable:

1. Add its type, sensitivity, ownership, and consumers to the contract.
2. Add it to each component in `config/active-components.yaml`.
3. Add missing, malformed, and valid-value tests.
4. Configure production without logging the value.
5. Run `make production-health` and verify only name-level completeness.

## CRLand Booking Authorization

`SZW_API_AUTHORIZATIONS` is a sensitive JSON list of exactly three CRLand
booking API JWTs for distinct accounts. Shenzhen Bay outdoor, Shenzhen Bay
covered, and Greater Bay Area share the pool. Each canonical entry includes
the `Wechat ` prefix; raw JWT entries are normalized in memory. The runtime
reads only Airflow Variables. Stage an explicitly authorized replacement pool
in the GitHub `production` Environment secret `SZW_API_AUTHORIZATIONS`; never
place values in source, documentation, workflow inputs, issue comments, shell
history, or logs.

After the exact main commit passes `CI / verify`, dispatch the protected
`Production Airflow` workflow with operation `szw_authorization_sync` and that
full `target_commit`. The operation checks every JWT's structure, expiry, and
distinct `sub`/`openid` identity without reporting claim values. It streams the
pool over pinned SSH stdin and performs nine read-only matrix queries for
tomorrow in Asia/Shanghai: every account against Shenzhen Bay outdoor,
Shenzhen Bay covered, and Greater Bay Area. Each query has a bounded timeout;
queries are spaced by two seconds and never follow redirects or environment
proxies. No observation, notification, booking, or Airflow Variable is written
by these probes.

Only after all nine API responses succeed does the operation replace the pool
and set the legacy `SZW_API_AUTHORIZATION` to its first account in one database
transaction. It compares both stored values before committing, so a failed
probe preserves the old values and a failed readback rolls back both writes.
The legacy value keeps the previous runtime and a reviewed rollback usable
during the pool deployment. Logs contain only fixed error categories, account
indices, and confirmation counts, never token claims, response bodies, or
credential values. A transport timeout has an uncertain completion state and
requires checking the protected result before claiming success. Verify three
subsequent natural polling cycles within the active window for both venue
DAGs; do not trigger synthetic email or WeChat notifications.

### Polling window and account rotation

Both venue DAGs inspect today and the next two calendar days using
`check_and_notify_day_0` through `check_and_notify_day_2`. Shenzhen Bay's
fourth-day task was retired by explicit user request on 2026-10-20. Its
historical task/run records remain; the current task manifest and bounded
diagnosis require only the three retained dates.

Shenzhen Bay uses a two-minute interval and Greater Bay Area a three-minute
interval. Routine CRLand queries run only from 08:00 inclusive to 21:00
exclusive in Asia/Shanghai. Booking dates and window checks use that timezone
independently of the host timezone. Airflow retains the interval schedules
outside this window: an intentional-idle round publishes an internal healthy
empty observation to clear stale availability and refresh status, without
querying CRLand or attempting reminders. Check actual local time at task entry,
before each upstream attempt, and before final publication. If the window
closes during collection, discard partial results and publish the idle empty
observation once.

Each venue rotates through the same three-account pool by its own scheduled
round. Selection is `floor(scheduled_timestamp / (interval_minutes * 60)) % 3`,
using the Airflow data interval end, then logical date when unavailable, then
captured actual time for a direct call. It uses no mutable counter or daily
reset. During uninterrupted polling, each account is selected every six
minutes for Shenzhen Bay and every nine minutes for Greater Bay Area. Every
date task in the same venue round selects the same account; it stays fixed
across booking areas and request retries. Expiry is checked against actual
execution time.

The legacy single Variable is a compatibility fallback only when the pool is
absent. An invalid, incomplete, duplicate-account, or expired configured pool
fails closed instead of silently concentrating requests on one account.
Credential renewal uses the protected sync operation and does not require a
runtime code deployment after the pool-capable release is installed.

The Greater Bay Area API permits today plus the next two calendar days. Its DAG
therefore runs `day_0` through `day_2`; longer-lived Web subscriptions continue
matching as later dates enter that rolling upstream window.

## NSWTT Free-Court Authorization

`NSWTT_API_CONFIG` is a sensitive JSON object used only by the Dashah River
free-court DAG. It requires `app_version` and `cookie`; `page_path`,
`page_uuid`, `project_id`, `base_url`, and `timeout_seconds` are bounded
optional fields. Never log or commit its value.

The canonical value is stored in the protected GitHub `production`
Environment as the `NSWTT_API_CONFIG` secret. Rotate it there, then run the
`nswtt_config_sync` protected Airflow operation. The operation validates the
shape and streams the value directly into the Airflow API Server container;
developer devices do not retrieve the production value.

The adapter first selects calendar rows whose `status`, `openstatus`, and
`issale` are all `200`. It then requires a non-empty free `placelist` for each
selected date. A calendar date with no free courts is a healthy empty result,
not an email event. Only zero-price slices with `status=200` are published.

## PosPal Venue Booking

TOPS, 泛思博特福中福, PICKLE POP宝安, FFTENNIS前海国际网球中心, and the
fifteen Fansibote chain courts (深云, 蛇口, 新安, 正中, 安托山, 棕榈泉,
观湖, 坂田, 沙河, 保税, 南油, 新桥, 壹方城, 麒麟, 茅洲河) query the same
public PosPal appointment service with a store ID and project UID that live in
the adapter. No login token, cookie, openid, or session key is required.
FFTENNIS uses the mini-program's public request headers and performs a
TLS-verified direct request first, falling back to the shared HTTPS proxy pool
only on failure. It publishes only courts 1–6 and drops non-standard singles
and ball-machine rooms. The shared chain-court adapter keeps only standard
tennis / 风雨场 names and drops 小场, 匹克, 练习, 非标, and 发球机 courts. A
successful V2 payload with zero bookable rooms is a healthy empty result.
PICKLE POP宝安 publishes tennis courts only and drops pickleball rooms. WeChat
alerts use the shared `SZ_TENNIS_CHATROOMS` list. Application-managed
`TOPS_PROXY_CACHE`, `FSB_PROXY_CACHE`, `FFT_PROXY_CACHE`, `PPBA_PROXY_CACHE`,
notification baseline, and venue dedupe caches are created on first successful
use.

## Raspberry Pi YDMap Scraper

`PI_DEVICE_SSH` is a sensitive JSON object shared by the Dashah International
Tennis Center and Bao'an Tennis Center DAGs. It requires `host`, `port`,
`username`, `password`, and `host_key_sha256`. Optional `scrape_url` defaults to
`http://127.0.0.1:8788/inspect`. Never log or commit its value.

The GitHub `production` Environment stores the scrape-host login as
`PI_DEVICE_SSH_*` names. Rotate them there, then run the protected
`pi_device_ssh_sync` Airflow operation. The operation validates the shape and
streams the value directly into the Airflow API Server container; developer
devices do not retrieve the production value. Those secrets are not an Airflow
runtime path and must not be copied onto developer machines. The workstation
`.env` is a local convenience file, not production identity.

The scrape service listens only on the Pi loopback interface. Airflow reaches
it by SSH and a localhost `curl`. Do not publish port `8788`. The Dashah watcher
collects today plus four later calendar days; the Bao'an watcher requests
`venue=baoti`, which scrapes the outdoor, indoor and wind-rain groups of
`bawtt.ydmap.cn` and returns the two released calendar days. Both publish raw
slots to the Web app before any WeChat enqueue, and every request is serialized
by the service's single-scrape lock.

## Web Subscription Publisher

All nine venue DAGs require:

- `WEBAPP_OBSERVATION_API_URL`: the Worker ingestion endpoint;
- `WEBAPP_OBSERVATION_API_TOKEN`: a random shared secret stored only in
  Airflow and Cloudflare;
- `WEBAPP_OBSERVATION_TIMEOUT_SECONDS`: bounded request timeout, normally `5`.

The publisher runs before WeChat handling and never raises to the DAG. This
ordering keeps Web subscription email independent from Android device health.
Do not reuse a public API credential, Cloudflare API token, or Airflow login
credential as the observation token.

Managed outbox and dedupe Variables are application state. Do not replace or
clear them during a normal deployment.

For the one-time Airflow 3 fresh start, managed state has an explicit
`fresh_start_policy`. Venue deduplication and proxy caches are preserved.
The active WeChat fallback outbox is reset in the new database and remains
available in the preserved Airflow 2 database and encrypted backup. The
retired Airflow email outbox remains historical incident evidence only. The
preparation and verification scripts report names and counts only.

Fallback outboxes are incident records, not retry queues. After fixing a
channel, verify that new records stop accumulating. Archiving or clearing old
records requires an explicit, no-replay maintenance step; never resend them in
bulk.

## Android Host Key

Each `APPIUM_SERVER_LIST` item's `login_info` must include an OpenSSH SHA-256
host-key fingerprint in `host_key_sha256`, using the `SHA256:<base64>` format.
Verify a changed fingerprint through a trusted channel before updating the
Variable. The runtime rejects missing or mismatched fingerprints and disables
the legacy `ssh-rsa` SHA-1 algorithm; never replace this with automatic host-key
acceptance.
