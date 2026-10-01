# YDMap source comparison: order-query verification confirmed, not released

All observations below are dated 2026-09-16; times are UTC. This record replaces
incomplete earlier hypotheses, not the requirement for genuine data validation.

## Scope and delivery status

- Dashah control: wxsports.ydmap.cn / schedule100220 / product100000.
- BAWTT indoor: bawtt.ydmap.cn / schedule104036 / product111317.
- BAWTT outdoor: bawtt.ydmap.cn / schedule104036 / product103224.
- BAWTT adapters, active DAGs, catalog/notification activation and production
  deployment are NOT complete. No three-natural-cycle acceptance exists.
- Diagnostics used isolated temporary profiles and non-production debug ports.
  They did not take over Dashah's production browser, restart services, create
  bookings/payments, or send synthetic email/WeChat messages.
- Before/after scraper healthz was ok=true. That proves liveness, not complete
  natural polling or delivery health for every existing venue.

## New decisive evidence: the indoor order query returns a verification page

Run35074563535 used workflow commit4ff9eb093fcccef85532ecc0c0c7141acd834f42
and exact observer source db9871e5bc5d06897b0d0db81992abcc2ed6ed68.
Artifact10436908724, ydmap-overlay, was downloaded; observation.json was read
and indoor.png was actually opened and visually inspected.

- Probe started08:35:19.641652Z, indoor observation elapsed8.82seconds.
- Artifact ZIP SHA256:
  91df3135f0f39e81075910d5e697452d607a294d6b4279afa3e42cdf09238f4b
- The URL matched the requested indoor product; DOM selectedProduct=111317,
  selectedDate=2026-09-16, ScheduleTable present, no actual time cells acquired.
- dateClicks=0; mode=overlay_observation_no_click; productionChanged=false.

The observed normal page requests were:

| Path suffix under srv100244/api/pub/sport/venue | HTTP / MIME | Actual envelope/body evidence |
| --- | --- | --- |
| getSalesItemList | 200 / application-json | code0, msg操作成功; data is an opaque string |
| getVenueCalendarList | 200 / application-json | code0, msg操作成功; calendarList length2 |
| getSportVenueConfig | 200 / application-json | code0, msg操作成功; data is an opaque string |
| getVenueOrderList | 200 / text-html | accessChallenge=true, access_verification_required, not JSON |

Code0 is an observed success envelope, NOT verified decoded bookability data.
No opaque data string, authentication values or raw request headers were exported.

The screenshot visibly shows “访问验证” and “为保证您的正常访问,请进行如下验证”.
The top hit-tested element above the date strip is DIV.waf-nc-mask, with a
1248x668 rectangle and opacity0.5. A full-page layer contains the same visible
verification text. The verification challenge interaction itself was not
rendered in that screenshot; do not claim a particular puzzle was observed.

This establishes the proximate failure in THIS indoor attempt: a booking order
request was answered by access-verification HTML, and the corresponding page
mask prevented normal interaction. It does not establish the provider's exact
trigger rule, a permanent tenant-wide policy, or a website-wide outage.

The probe stopped on verification. **Outdoor was not visited in this run.**
Its earlier empty schedule/intercepted click remains unaccepted, but this run
must not be represented as a separate outdoor CAPTCHA observation.

One more acceptance gap remains: the screenshot's top product strip appears
to highlight 室外网球场 while DOM selectedProduct reports111317. Rendering may
not have settled, but the cause is unverified. URL and one DOM property cannot
prove every displayed product and response is consistently bound to the target.

The older Vue-only detector returned challenge=false and no visible NeVerify,
because the actual WAF mask is outside that inspected component tree and the
Chinese phrase “访问验证” was missing from its text match. This is a detector
false negative, distinct from the earlier generic Slider false positive.
Fix shared detection with offline fixtures, not more third-party page attempts.
Do not remove the mask, force-click, solve/bypass verification, forge/replay
signed requests, or convert this failed acquisition into a healthy empty result.

https://github.com/claude89757/wechat-on-airflow/actions/runs/35074563535

## Same supplier really does use the same captured booking business bundle

Run35073589879/job104720589894 started08:24:38.126428Z. Artifact10437490985,
ydmap-business-evidence, was downloaded and inspected; artifact digest:
9fdd5d08be4891f7c29e07183e3ec8cbd6d2a5a1e1bb3ff5d38b6988faa0a7fb.

All three sources returned the same already-loaded public booking script:

- /js/booking-schedule-venue.b6226c5c.js
- 101072 UTF-8 bytes each
- SHA256: 4b017dedcd26179928332a3d340842f4b7e0ca8ff46c5663a00b59f76435825a

This is byte-level equality, not just matching filenames. The backend paths
are nevertheless different: Dashah uses srv100140; BAWTT uses srv100244.
Shared frontend code does not prove identical tenant data or access policy.

The public bundle awaits getSportVenueConfig and getVenueOrderList together
before constructing the grid. This explains why successful product/calendar
loading can coexist with missing schedule cells when the order query requires
verification. Do not identify response data strings as decoded court arrays.
The route identifier is salesId in getSalesItemList, not a per-court venueId.

| Observation | Dashah | Indoor111317 | Outdoor103224 |
| --- | --- | --- | --- |
| URL/product/selected date | matched,2026-09-16 | matched,2026-09-16 | matched,2026-09-16 |
| Parent ready / ScheduleTable | true / present | true / present | true / present |
| Explicit data wait | 1.21s | 35.82s | 35.67s |
| Court names | 8 | unknown | unknown |
| Rendered time cells | 124 | none acquired | none acquired |
| Verified availability | no | no | no |

Rendered cells include unavailable/expired cells;124 is NOT a free-slot count.
Page.getResourceContent recovered the public script but failed to recover
cached XHR bodies for both the working control and BAWTT. Those exceptions are
an evidence-reader limitation, not demonstrated upstream HTTP/business errors.
No requests were replayed to work around that limitation.

https://github.com/claude89757/wechat-on-airflow/actions/runs/35073589879

## Our diagnostic assumptions corrected with controls and screenshots

Dashah's production code recreates its profile each round. Retained old login
state is therefore not an established explanation for its successful polling.

Run35068987410/job104705779360, result07:32:21Z: original URL in native Chromium
startup arguments followed by delayed Selenium attachment reached ScheduleTable
for all3sources; Dashah had8courts/125cells. The first probe returned too early
on component presence. That success did not certify loaded BAWTT schedule data.

Run35069607529/job104707739732, result07:41:27Z: about:blank startup, performance
logging attachment, then driver.get left ALL3sources, including Dashah, at
AccessLoadingHolder. Multiple conditions changed; this does not prove one
causal browser flag or a BAWTT-only outage. Native target-URL startup was restored
without fingerprint, navigator, user-agent or website-state modifications.

Run35070716599 stopped at Dashah because our detector misclassified Slider.
Run35071385101's screenshot artifact10435744872 was actually viewed: Slider
was the product/date strip; the real NeVerify root had zero height. There was
no displayed CAPTCHA in that image. That false positive was fixed and tested
with actual JavaScript cases: Slider, zero-height/visible verification, offscreen
and transparent ancestors. It does not invalidate the NEW actual WAF screenshot.
Artifact digest: c25bbbbe3ee6855631f027a8f35fb050e7a49097a4bc2a6340750f2882b06174.

https://github.com/claude89757/wechat-on-airflow/actions/runs/35071385101

## DSH was actually invoked and returned a review

Run35072038544/job104715560615 invoked the installed DSH through its normal
headless CLI in a new isolated workspace of public code and current evidence.
It did not retry the previously blocked web-auth/private-artifact route.
Artifact10435779451 contains the actual receipt:

- invoked=true; launcherSource=observed_service_program
- exitCode=0; state=review_completed; credentialSetupRequired=false
- productionChanged=false; externalTestSends=0

Review started08:08:50.959746Z. Its useful findings distinguished JSON decoding,
DOM cells, business success and per-source/date/bookability validation.
Its claim that schedule_component_only was terminal in the comparison loop was
incorrect and was NOT adopted; the later35.82/35.67second measurements also
confirm the loop waited. An agent's report is not automatically correct.

The wrapper kept a bounded/redacted3500-character finalText; the full review
tail is unavailable. No model name or tool-call count was independently verified
for this new invocation. This review is not production acceptance.

https://github.com/claude89757/wechat-on-airflow/actions/runs/35072038544

## Normal next-date navigation comparison

Run35073753854 started08:26:30.281998Z. Artifact10437595432 was downloaded/read.
Dashah completed1normal date click to09-17 and rendered8courts/106cells; config
and order responses were HTTP200/application-json/code0/msg操作成功, with data
as a string. Neither BAWTT click completed: ElementClickInterceptedException,
dateClicks=0. No forced interaction followed. The later no-click screenshot
above establishes an actual indoor verification layer, not outdoor verification.

https://github.com/claude89757/wechat-on-airflow/actions/runs/35073753854

## Verification and remaining release conditions

The comparator local group passed12tests, including executed browser-JavaScript
fixtures and loaded-resource allowlist/error cases. DSH discovery passed4tests.
LocalPython3.13.5 is not productionPython3.12. Protected workflows ran pinned
Python3.12 checks before Pi execution. Formatting-gate failures35072818286 and
35074224799 never executed their browser step and are not venue failures.

Full CI must be read on the final PR head. Earlier green commits do not certify
a later head. Offline detection fixes must preserve real failures and never
publish a healthy empty observation or notification for a verification page.

The remaining access requirement is a normal supported access/verification
flow for the actual deployment browser, or a provider-approved query integration.
Do not promise that one manual verification guarantees unattended future access.
After access is established, validate each source's product/date/courts and
available/unreleased/unavailable states, finish source-isolated adapters and
DAG/catalog contracts, pass exact-SHA CI and reviewed deployment, and observe
three natural successful cycles per source. None of those release conditions
is replaced by a diagnostic success, identical JS bundle or static review.
