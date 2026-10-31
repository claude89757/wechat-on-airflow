# Release Strategy

## Versioning

The project follows Semantic Versioning. While the package remains below 1.0:

- minor releases may change documented deployment or configuration contracts;
- patch releases preserve DAG IDs, notification semantics, and configuration schemas;
- incompatible DAG ID or metadata ownership changes require an explicit migration plan.

Every named release updates `CHANGELOG.md`, `pyproject.toml`, and the runtime
package version together. Production operations use a pushed full commit SHA and
immutable tags; mutable branches are never deployment identities.

## Supported Runtime

| Component | Supported version |
| --- | --- |
| Apache Airflow | 3.3.0 |
| Python | 3.12 |
| PostgreSQL | 17 |
| Celery provider | 3.21.0 |
| FAB provider | 3.7.1 |
| Standard provider | 1.15.0 |

Dependency updates must pass the relevant component checks, migration rehearsal
when metadata compatibility changes, and the protected production gate. Airflow
major or metadata-schema changes still require explicit human approval.

## Single Production Control Plane

Only `.github/workflows/ops-chatops.yml` listens to owner comments on issue 39.
It parses mutually exclusive `/release` and `/ops` commands, calls reusable
workflows, and publishes one final result. Component workflows do not listen to
issue comments directly, which prevents one command from creating duplicate,
skipped, or misleading red Action runs.

The normal named-release command is:

```text
/release ship <version> <full-sha> scope=auto sender=false
```

`ship` validates the version contract before mutation, waits for the exact-SHA
`CI / verify` result in the common production gate, applies the resolved
component scope, verifies health, and only then creates the immutable tag and
GitHub Release.

Advanced commands remain available:

```text
/release preflight <full-sha> scope=auto sender=false
/release apply <full-sha> scope=auto sender=false
/release tag <version> <full-sha>
```

A separate preflight is recommended for unusual migrations, runtime upgrades,
or incident recovery. Routine low-risk releases use `ship`; Web apply and the
Airflow transaction both execute their own pre-mutation checks.

## Component Scope

`scripts/release_plan.py` compares the target with the preceding semantic
release and resolves these runtime components:

- `webapp`: Cloudflare Worker, D1 migrations, and browser assets;
- `airflow`: DAGs, runtime package, Airflow image/configuration, and Compose;
- `sender`: Android-host WeChat sender runtime;
- `pi_ydmap`: private Raspberry Pi YDMap scraping service; candidate source,
  mock tests and real date/product/court evidence must pass before it is
  activated and before the matching Airflow clients are deployed;
- `control`: workflows, release tooling, documentation, tests, or version-only
  metadata that require no runtime deployment.

`scope=auto` is the default. A manual scope may broaden the plan, but cannot omit
a detected runtime component. Any sender deployment additionally requires
`sender=true`; this remains an explicit real-host approval boundary.

Pi scraper apply waits for only the Dashah/Bao'an DAGs to drain, pauses them
through a bounded protected guard, and restores their original pause flags after
acknowledged completion. Lost connectivity retains the pause until the bounded
lease fence ends. The installer requires measured proof and sufficient remaining
time for real-port inspection plus rollback, including for the first legacy
replacement. See `docs/runbooks/pi-ydmap-deployment.md`.

Component identities may therefore differ after a Web-only or control-only
release. The release summary records the target, diff base, resolved scope, and
each component result instead of pretending every runtime was replaced.

## CI Efficiency and Authority

The required check remains named `verify` for release-gate compatibility. It
always runs lint, type checking, unit tests, and workflow contracts, then runs
only the Web, Airflow, or sender build suites relevant to the changed surface.
Control-plane or unknown paths conservatively run all suites. New commits cancel
stale pull-request CI runs, while `main` runs are never cancelled because their
exact merge SHA is a release candidate.

The common production gate is the only CI waiter. It fails immediately when an
older target has no CI record, polls only existing queued/in-progress checks,
and rejects unsuccessful checks. ChatOps does not perform a second 30-minute
wait.

## Rollback

The release planner compares a candidate with its preceding semantic release;
it is designed for forward releases, not for selecting an arbitrary historical
component during incident response. A component-only rollback therefore uses
the matching protected reusable workflow directly with the prior recorded
component commit:

- `production-webapp.yml` for Web;
- `production-airflow.yml` for Airflow application services;
- `production-wechat-sender.yml` for the sender, with explicit approval.

Use the full production release path only for a reviewed repository-wide
rollback whose scope intentionally includes every detected component. The
Airflow transaction preserves stateful volumes and reports deployment and
health results separately. It does not automatically restore the pre-deploy
image on a health failure; inspect the deployed identity and the explicit
`automatic_restore` result before choosing a recovery path.

Database restore, Airflow major-version migration, and metadata deletion remain
separate high-risk operations requiring explicit approval.

### Routine release acceptance waiting

A completed business report is not necessarily a successful release. When all
technical checks pass and only natural email/WeChat delivery evidence is absent,
acceptance reports `pending`, exits 75, creates no tag/release, and keeps the healthy
single delivery owner active. A missing/malformed report, any other failed check,
or missing evidence upload remains a failure and uses the safety-stop path.
Resume by re-running **failed jobs on the same ship run**, not by starting a new
ship: successful deployment/activation ancestors must not rerun or reset the
acceptance window. Completion still requires all original natural-delivery checks.
No synthetic notifications may be sent to satisfy acceptance.

Release preflight now diagnoses a dirty Airflow worktree instead of automatically
repairing it. Its fixed read-only business inventory reports the explicitly retired
Shenzhen Bay fourth-day key separately, aggregate other stored scopes, current
runtime/control identities and delivery flags, and past-24-hour natural delivery
counts. These baseline counts are not evidence for the new release. Unknown or
failed inventory is a preflight blocker; no database/schema maintenance is allowed.
