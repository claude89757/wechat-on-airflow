# Release Strategy

## Versioning

The project follows Semantic Versioning. While the package remains below 1.0:

- minor releases may change documented deployment or configuration contracts;
- patch releases preserve DAG IDs, notification semantics, and configuration schemas;
- incompatible DAG ID or metadata ownership changes require an explicit migration plan.

Every release updates `CHANGELOG.md` and creates an immutable Git tag. Production
deployments use a pushed commit and pinned image, never a mutable branch alone.

## Supported Runtime

| Component | Supported version |
| --- | --- |
| Apache Airflow | 3.3.0 |
| Python | 3.12 |
| PostgreSQL | 17 |
| Celery provider | 3.21.0 |
| FAB provider | 3.7.1 |
| Standard provider | 1.15.0 |

Dependency updates must pass `make verify`, the migration rehearsal when metadata
compatibility changes, and the production deployment preflight. Airflow major or
metadata schema changes require explicit human approval before production apply.

## Release Gate

1. Update tests, contracts, documentation, and changelog together.
2. Run local checks without production credentials, then push a pull request.
3. Require the GitHub `CI / verify` check for the exact commit to pass.
4. Dispatch `production-release.yml` in `preflight` mode. The gate rejects a
   commit outside `main` or without the successful required check.
5. Dispatch the same SHA in `apply` mode through the protected `production`
   Environment. GitHub deploys D1/Worker, Airflow, and optionally the sender.
6. Require each component to report the exact release SHA and pass its read-only
   probes. Observe multiple complete schedule cycles.
7. Tag the verified commit after the production observation window succeeds.

Rollback restores the previous application commit when the metadata schema is
unchanged. The Airflow 3 fresh-start rollback switches back to the preserved
Airflow 2 commit, environment, and data paths without changing either database.
