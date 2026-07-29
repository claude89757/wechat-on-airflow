# Release Paths

Read `docs/runbooks/production-deployment.md`,
`docs/runbooks/webapp-deployment.md`, and `docs/runbooks/rollback.md` before
applying production changes.

## Common Gate

1. Record pre-change health and current deployed identities.
2. Run `make verify`, `make deploy-check`, and `make rollback-check`.
3. Review the diff for secrets and unrelated changes.
4. Commit and push the exact intended state.
5. Require GitHub CI success.
6. Use the full pushed SHA in every production apply.

For a named release, update `CHANGELOG.md` and the semantic version in the
release commit. Create the immutable Git tag only after the production
observation window succeeds.

## Airflow Application

Run:

```text
make deploy DEPLOY_ARGS="--target-commit <full-sha>"
make deploy DEPLOY_ARGS="--apply --target-commit <full-sha>"
make production-health
```

The apply command must drain active tasks, preserve DAG pause state, replace
only application services, retain database/broker/log volumes, and restore the
previous state automatically if startup fails.

Observe the natural schedule-cycle count in `config/runtime-target.yaml`.

## Cloudflare Web Application

Run the web checks included by `make verify`. Apply D1 migrations only when a
new migration exists and review it before remote apply. Deploy with:

```text
cd webapp && npm run cf:deploy
```

Verify:

- `/api/healthz` reports healthy;
- unauthenticated `/api/bootstrap` exposes five venues and no email address;
- unauthenticated observation writes return HTTP 401;
- natural venue runs refresh inspection timestamps;
- mobile subscription creation and keyboard behavior pass browser checks.

Do not send a verification email or create production data without approval.
Because production identity is repository-wide, deploy the same pushed commit
to Airflow after a web-only code release unless the documented production
strategy changes.

## WeChat Sender

Use the Android-host installer in preflight mode, then apply:

```text
sudo scripts/install_wechat_sender.sh --target-commit <full-sha>
sudo scripts/install_wechat_sender.sh --apply --target-commit <full-sha>
```

Verify systemd is enabled and active and both `/healthz` and `/readyz` succeed.
Do not use the send endpoint as a smoke test. A real send requires explicit
approval.

## Configuration

Compare Variable names, types, counts, required fields, and protected hashes.
Never print values. Airflow should retain only the Web observation
configuration required to publish venue data; the observation token must equal
the Worker push token without exposing either value. Keep subscriber email
credentials and delivery configuration in the Worker, not Airflow.

Configuration that changes runtime behavior must follow the exact-commit
Airflow deployment path and production health checks.

## Cloudflare Tunnel

Keep `airflow.claude89757.cc` routed through the host-managed
`cloudflared.service` to loopback `127.0.0.1:8080`. Verify the public UI,
public health endpoint, service enabled/active state, and private Execution API
probe. Prefer the supported Cloudflare CLI and host service management over
browser configuration.

## Rollback

For application rollback, restore the previously recorded pushed commit and
pinned image without replacing the Airflow 3 database. Run
`make rollback-check` before apply and `make production-health` afterward.

Database restore, Airflow major-version migration, and metadata deletion are
separate high-risk operations that require explicit approval.
