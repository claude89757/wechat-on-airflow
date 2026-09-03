# ADR 0012: Airflow-host notification core

- Status: Accepted
- Date: 2026-09-03
- Target version: 0.7.0

## Context

The Web subscription service originally owned verified-email subscriptions,
subscription matching, Tencent SES delivery, delivery reconciliation, and a D1
outbox. WeChat was sent by Airflow through the Android sender, but a ten-minute
D1-derived venue gate could suppress that channel. This made the D1 Free
row-read allowance a shared failure domain for the Web UI, subscriber email,
and WeChat admission.

The production Airflow host already runs PostgreSQL 17, Redis, Airflow 3.3,
and an immutable application image. Venue observations originate on that host.
Introducing additional Cloudflare storage layers would duplicate state without
removing the delivery dependency.

## Decision

The Airflow host owns the complete notification data plane.

- PostgreSQL is the authoritative store for identities, subscriptions,
  normalized venue observations, notification deduplication, email outboxes,
  provider delivery state, quotas, and bounded incident records.
- Application tables live in the dedicated `zacks` schema. They do not modify
  or depend on Airflow metadata tables and are excluded from Airflow metadata
  cleanup.
- A local `zacks-api` service provides the existing same-origin `/api/*`
  contract under the private `/zacks-api/api/*` origin path.
- A local `zacks-notification-worker` leases PostgreSQL outbox rows with
  `FOR UPDATE SKIP LOCKED`, sends Tencent SES mail, and reconciles provider
  delivery state.
- Airflow venue tasks post observations directly over the Compose network.
  The local API computes the venue subscription gate and returns the existing
  `wechatGate` response contract, so WeChat remains Airflow -> Android sender
  and no longer needs D1.
- Redis remains the Celery broker. It is optional for future wakeups and cache;
  no user, subscription, deduplication, or outbox fact depends on Redis.
- Airflow Variables remain configuration and cutover switches, not a business
  database.
- Cloudflare Worker serves static assets and acts as a stateless authenticated
  reverse proxy. Cloudflare Tunnel, DNS, TLS, WAF, and CDN remain the public
  edge. Worker cron performs no business work after cutover.
- D1 is retained read-only for a rollback window. It is not deleted by this
  release.

## Atomic cutover

The protected workflow executes one reversible sequence:

1. Deploy the protected migration endpoint and transfer existing Cloudflare
   runtime mail secrets in a host-generated RSA/AES envelope; plaintext never
   enters GitHub Actions or logs.
2. Deploy local API and worker with `ZACKS_DELIVERY_OWNER=cloudflare`.
3. Point Airflow observations to the local API in dual-forward mode.
4. Copy an initial D1 snapshot.
5. Quiesce D1 mutations, observation ingestion, and Worker cron.
6. Wait for in-flight legacy work, then copy a final incremental snapshot.
7. Set the local owner to `airflow_host`.
8. Switch the public Worker to the stateless host proxy.
9. Disable the migration and secret-envelope endpoints.
10. Verify exact-commit local and public health.

Only one owner can send subscriber mail at a time. Failure after quiesce invokes
the rollback path, restores the legacy observation URL and delivery owner, and
redeploys the Worker in legacy mode.

## Security

The host API is bound to loopback and exposed only through the existing
Cloudflare Tunnel path. Public requests must pass through the Worker, which
adds a shared edge header. Internal observations use the existing bearer token.
Secrets remain in Airflow Variables or root-owned runtime secret files. The
migration endpoint is bearer-protected, paged, no-store, and exists only to
support migration and rollback.

The D1 exporter decrypts recoverable invitation codes inside the Worker and
the host immediately re-encrypts them under host-owned key material. Migration
output is not logged and no persistent plaintext export is created by the
production workflow.

## Availability model

After cutover:

- Cloudflare or Tunnel outage affects Web access and subscription mutations,
  but existing observations, email, WeChat, retries, and reconciliation
  continue on the Airflow host.
- Redis outage does not lose notifications; the worker polls PostgreSQL.
- Tencent SES outage affects email only.
- Android sender outage affects WeChat only.
- PostgreSQL remains the shared durable dependency already required by Airflow.

## Consequences

The local PostgreSQL instance becomes the single business state authority.
This removes D1 usage from the hot path and makes Cloudflare spend independent
of polling frequency. It also requires application-schema backup, retention,
health checks, and exact-commit deployment to be part of the Airflow production
lifecycle.

ADR 0007 and ADR 0008 are superseded where they assign subscriber-email
ownership to Cloudflare. Their verification, deduplication, privacy, and
best-effort observation invariants remain in force under the host-owned
implementation.
