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

`SZW_API_AUTHORIZATION` stores the shared CRLand booking API JWT used by the
Shenzhen Bay outdoor area, Shenzhen Bay covered area, and Greater Bay Area
venue. The canonical form includes the `Wechat ` prefix; the adapter also
accepts the legacy raw JWT and adds the prefix in memory. Keep it only in
Airflow Variables; never place it in source, documentation, shell history, or
logs.

The venue adapter validates the JWT structure and `exp` claim before each request. A missing,
malformed, or expired value marks the Web observation unhealthy and fails the affected Airflow
task so its configured retry and failure visibility remain effective. Renewing the credential only
requires replacing this Variable; it does not require a code deployment.

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

## Web Subscription Publisher

All seven venue DAGs require:

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
