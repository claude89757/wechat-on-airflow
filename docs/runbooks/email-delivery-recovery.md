# Recover an existing email consumer after a paused release

Use this incident procedure when a partially completed release has paused the
existing Host Core email consumer, while the API, PostgreSQL, verified migration
checkpoint, SES configuration and ongoing venue observations remain available.
It restores the existing email channel without deploying another runtime or
making the incomplete release pass acceptance.

The owner must authorize email recovery. Run through the existing Issue #39
owner-only control router and the protected `production` Environment. The
workflow shares the Host Core concurrency group. Application credentials stay
on the production host; the runner receives only its existing scoped SSH
identity. Do not use a workstation SSH connection, copy secrets, or manufacture
a verification email or court observation.

## Two exact commits

The operation takes two full, explicit 40-character SHAs:

- **Operations commit:** the current `main` commit containing the recovery
  implementation, with a successful exact-commit `CI / verify` check.
- **Existing runtime commit:** the already deployed Host Core/mail-consumer
  commit. It must be on `main` with successful exact-commit CI, and must match
  the existing host worktree, API, email consumer and PostgreSQL control state.

The workflow checks both commits before remote access. The operation checks
the actual production identities again and fails on drift. It never checks
out the operations commit on the production host, builds an image, recreates a
container, updates the edge or changes a deployed component's commit.

## Commands

Post one command at a time on Issue #39 as the repository owner:

```text
/ops email-preflight <operations-sha> <existing-runtime-sha>
/ops email-resume <operations-sha> <existing-runtime-sha>
/ops email-status <operations-sha> <existing-runtime-sha>
```

`Production Email Recovery` also has an owner-only manual dispatch with the
same explicit inputs and gates. It accepts no shell command, bypass flag,
recipient, group or alternate runtime selector.

### Preflight

`email-preflight` is read-only. Review the complete bounded report before
resuming. It must establish exact existing identities, valid prior activation
and migration reconciliation, working database/API and SES configuration,
fresh observations, and the existing email container. WeChat must be disabled
and its consumer stopped. A missing checkpoint, a changed runtime, uncertain
ownership or a running WeChat consumer is a failed precondition, not a reason
to loosen a guard.

### Resume

`email-resume` repeats preflight immediately before mutation. It starts the
existing email consumer and restores email ownership through the existing
PostgreSQL delivery fence. Only normal eligible subscription and system email
work can then proceed. WeChat stays disabled and its consumer remains stopped;
the existing group-routing configuration is not edited.

No queue, recipient, subscription, deduplication identity, delivery receipt or
unknown-submission record is cleared or replayed. The worker's existing expiry,
subscription validity and fresh-availability checks remain in force. Old
reminders and expired verification codes do not become a recovery broadcast.
The operation must preserve production identities and stop safely if its
postconditions fail.

### Verify and observe

The workflow records a separate read-only status after a successful resume.
Use `email-status` again to inspect the consumer heartbeat, enabled ownership,
queue progression and natural Tencent SES submission/delivery receipts. Reports
contain counts, timestamps and commits rather than addresses, payloads or
credentials. A running worker or HTTP 200 is not proof of provider delivery;
absence of a new eligible event is not itself a failed send. Do not generate a
real test message to make a receipt appear.

If the command result is lost or uncertain, inspect `email-status` before
considering another resume. Do not blindly replay an uncertain operation.

## Keep the release and WeChat gates intact

This is email incident recovery only. It does not set release acceptance,
enable WeChat, change venue schedules, restart Airflow, deploy Pi/Sender/edge,
rotate credentials, reimport D1, restore a database, or create a release tag.
All existing full-release requirements remain, including exact component
identities, all 27 venues and their natural cycles, the transaction-rollback
API probe, and independent natural email/WeChat receipts.

Report any incomplete Baoan/Pi collection or older Sender deployment separately.
Those components still require their protected release path. Never describe a
recovered email channel as a completed 0.9.0 rollout or all-channel recovery.
