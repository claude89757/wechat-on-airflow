# Scoped Verification

Browser installation and the subscription/date-pause browser suite follow actual
Web runtime, browser-test, configuration and dependency changes. Backend health,
release tooling and production-only QA scripts do not install Chromium just
because they select Web unit/build checks. Mixed frontend/control changes and
unknown paths still select browser checks. Scheduled and manually dispatched
full regression always include them. This avoids turning a routine control
update into an unrelated browser download; exact-main CI remains mandatory.

The main commit's `CI / verify` remains the release gate. Pull requests run only
`pr-check` (lint, formatting, Python compilation and diff checks); main runs component tests
once after merge. A green PR is NOT release authorization: main verification must
pass, and a failing main commit must not deploy. Documentation and frontend-only
changes do not start PostgreSQL or install and test the Python application.
Python sources, tests, backend, Sender, control-plane and unknown changes retain
the complete Python suite, including database contracts, on main. MCP authentication
tests remain mandatory on main when the corresponding MCP component changes.

The main ruleset requires `pr-check` for merging, without an up-to-date-branch
requirement. Main's `verify` tests the actual integrated commit before deployment;
the release gate never accepts the PR-only check. Review-thread resolution and
protection against deletion/force pushes remain enabled.

Image builds, DAG imports and dual-Python Sender compatibility run before release
when Docker, dependencies, DAGs or unknown files change; otherwise they run in
the daily full regression. Production still builds the exact commit and checks
service health. This reduces duplicate image builds without trusting workstation
artifacts or introducing an image-promotion subsystem.

The owner accepts interruptions. Unified Airflow apply uses `deploy_recovery`:
stop executors, mark unfinished scheduled tasks failed (retain their history),
clear the transient broker queue, deploy, then restore scheduling. PostgreSQL
business outboxes, deduplication and provider receipts are never cleared.
Immediate post-deploy health does not fail solely for recent DAG-run history:
interrupted runs remain visible and are reported as pending observation. The
standalone health monitor remains strict; unhealthy services, wrong commits,
missing DAGs and other failures still block the deployment.
Do not wait ten minutes for scheduled/retry tasks to drain. Routine component
updates can use protected component workflows with a full SHA, without creating
a semantic-version release first. Ship/tag remains optional release bookkeeping.

Scheduled CI runs all component checks daily at 20:17 UTC. Manual CI dispatch also
runs all checks. These runs never deploy or send notifications. Failures appear
in Actions and must be triaged; this does not create a separate alert transport.

During local iteration run focused checks for the affected component. Shared
Python and release-control work uses `make lint typecheck test`. Add image and
DAG checks when Docker, dependencies or DAG wiring changes; use `make verify`
for ambiguous cross-component changes or explicit full regression.
Documentation-only work needs diff/link checks; frontend-only work needs
`make webapp-check`; MCP-only work needs its package tests and security checks.
Never substitute a locally successful check for the exact pushed commit gate.

Use the existing unified release entry and component planner. Protected identities,
exact commits, deployment health and separate high-risk approvals are unchanged.
Natural observation remains asynchronous. This optimization does not introduce
CI-built image promotion. Formal versioned ship still creates a tag, but routine
SHA-based component repair does not require a new version or release ceremony.
Venue and coupled business updates use `make release TARGET_COMMIT=<full-sha>`;
see [venue-onboarding.md](venue-onboarding.md). This is one protected workflow,
with a live-runtime diff base and no unrelated MCP preflight. Deployment builds
the exact verified sources without repeating main's frontend unit/type tests.
Host health, acceptance and emergency pause target the deployed main-ancestor
commit, not necessarily latest main. Host source and live API must both match
that target; these operations never check out an older production version.
