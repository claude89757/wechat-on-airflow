# Release Paths

Read `docs/release-strategy.md`, `docs/runbooks/production-deployment.md`,
`docs/runbooks/webapp-deployment.md`, and `docs/runbooks/rollback.md` before
applying production changes.

## Common Gate

1. Record pre-change health and current deployed component identities.
2. Run credential-free checks and review the diff for secrets.
3. Commit and merge the exact intended state through a pull request.
4. Require GitHub `CI / verify` to succeed for the exact merge SHA.
5. Use the single issue-39 `Production Control` router; component workflows must
   not listen to `issue_comment` directly.
6. For a routine named release, run:

```text
/release ship <version> <full-sha> scope=auto sender=false
```

The ship workflow validates version/changelog consistency before mutation,
resolves the component scope, applies and health-checks those components, and
only then creates the immutable tag and GitHub Release.

Use standalone `preflight`, `apply`, or `tag` commands only for unusual
migrations, incident recovery, or resuming a partially completed operation.
The production release gate is the only CI waiter; do not add another polling
loop to ChatOps.

## Component Scope

`scripts/release_plan.py` compares the target with the previous semantic release.
`scope=auto` is preferred:

- Web source, Worker, migration, or asset changes deploy `webapp`;
- DAG, Airflow runtime/configuration, or image changes deploy `airflow`;
- sender runtime changes deploy `sender` and require `sender=true`;
- workflows, release tooling, docs, tests, and version-only metadata resolve to
  `control` and deploy no runtime.

A manual scope may broaden the plan but must never omit a detected runtime
component. Unknown paths fail conservatively into all component checks.

## Airflow Application

When Airflow is in scope, apply must drain active tasks, preserve DAG pause
state, replace only application services, retain database/broker/log volumes,
and treat deployment plus full production health as one transaction. On health
failure it restores the previous commit/image/configuration, verifies the
restored state, and still fails the attempted release.

Observe the natural schedule-cycle count in `config/runtime-target.yaml`.

## Cloudflare Web Application

Web apply performs its own build, Wrangler dry-run, D1 migration listing,
migration apply, deployment, and exact-commit health check. A Web-only patch
must not restart Airflow merely to keep a repository-wide SHA fiction;
component identities are recorded independently.

Verify:

- `/api/healthz` reports healthy and the expected Web deployment commit;
- unauthenticated `/api/bootstrap` exposes fourteen venues and no email address;
- unauthenticated observation writes return HTTP 401;
- mobile subscription and critical interaction tests pass.

Never use local Wrangler credentials for production deployment.

## WeChat Sender

Sender deployment remains separately approved. `scope=auto` will reject a
sender change unless the command includes `sender=true`. Verify systemd is
enabled and active and both `/healthz` and `/readyz` succeed. Do not use the
send endpoint as a smoke test; a real send requires explicit approval.

## Configuration

Compare Variable names, types, counts, required fields, and protected hashes.
Never print values. Keep subscriber email credentials and delivery
configuration in the Worker, not Airflow. Configuration that changes Airflow
runtime behavior must enter the Airflow component scope and full health gate.

## Cloudflare Tunnel

Keep `airflow.claude89757.cc` routed through the host-managed
`cloudflared.service` to loopback `127.0.0.1:8080`. Verify the public UI,
public health endpoint, service enabled/active state, and private Execution API
probe.

## Rollback

The release planner is for forward release diffs. For a component-only rollback,
invoke the matching protected reusable workflow directly with the prior recorded
component commit: `production-webapp.yml`, `production-airflow.yml`, or
`production-wechat-sender.yml`. Use the full release path only for a reviewed
repository-wide rollback whose detected scope intentionally includes all
components. Database restore, Airflow major-version migration, and metadata
deletion are separate high-risk operations requiring explicit approval.
