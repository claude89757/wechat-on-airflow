# Configuration Runbook

Airflow Variable names and shapes are authoritative in
`config/config-contracts.yaml`. Values are never stored in Git.

Before deployment, compare the required names with production using read-only
commands. Do not print values. Every venue must have its own email list;
configuration must not fall back to another venue.

When adding a Variable:

1. Add its type, sensitivity, ownership, and consumers to the contract.
2. Add it to each component in `config/active-components.yaml`.
3. Add missing, malformed, and valid-value tests.
4. Configure production without logging the value.
5. Run `make production-health` and verify only name-level completeness.

Managed outbox and dedupe Variables are application state. Do not replace or
clear them during a normal deployment.

Fallback outboxes are incident records, not retry queues. After fixing a
channel, verify that new records stop accumulating. Archiving or clearing old
records requires an explicit, no-replay maintenance step; never resend them in
bulk.
