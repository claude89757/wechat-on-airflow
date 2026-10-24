# BAWTT rollout preflight: BLOCKED, not released

Observation date: 2026-09-16. This supplements the historical DSH investigation
in `bawtt-onboarding-20260916.md`; it does not replace its scope limitations.

## Exact request and release status

- Venue `104036`; indoor `111317`, outdoor `103224`.
- The user requested implementation, production release and acceptance.
- Actual result: public-query acquisition failed for both products. No active
  BAWTT DAG, venue catalog entry or production notification route was added.
- No merge, release tag, production deployment, booking/payment or synthetic
  notification was performed. Three natural successful cycles were NOT observed.
- Do not interpret passing diagnostic/unit/CI jobs as venue rollout acceptance.

## New independent evidence (not old DSH private artifacts)

All page observations below used normal browser controls on the authorized Pi,
with an isolated temporary profile and no CAPTCHA solution, fingerprint patch,
credential extraction, authentication bypass or production-browser takeover.
The previously blocked DSH artifact reconciliation was not retried.

| Run / job | Actual result |
| --- | --- |
| `35063330002` / `104688194040` | Both sources: app root present, 18 scripts, no ScheduleTable, no recognized calendar/order responses. Workflow failed; not empty availability. |
| `35063914013`, attempt 2 / `104691465535` | UI diagnosis completed at 06:36:31Z. Both sources: Vue2 mounted, app text empty, only DIV:fixed-width in app. JS/CSS/WASM resources loaded with 200 responses; no calendar/order queries started. |
| `35064917872` / `104692980605` | Normal-window query preflight completed at 06:44:09Z and FAILED. Both windows initially visible, document complete, Vue and WebAssembly available; component chain ends in Layout -> AccessLoadingHolder. No calendar/order responses and no schedule cells. 15 dedicated probe tests passed before the real acquisition failed. |

Raw runs:
- https://github.com/claude89757/wechat-on-airflow/actions/runs/35063330002
- https://github.com/claude89757/wechat-on-airflow/actions/runs/35063914013
- https://github.com/claude89757/wechat-on-airflow/actions/runs/35064917872

The last run observed only fingerprint measurement text in document.body, not
usable booking content. Layout exposed field NAMES including srvInfo and error;
its private values were not exported. No named CAPTCHA/login prompt was detected
in these latest observations. That does not establish that access preparation
succeeded, and it does not justify claiming a particular CAPTCHA was displayed.

**Established failure boundary:** the public application does not advance past
its access/loading initialization into the booking schedule in this environment.
It is not a successful empty schedule. It is also not merely a Vue2/Vue3 selector
mismatch or a hidden-window issue. Exact site-side failure reason is unresolved;
the evidence alone cannot distinguish compatibility, a site error or an access
policy decision. Do not invent a specific cause or bypass the loading component.

A credential-free GitHub-hosted request for one already-observed public business
script returned HTTP200/text-plain/204 bytes, not JavaScript, in run35064902633.
The attempt stopped without retry or endpoint substitution. No business-source
contract was recovered from that response.

## Deployment gate defect discovered and fixed in PR

Main `126c359919556081f68cf8199f5de9898129694b` had 104 check records. Its successful
required `verify` check, job `104262985797`, was on page2. The original gate only
read page1 (100 records), falsely reporting required_check_present=false.

The new `fetch_check_runs` implementation reads bounded pages and rejects
malformed pagination metadata, a changing total, duplicate IDs, wrong head SHA,
incomplete pages and excessive page counts. The existing rule remains unchanged:
the newest required check must be completed/successful and the target on main.

Files: `scripts/github_release_gate.py`, `tests/github_check_pagination_test.py`.
The local gate/ops regression group passed 79 tests plus one subtest. The combined
group including the then-present isolated browser tests passed 98 plus one
subtest locally. Run35065019540 repeated that combined group on Python3.12.14
and completed successfully after installing the required pinned PyYAML package.
Its formatter verified AST equivalence before committing cosmetic changes.

- https://github.com/claude89757/wechat-on-airflow/actions/runs/35065019540

For immediate diagnosis, the original exact-main verify job was legitimately
rerun: run34932338181, replacement job104690362788 completed successfully. The
later Pi diagnosis passed the unchanged main gate. No check result was forged,
renamed, ignored or bypassed. The permanent pagination fix remains in this PR;
it is not yet merged into the production control plane.

## Repository cleanup and preserved parallel work

The one-off public-contract workflow, source-formatting helper and duplicate
public-browser/UI diagnosis scripts are retired after evidence collection.
Their historical commits and run logs remain. Their removal does not suppress
an active venue test, because none of these probes was a production venue.

The concurrently developed `bawtt_live_query.py`, its tests and workflow are
preserved, alongside the earlier credential-free onboarding probe. No parallel
branch changes were overwritten. The latest full PR CI must be checked on the
final head; earlier green runs are not final-head acceptance.

## Remaining unblock and acceptance, in order

First establish normal successful access to these exact two booking products on
the Pi: an operator can open them in an ordinary browser and complete only the
site's normal displayed access/login checks. A normal page that also stays blank
needs the venue/platform's assistance; no automation parser can turn that blank
page into a trustworthy schedule. Do not request/export passwords, raw HARs,
Cookies, fingerprint tokens, signing keys or other DSH session data.

After normal access works, obtain minimal public calendar/order JSON samples
and compare product ID, selected date, courts, released/disabled/bookable states
with the visible UI. The actual response semantics must determine the parser;
HTTP200, an empty app or lack of disabled CSS alone cannot determine availability.

Then finish the shared Pi source selector/browser locking, source-specific
observation and dedupe identities, catalog/booking-link/cadence contracts and
Airflow DAGs. Keep acquisition failure distinct from verified empty data and
preserve Dashah behavior. Complete full checks and reviewed exact-SHA release,
then verify the deployed identity and three natural successful observation
cycles for EACH source without synthetic email/WeChat sends.

Until these conditions are met, releaseReady=false and the new venues remain
inactive. This is an unfinished rollout, not a successful deployment report.
