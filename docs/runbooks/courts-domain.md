# Courts custom domain

`courts.zacks.vision` is the primary public subscription site. The existing
`zacks.claude89757.cc` remains on the same `zacks-tennis-alerts` Worker with no
forced redirect. Wrangler custom-domain routes provision DNS and TLS through
the protected `production-webapp.yml` workflow. Do not use workstation Wrangler
or create a separate Worker. The Zacks Vision apex is outside this change.

The UI is named **Zacks 场地**, with subtitle **网球空场提醒**. Desktop navigation
and the mobile More menu link directly to `https://zacks.vision`, labelled
**视频分析 · Zacks Vision**. Links use `noopener noreferrer` and contain no
identity, verification receipt, query string or fragment.

Browser verification receipts remain origin-local in
`zacks-tennis-verified-emails-v1`. A visitor on the new origin must verify their
email again. Existing subscriptions remain in PostgreSQL and continue to run;
verification on the new domain retrieves the same backend identity. No receipt
migration, shared cookie, SSO or session transfer is introduced.

## Release and recovery

This is an isolated Web rollout, using the supported protected component
workflow after PR review and exact merge-SHA CI. Run `deploy_preflight`, then
`deploy_apply`, then `health` with that SHA. The component workflow validates main ancestry;
it does not enforce CI itself. Record the successful `CI / verify` check for the
exact merge SHA independently before dispatching preflight or apply. The public-hostname fields in
`config/runtime-target.yaml` are Web health targets, not Airflow runtime changes.
The generic release planner treats the entire config directory as Airflow;
therefore do not use a named whole-platform ship for this domain-only change.
Do not redeploy host services or Sender merely to align their commits.

Pre-change recovery identity: `9cca72d73eb05c502446bd1d947c4307d7f73f35`.
The pre-change Worker deployment is `710523e8-d734-419c-9bdd-c73eb7cfa109`,
version `ec630074-80c0-4b70-8047-a8798ab84a3f` at 100%; its only custom domain is
`zacks.claude89757.cc`. Reconfirm this route and version inventory before apply. There are no schema, secret, origin, security, notification or subscription
changes. Database restore is neither needed nor permitted. If the rollout fails,
retain evidence and use the protected Web component workflow with the prior
verified SHA, or a reviewed forward fix. Restoring that old route config removes
the new hostname and retains the legacy hostname; assess that explicit impact
before recovery. Never activate the legacy D1 backend.

`webapp_production_health.py` checks both primary and additional public URLs.
`webapp/qa/public-acceptance.mjs` checks both domains at desktop, mobile and small
screen sizes, their exact edge SHA, host health, no redirect, links, assets and
subscription verification controls. It blocks all public writes, including injected Cloudflare `/cdn-cgi/rum` POST
beacons. Only exact same-origin RUM beacons are counted separately as blocked
telemetry; every other write attempt still fails acceptance. Mocked browser
tests cover verification/create/cancel. Production checks never submit a code,
create a synthetic subscription or send a real test notification. Natural
DAG and sender health is observed through `production-airflow.yml` using the
unchanged host SHA. The existing host-core public check assumes edge and host
have equal SHAs (`pureEdgeExactCommit`), and its workflow requires current main;
it is not a valid whole-report pass for this isolated Web deployment. Keep that
limitation explicit and record component identities separately. Never weaken
exact identity checks to manufacture a passing report.

New hostname DNS/TLS transport failures receive a bounded read-only health retry.
Both domains are reported even if one remains unreachable. If propagation exceeds
the bound, inspect the actual deployed SHA and rerun only `health` and browser
acceptance after DNS/TLS is ready; do not repeat deployment to wait for certificates.

The older Web deployment runbook describes pre-cutover D1 behavior. Current
runtime ownership is defined by `ARCHITECTURE.md`, `config/host-core-contract.yaml`
and the stateless edge workflow; no D1 migration or business Cron belongs here.


## First domain rollout evidence

PR #250 deployed Web SHA `e520007bf7ca8149f7ca71b15023bbd0d10d8591` through
protected run [40630159807](https://github.com/claude89757/wechat-on-airflow/actions/runs/40630159807)
at 2026-10-28 04:04:55 UTC. Both domains passed health and all six public browser
views, but the final no-write assertion failed on three blocked Cloudflare RUM
beacons injected on the new zone. Diagnostic replay confirmed each target was
`POST https://courts.zacks.vision/cdn-cgi/rum`; no subscription or email write
was attempted, and every POST was aborted. That original run remains failed.
The acceptance-only correction preserves the write block, reports telemetry
separately and is verified against the already deployed edge SHA. Do not repeat
apply for this diagnostic-only change. The host and Sender retain
`9cca72d73eb05c502446bd1d947c4307d7f73f35`.
