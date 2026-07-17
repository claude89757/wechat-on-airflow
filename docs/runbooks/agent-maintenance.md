# Agent Maintenance

The repository, not chat history, is the persistent operational memory.

For every task:

1. Read `AGENTS.md`, component manifests, relevant ADRs, and the production
   baseline.
2. Inspect Git and production state without exposing secrets.
3. Classify the operation by the risk rules in `AGENTS.md`.
4. Add a failing test or an explicit machine-verifiable acceptance check.
5. Make the smallest complete change.
6. Run `make verify` and any component-specific integration check.
7. Update contracts, runbooks, ADRs, and the changelog when facts change.
8. Commit and push before deployment.
9. Compare pre- and post-deploy health output.
10. Observe the required schedule cycles and record residual risk.

Do not create platform-specific instruction files containing independent rules.
They may only point to `AGENTS.md`.
