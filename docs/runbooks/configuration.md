# Configuration Runbook

Airflow Variable names and shapes are authoritative in
`config/config-contracts.yaml`. Values are never stored in Git.

Before deployment, compare the required names with production using read-only
commands. Do not print values. Every venue must have its own email list;
configuration must not fall back to another venue.

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

Managed outbox and dedupe Variables are application state. Do not replace or
clear them during a normal deployment.

For the one-time Airflow 3 fresh start, managed state has an explicit
`fresh_start_policy`. Venue deduplication and proxy caches are preserved.
Fallback outboxes are reset in the new database and remain available in the
preserved Airflow 2 database and encrypted backup. The preparation and
verification scripts report names and counts only.

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
