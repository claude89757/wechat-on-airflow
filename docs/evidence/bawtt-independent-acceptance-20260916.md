# BAWTT 104036 independent live acceptance — NOT released

## Decision

The requested indoor (`111317`) and outdoor (`103224`) availability monitors
are NOT running in production. No active DAG, catalog/subscription registration,
verified bookability parser, production deployment or three-cycle acceptance
has been completed for them. Passing diagnostic tests does not change that.
The implementation and release request remains incomplete.

These observations come from new, ordinary public-page tests on the actual Pi,
not from the previous DSH agent's private artifacts or from a GitHub browser.
No old DSH authentication/artifact access was retried. No booking, payment,
real notification, CAPTCHA solving or fingerprint modification was performed.

## Independently reproduced observation

Latest browser run:
https://github.com/claude89757/wechat-on-airflow/actions/runs/35064917872

- Workflow commit: `5941412dc585787752a9017ab01d035944b23b4c`.
- Probe/test source: `27988092a6acd70af2f6d9008aa9335ae0611508`.
- Job: `104692980605`.
- Probe start: `2026-09-16T06:42:31.650694+00:00`.
- Result logged: `2026-09-16T06:44:09.3319261Z`.
- Protected transport baseline: `126c359919556081f68cf8199f5de9898129694b`.
  Its exact-main `verify` gate passed before SSH execution.
- Both targets returned `query_acquisition_incomplete`; remote exit code 1.
- `productionChanged=false`, `productionReady=false`, `externalTestSends=0`.

| Observation | Outdoor 103224 | Indoor 111317 |
|---|---|---|
| Exact source URL/product match | true | true |
| Document readyState | complete | complete |
| Initial and final visibility | visible | visible |
| Vue instance present | true | true |
| WebAssembly available | true | true |
| Document script count | 18 | 18 |
| ScheduleTable found | false | false |
| Usable calendar/order JSON observed | no | no |
| Visible CAPTCHA detected in this attempt | no | no |
| Court count / available slots | unknown | unknown |

The observed component tree for both targets was:

```text
anonymous
  anonymous
    Layout
      AccessLoadingHolder
```

The 45-second per-target observation window did not progress into the schedule
component. Both windows were already visible, so the hidden-window focus action
was not needed. Hidden-page suspension is not supported as the cause here.

The recorded main document, Vue libraries, application/schedule bundles and
`/assembly/build/portal.wasm` had HTTP 200 responses. The visible body contained
156 characters of measurement/test text, including `Element.getClientRects`
and `F i n g e r p r i n t i n g ?`, not booking information. One outdoor console
resource error reported HTTP 404, but its resource identity was not retained;
it is NOT established as the cause of the stall. Indoor logged no such error.

Confirmed boundary: site initialization remains in its access-loading component
before a usable public schedule query is observed. The exact cause is NOT
conclusively established. A component name or fingerprint-related test text
alone does not prove CAPTCHA is currently present, a particular WAF decision,
a website-wide outage, zero free courts, or that bypassing a check is needed.

Earlier independent runs support the same acquisition failure:

- `35063255418` / job `104687917184`: Selenium on Pi, two source matches,
  app root present, body text length 156, no table or query samples.
- `35063330002` / job `104688194040`: separate native Chromium/CDP implementation,
  both targets `schedule_not_ready`, no usable API samples. Its wrapper rejected
  the failed acceptance even though the diagnostic process itself exited zero.
- `35064229922` / job `104690876066`: main resources loaded, Vue and WASM present,
  both targets still had no table/query samples. Results logged 06:35:35 UTC.

The earlier DSH report of one rendered outdoor table and subsequent challenge
is retained in `bawtt-onboarding-20260916.md`. It has not been promoted into a
successful independent bookability acceptance by these later failed runs.

## Code and verification performed

`bawtt_live_query.py` uses fixed source identities and passive observation of
four allowlisted public query paths. It isolates its browser profile from the
running Dashah scraper, bounds diagnostic output, and distinguishes failed
acquisition from observed query samples. The latter still is NOT bookability
acceptance. It stops on a rendered login/challenge or observed WAF query HTML.
It never publishes availability or notification intents.

Local Python 3.13.5: 34 related BAWTT tests passed. This is not the production
Python version and does not establish a full project verification.

Actual GitHub Python 3.12.14 evidence:

- Latest Pi-preflight job: 15 live-query tests, ruff check and format check passed
  before the real page acquisition failed.
- Run `35065238832`, job `104693947568`: whole-repository `ruff check` passed;
  `ruff format --check` reported 220 files formatted; 53 combined BAWTT and
  release-gate/pagination regression tests passed in 0.40 seconds.
- That formatting reconciliation verified AST equivalence and found no further
  file changes necessary; it did not make a redundant formatting commit.
- The parallel release-gate pagination repair is preserved. It fixes the earlier
  first-page-only check lookup without accepting incomplete or wrong-SHA checks.
- Final full CI must be read on the actual final PR head. The targeted run above
  does NOT replace full CI, deployment or venue acceptance.

Local `make verify` was also attempted and failed at its first command because
this sandbox lacks the expected `.venv/bin/ruff` executable. No checks were
waived to turn that into a pass; the existing CI is the separate full-runtime
verification route.

The temporary write-capable formatter workflow was removed after its run.
The live-query workflow was made manual-only after the reproduced stall;
ordinary commits no longer start this probe. Parallel work and existing
production code/configuration were preserved.

## Required next evidence, not an automatic rollout

First establish ordinary interactive access to both original booking pages on
the Pi. If the site presents a human verification prompt, complete its normal
process or obtain a supported platform query integration; do not synthesize
fingerprints, forge tokens, copy another browser's cookies or disable checks.
If the ordinary page also remains in AccessLoadingHolder, the platform/browser
initialization failure needs diagnosis through a supported access path.

A useful handoff contains a successful calendar/order response with private
fields removed, the selected product/date and public court/time/state fields,
and a visible-page comparison including unavailable/unreleased states. A URL,
HTTP 200, page shell or agent `completed` status is not sufficient.

Then implement and verify separate indoor/outdoor observation identities,
source/date freshness checks, explicit bookability rules, shared-browser
resource protection, safe URL/shell handling, catalog/DAG contracts and failed
observation semantics. Only after those pass full CI may protected exact-SHA
release and three natural successful cycles be accepted. No such release is
claimed by this document.
