# YDMap control comparison and DSH review — not a production release

All observations in this document are dated 2026-09-16. Times below are UTC.
This record supersedes the older claim that every new-source attempt remains
at AccessLoadingHolder. It does not supersede the requirement for trustworthy
bookability evidence, reviewed runtime code and actual deployment acceptance.

## Scope and status

- Dashah control: wxsports.ydmap.cn / schedule100220 / product100000.
- New indoor: bawtt.ydmap.cn / schedule104036 / product111317.
- New outdoor: bawtt.ydmap.cn / schedule104036 / product103224.
- New-source adapters, active DAGs, catalog registration, notification activation
  and production deployment are NOT complete. No three-cycle acceptance exists.
- No production browser takeover, service restart, booking, payment, synthetic
  email or synthetic WeChat delivery was performed by these diagnostics.
- Probes use independent temporary profiles and non-production debug ports.
- Before/after scraper healthz returned ok=true. This is service liveness,
  not proof of every production venue's natural polling or notification health.

## What the same-provider comparison established

Run35073589879/job104720589894 started its real Pi probe at08:24:38.126428Z.
Artifact10437490985, ydmap-business-evidence, was downloaded and inspected.
Its digest is:
9fdd5d08be4891f7c29e07183e3ec8cbd6d2a5a1e1bb3ff5d38b6988faa0a7fb.

All three sources returned the same already-loaded booking business script:

- Path: /js/booking-schedule-venue.b6226c5c.js
- Size: 101072 UTF-8 bytes
- SHA256: 4b017dedcd26179928332a3d340842f4b7e0ca8ff46c5663a00b59f76435825a

This is byte-level equality for that captured bundle, not merely matching
filenames. It supports reusing the shared YDMap booking implementation rather
than inventing a separate frontend parser for BAWTT. It does not establish
identical tenant data, feature flags, booking rules or access policy.

The actual booking backend paths differ: Dashah uses srv100140; BAWTT uses
srv100244. Both observed sales-item/calendar/config/order resource families.
The public bundle builds schedule data by awaiting getSportVenueConfig and
getVenueOrderList together, then mapping venueTimeSlotResponses,
venueResponses, venuePriceResponses and old/new venue grid structures.
The route identifier is used as salesId in getSalesItemList; do not confuse it
with the per-court venueId when implementing a future adapter.

| Observation | Dashah | Indoor111317 | Outdoor103224 |
| --- | --- | --- | --- |
| URL/product and selected date | matched,2026-09-16 | matched,2026-09-16 | matched,2026-09-16 |
| Parent ready | true | true | true |
| ScheduleTable | present | present | present |
| Explicit data wait | 1.21s | 35.82s | 35.67s |
| Court names | 8 | unknown | unknown |
| Rendered time cells | 124 | none acquired | none acquired |
| Verified availability | no | no | no |

Rendered cells include unavailable/expired cells;124 is NOT an available-slot
count. An empty BAWTT component is NOT a verified empty booking schedule.

Page.getResourceContent successfully read the loaded public business bundle.
It failed to recover cached query bodies with WebDriverException for both the
working control and BAWTT. That is a limitation of that evidence-acquisition
method, not a demonstrated upstream HTTP or business error. Requests were not
replayed to work around the limitation. No raw query strings or headers were
exported.

https://github.com/claude89757/wechat-on-airflow/actions/runs/35073589879

## Corrections to earlier diagnostic assumptions

The existing Dashah production code recreates its browser profile each round.
Therefore a retained old login session is not an established explanation for
why its polling works.

Run35068987410/job104705779360, result07:32:21Z, used native Chromium with the
original URL supplied at startup, followed by delayed Selenium attachment.
All three sources reached ScheduleTable; Dashah had8 courts/125 rendered cells.
The first comparison returned when a component appeared, so its zero BAWTT cell
counts were not evidence that loading had finished.

Run35069607529/job104707739732, result07:41:27Z, instead opened about:blank,
attached performance logging, then navigated through driver.get. All three
sources, including Dashah, remained at AccessLoadingHolder. The observed
getConfig resource was HTTP200/text-html, with no body evidence. This does not
prove a BAWTT-only outage or identify a single causal browser flag; multiple
startup conditions changed. Native target-URL startup was restored without
fingerprint, navigator, user-agent or website-state modifications.

Run35070716599/job104711322421 stopped at Dashah because the new diagnostic
mistook a generic Slider component for access verification. BAWTT was not visited.

Run35071385101 then captured an isolated control screenshot. Artifact10435744872
was actually downloaded and visually inspected: Slider was the tennis product
and date strip; the real NeVerify root had zero height. The screenshot showed
normal product/date labels and a loading skeleton, NOT a CAPTCHA. Its artifact
digest is c25bbbbe3ee6855631f027a8f35fb050e7a49097a4bc2a6340750f2882b06174.
The false-positive detector was fixed; genuine visible verification/login
conditions still stop the probe. Real JavaScript fixtures cover generic Slider,
zero-height verification, visible verification, offscreen and transparent roots.

https://github.com/claude89757/wechat-on-airflow/actions/runs/35071385101

## DSH was actually invoked and returned a review

Run35072038544/job104715560615 used the installed DSH program through its normal
headless CLI, not the previously blocked web-auth or private-artifact route.
A new isolated workspace contained only supplied public code and current public
observation summaries. The instruction permitted static review and offline
local tests, not production or third-party website changes.

Artifact10435779451, ydmap-data-review, contains the real receipt:

- invoked=true
- launcherSource=observed_service_program
- exitCode=0
- state=review_completed
- credentialSetupRequired=false
- productionChanged=false;externalTestSends=0

The headless review began at08:08:50.959746Z. The preceding real observation
started08:07:20.335799Z and found Dashah8 courts/124 cells, while both BAWTT
products selected2026-09-16 but had no loaded time cells.

DSH usefully highlighted that JSON decoding is not business success, DOM cells
are not captured API bodies, and each source needs its own date/bookability
contract. Its assertion that schedule_component_only was a terminal state in
the current comparison loop was incorrect: the actual loop did not break on
that state. We did not adopt that finding. The next run's explicit35.82/35.67s
wait measurements confirm the distinction.

The wrapper retained only a bounded/redacted3500-character finalText, so the
complete structured review tail is unavailable in that artifact. No model name
or tool-call count was independently verified for this new invocation.

https://github.com/claude89757/wechat-on-airflow/actions/runs/35072038544

## Normal date-switch evidence, not forced interaction

Parallel work added a tenant-scoped passive response observer and a single
normal next-date click. These changes were preserved and shared the same
workflow concurrency group; no duplicate click probe was added here.

Run35073753854 started08:26:30.281998Z. Artifact10437595432, ydmap-date-query,
was downloaded and inspected:

- Dashah performed1 date click, selected2026-09-17, and rendered8 courts/106
  time cells. Its config and order responses were HTTP200/application-json,
  code0,msg=操作成功. Their data field was a string, not a decoded court array.
  We did not export its value or claim a verified bookability mapping.
- Indoor and outdoor each ended with ElementClickInterceptedException and
  dateClicks=0. Thus the requested switch was not completed for either source.
  It is not yet known which visible element intercepted those clicks.
- Neither failure authorizes force-clicking, removing an overlay, solving a
  CAPTCHA, invoking internal methods or replaying requests.

The next discriminating evidence is the BAWTT visible blocking element and its
normal UI state, followed by real public booking responses or verified DOM
schedule data. Do not simply repeat different startup scripts or reinterpret
failed acquisition as no available courts.

https://github.com/claude89757/wechat-on-airflow/actions/runs/35073753854

## Verification boundaries

The local latest comparator group passed12 tests, including executed browser-JS
fixtures and loaded-resource allowlist/error cases. The DSH discovery group
passed4 tests. Local Python3.13.5 is not the production Python version.
The loaded-resource workflow passed its pinned Python3.12 source checks before
running on the actual Pi. Earlier formatting-gate failures, notably35072818286,
never ran their browser step and are not extra venue-acquisition failures.

Full CI must be read on the final current PR head. Earlier green commits do not
prove a later head passed. No diagnostic run, static review, byte-equal script
or successful unit test constitutes deployment or three-natural-cycle acceptance.
