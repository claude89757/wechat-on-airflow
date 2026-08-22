# ADR 0006: GitHub-Only Delivery Control Plane

## Status

Accepted on 2026-08-22.

## Context

Airflow and the Android WeChat sender already used GitHub Environment SSH
identities, but Web/D1 deployment still required workstation Wrangler login.
Production health derived identity from local Git `HEAD`, and application
deploy/rollback preflights incorrectly required a workstation database backup.
This prevented another device or coding agent from operating the project with
only GitHub authentication.

## Decision

GitHub Actions is the authoritative development-to-production control plane.

- `CI / verify` is the required check for an exact release commit on `main`.
- `production-release.yml` gates and sequences Web/D1, Airflow, and sender
  component workflows.
- Cloudflare and SSH deployment identities live only in the protected GitHub
  `production` Environment.
- Workstation commands may dispatch workflows using GitHub authentication, but
  they do not read production credentials or define production identity.
- Production health receives an explicit full SHA from the workflow.
- Normal application rollback does not require a database backup because it
  does not replace or migrate the database.
- Runtime credentials remain in platform-native stores and are not copied into
  GitHub or downloaded to developer machines.

## Consequences

A workstation can be rebuilt with only GitHub authentication. Cloudflare
deployments and remote verification are auditable GitHub jobs. The deployment
API token must be scoped to the target account, D1 database, Worker, and zone,
and rotated in the GitHub Environment when needed.

D1 migrations remain forward-only release inputs and must be backward
compatible with the previous application release. Database restore, metadata
cleanup, runtime-secret rotation, and real notifications remain separately
approved high-risk operations.
