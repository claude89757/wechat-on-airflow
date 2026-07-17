# ADR 0003: Evidence-Based Repository Cleanup

- Status: Accepted
- Date: 2026-07-17

## Context

The repository contained archived experiments, duplicate helpers, paused DAGs,
legacy Appium notification paths, a retired Cloudflare gateway, and unrelated
infrastructure. Production registered nine active DAGs and no active component
referenced those paths.

## Decision

Keep only active DAGs, their statically and dynamically verified dependencies,
the standalone sender service, tests, and current operations material. Git
history remains the archive.

## Evidence

- Production DagBag inventory and pause state
- Recent production run history
- Import error inventory
- Static reference search
- Active component and configuration manifests
- Unit, contract, and Airflow 3 DagBag checks

Deletion is complete only after the full repository scan and verification gates
pass.
