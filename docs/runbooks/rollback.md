# Rollback

Airflow 3 metadata changes are not rolled back in place. Restore a verified
pre-migration backup into an empty PostgreSQL database and redeploy the recorded
Airflow 2 commit and images.

## Application-Only Rollback

1. Stop affected application services.
2. Check out the previously recorded pushed commit.
3. Resolve and validate its Compose configuration.
4. Rebuild or pull its pinned image.
5. Start the affected services.
6. Run the production health check and compare with the pre-deploy record.

## Database Restore Rollback

1. Stop every Airflow application component.
2. Preserve failed migration logs and database metadata.
3. Move the failed database aside; do not restore over it.
4. Create an empty PostgreSQL database.
5. Decrypt and restore the verified custom-format archive without writing the
   key or plaintext archive to the repository.
6. Deploy the recorded Airflow 2 commit and images.
7. Start services and verify DAG history, Variables, Connections, Pools, and
   users by count and name only.
8. Resume schedules only after health checks pass.

Run `make rollback-check` before any production change. Database replacement
requires explicit human approval.
