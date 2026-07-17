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
2. Run `make verify`, `make deploy-check`, and `make rollback-check`.
3. Push the exact commit and require CI to pass.
4. Build and record the immutable image identifier.
5. Deploy only after the production health and strategy-specific storage floor
   in `config/runtime-target.yaml` pass.
6. Run post-deploy health checks across multiple complete schedule cycles.
7. Tag the verified commit after the production observation window succeeds.

Rollback restores the previous application commit when the metadata schema is
unchanged. The Airflow 3 fresh-start rollback switches back to the preserved
Airflow 2 commit, environment, and data paths without changing either database.
