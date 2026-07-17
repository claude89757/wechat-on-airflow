# Rollback

## Airflow 3 Application Rollback

1. Stop affected application services.
2. Check out the previously recorded pushed Airflow 3 commit.
3. Resolve and validate its Compose configuration.
4. Load or build its pinned image.
5. Start the affected services.
6. Run the production health check and compare with the pre-deploy record.

Do not replace the Airflow 3 database for an application-only rollback.

## Airflow 2 Cutover Rollback

The fresh-start design keeps the complete Airflow 2 database and runtime paths
unchanged. No database restore or downgrade is required:

1. Pause Airflow 3 DAGs and wait for active tasks to finish when possible.
2. Stop and remove Airflow 3 containers without deleting bind-mounted data.
3. Preserve failed Airflow 3 logs, configuration counts, and health output.
4. Check out the recorded Airflow 2 commit.
5. Restore the mode-600 Airflow 2 environment file.
6. Validate that Compose resolves to the original database, Redis, and log paths.
7. Start the Airflow 2 PostgreSQL and Redis services, then its application services.
8. Verify Airflow version, active DAGs, configuration names, and service health.
9. Resume Airflow 2 schedules.

Airflow 3 run history is not copied back. Keep its named volumes for
incident analysis until the rollback is closed. Never run an Airflow 2 process
against the Airflow 3 database or an Airflow 3 process against the preserved
Airflow 2 database.

## Backup Restore

The encrypted Airflow 2 database backup remains a last-resort recovery input if
the preserved bind-mounted database is damaged. Restoring or replacing a
production database remains a separate, explicitly approved operation.

Run `make rollback-check` before any production change.
