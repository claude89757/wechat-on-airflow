# Diagnosis Matrix

Start with read-only evidence. Preserve failure times, affected DAGs or chats,
service health, commit identity, and whether counts are still increasing.
Never inspect or print protected payload values.

| Symptom | First checks | Ownership boundary | Required guardrail |
| --- | --- | --- | --- |
| DAG missing or import failure | `make test-dags`; manifest file, DAG ID, task IDs, traceback | `dags/`, image build, dependency packaging | Do not mutate `sys.path`; keep reusable code outside `dags/` |
| Venue DAG failure | Recent runs, booking API response class, proxy cache, timeout, parser contract | `src/wechat_airflow/venues/` or external booking API | Keep delivery failures from failing the DAG |
| Execution API failure | `make production-health`; public root, private `/execution/`, proxy headers | Airflow API server, Compose config, Cloudflare Tunnel | Keep public hostname root and private route paired |
| Subscriber email delay or failure | Worker health, observation freshness, subscription validity, D1 outbox status and latest attempt, SES result code | Cloudflare Worker/D1 or Tencent SES | Do not add an Airflow email path; do not expose recipients or send a live test without approval |
| WeChat delay or failure | Sender `/healthz` and `/readyz`, systemd enabled/active, `device_busy`, Appium, ADB, latest outbox time | Android-host sender, Appium, device, WeChat UI | One process per device; no live send without approval |
| Duplicate notification | Stop manual retries; inspect dedupe write order, overlapping runs, event identity, outbox identity | Venue cache or D1 uniqueness contract | Preserve cache/outbox evidence before changes |
| Web subscription failure | `/api/healthz`, `/api/bootstrap`, D1 migrations, Worker cron/outbox, Airflow observation publisher | `webapp/`, Cloudflare Worker/D1, observation client | No fake production subscription or slot; no email address in bootstrap |
| Stale web dashboard | Natural venue runs, observation API 401 without token, publisher timeout and latest inspection time | Airflow observation publisher or Worker ingestion | Publishing remains best effort and cannot fail a DAG |
| Phone reboot failure | Variable shape by field name, pinned host-key validity, SSH, `adb devices`, target serial | Maintenance DAG, Android host, ADB | Never fall back to an unrelated device |
| Proxy refresh failure | Source-specific failure, bounded timeout, last successful publication, GitHub API result | Proxy adapter or external source | One failed source must not abort all candidates |
| High disk or metadata growth | `make production-health`, free-space floor, relation sizes, `make db-cleanup-check` | Deployment manager and PostgreSQL | Cleanup apply requires approval and exact cutoff; never schedule it |
| Version mismatch | Local/upstream/production commits, image tag, Worker version, sender deployed commit | Release process | Deploy the exact pushed SHA or intentionally roll back |

## Interpret Outboxes

Distinguish historical retained records from an active incident by comparing
the latest failure timestamp and count across the observation window. Do not
make health green by clearing or replaying records.

The Airflow WeChat fallback outbox and retired email outbox are incident
evidence and are never automatically replayed. The Cloudflare subscriber-email
outbox is a separate, bounded retry mechanism owned by the Worker.

## Close An Incident

Require a root cause, a regression check or durable contract update, successful
component health, and a natural observation window. A process restart may
restore service but does not close the incident by itself.
