# BAWTT 104036 onboarding: read-only validation, NOT activated

## Requested sources

| Logical source | Venue ID | Sales item | Booking entry |
|---|---|---|---|
| `bawtt_104036_indoor` | `104036` | `111317` | https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=111317 |
| `bawtt_104036_outdoor` | `104036` | `103224` | https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=103224 |

Indoor/outdoor labels come from the user's request. The public venue name,
court inventory, release horizon and opening time have NOT been verified.
Do not guess a venue name from its numeric ID.

## Production baseline actually checked

Reviewed main: `126c359919556081f68cf8199f5de9898129694b`.
Existing protected command on Release Control #39:

```text
/ops device-network-preflight 126c359919556081f68cf8199f5de9898129694b
```

Evidence: https://github.com/claude89757/wechat-on-airflow/actions/runs/35046490262
Job `104637332884`, observation `2026-09-16T02:04:06Z`.

- Exact-main CI gate passed; Airflow host inspection succeeded.
- Host Core API and Sender report healthy; pinned Pi tunnel SSH authenticated.
- The tunnel's `127.0.0.1:8788/healthz` response failed JSON decoding.
  HTTP status, content type and response body are not present in this probe's
  report. This does NOT establish the root cause or prove that the existing
  Airflow-to-Pi scrape route has failed.
- Host Core / Sender runtime commit:
  `a730feea501fc3d50dd78b96f3ba67a8b1dc897b`.
  This differs from the inspected main commit; the DAG deployment SHA was not
  independently measured by this probe.
- 26 venue-status records; zero stale/unhealthy records by the existing
  ten-minute check. This is not end-to-end notification or scrape acceptance.
- Business health failed these checks:
  `notification_outbox:noNewUnknownSubmission`,
  `wechat_outbox:noNewUnknownSubmission`,
  `wechat_outbox:noNewTerminalFailure`.
- Overall preflight failed. `configurationChanged=false`, `externalTestSends=0`.

No production configuration, code, database state, notification settings,
booking, payment, or runtime credentials were changed/exported for this work.

## Why not copy Dashah's watcher and replace its URL

The existing scraper hardcodes its URL and shares its Chromium profile,
debug port and process lock. Independent copies using those resources would
conflict. The client also builds a shell curl command; adding multiple query
parameters requires proper URL construction and shell quoting, not string
concatenation with a raw ampersand.

Dashah's fifth-day noon rule is venue-specific. Its status-class exclusion and
signature-change check do not prove the selected source, booking date or an
explicitly released slot. An unchanged signature can still be returned at a
wait timeout. The recent six-court full-day circuit breaker is an emergency
Dashah guard, not a verified BAWTT eligibility rule.

## Changes in this draft

`scripts/probe_bawtt_ydmap.py` is an isolated, credential-free, read-only public
page probe. It reuses the ScheduleTable discovery approach without turning
visible cells into availability. It rejects cross-source redirects, reports
verification challenges, and always declares `productionReady=false`. It does
not import notification clients or connect to production. Browsers use private
temporary profiles and never attach to or kill the running Dashah browser.

The branch-only workflow performs the same bounded probe from a GitHub-hosted
runner, with no production environment, no secrets and read-only GitHub rights.
No raw HTML, cookies, screenshots, slot data, account details or exception
messages are logged. A passing public-page probe is NOT a Pi live acceptance.

Local credential-free regression result: 15 passed on Python 3.13.5. The project
requires Python 3.12; the workflow checks that version. Full `make verify` and
actual BAWTT browser validation were not run in the local sandbox because it
cannot resolve outbound hosts and has no Selenium/Chrome runtime.

## Required handoff before enabling notifications

1. Diagnose the Pi HTTP health mismatch through the protected production route;
   record status, content type and bounded non-sensitive diagnostic categories.
   Separately verify the existing Airflow-to-Pi route and release identity.
2. Render both requested pages on the intended scrape host and verify the exact
   venue name, product ID, court inventory, selected date, loading completion,
   positive bookable status and unreleased/disabled states against the UI.
   Stop on a verification challenge; do not bypass access checks.
3. Generalize the existing Pi service with an allowlisted source selector and a
   single shared browser lock. Preserve Dashah's existing route and behavior.
   Use URL encoding and shell quoting; reject unknown targets.
4. Add independent indoor/outdoor observation IDs, cache/dedupe identities and
   booking links; update catalog, active-component and cadence contracts.
   Confirm horizon/release policy rather than copying Dashah's noon rule.
5. Cover wrong-source/date, stale unchanged grid, incomplete data, CAPTCHA,
   disabled/unreleased cells, full-day placeholders, busy responses, timeouts,
   adjacent-slot normalization and independent target failure in tests.
6. Require full `make verify`, exact-SHA CI and reviewed protected deployment.
   Perform dry-run observation validation without real sends, then observe
   three natural successful cycles before marking production ready.

This draft deliberately adds NO active DAG, catalog entry or subscriber route.
The monitoring integration remains incomplete until those acceptance gates
are met. Do not mark this PR as a completed venue rollout.
