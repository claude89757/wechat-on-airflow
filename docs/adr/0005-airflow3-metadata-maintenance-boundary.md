# ADR 0005: Airflow 3 Metadata Maintenance Boundary

- Status: Accepted
- Date: 2026-07-19

## Context

Airflow 3 isolates task subprocesses from direct metadata database access.
The legacy `airflow_db_cleanup` DAG launched `airflow db clean` from a
`BashOperator`. Two natural production runs failed while the CLI initialized
because the task subprocess did not receive a usable metadata database URL.
Both failures occurred before any deletion.

Metadata cleanup is administrative deployment maintenance, not venue workflow
business logic. Keeping it in the DagBag also prevented the active-DAG health
contract from becoming green even though all business workflows succeeded.

## Decision

Remove `airflow_db_cleanup` from the production DagBag. Run metadata cleanup
through `scripts/airflow_db_cleanup.py` from the deployment manager:

- default mode performs `airflow db clean --dry-run`;
- production and local Git commits must match;
- apply mode requires a clean pushed commit, a verified encrypted backup, and
  an explicit `--confirm-delete-before YYYY-MM-DD`;
- cleanup is not automatically scheduled;
- agents must obtain human approval before apply mode.

The command executes the supported Airflow CLI in the API Server container,
where the administrative database configuration is available.

## Consequences

All retained DAGs stay within the Airflow 3 Task SDK boundary. Database
maintenance remains reproducible and machine-verifiable without granting DAG
tasks metadata credentials. Cleanup will not occur automatically until a human
approves a retention cutoff and apply invocation.
