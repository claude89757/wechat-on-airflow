# Passive request evidence repair (not a new live experiment)

Baseline: 1639ae4047614359b8ee25d22e34537ec1ed6fb3, PR223.
This change extends the existing QueryTrace and existing date-probe report.
It adds no workflow, recurring task, venue activation, new site request or
production deployment. No CAPTCHA was solved or bypassed; no DSH task ran.

## Implemented

- Capture Network.requestWillBeSent before correlating responses. Store its
  actual wallTime as startedAt, monotonic request/response/finish timestamps,
  and durationMs only when both endpoints are present and consistent.
- startOrder is the observed allowlisted request-start ordinal, NOT a global
  request number. Result array order remains body-completion order. Missing
  start events retain null time/order and unknown product binding.
- Extract only literal top-level salesId/salesItemId and valid ISO dates from
  the already-observed URL or small plain JSON/form body. No raw query string,
  body, header, Cookie, token or provider request ID is exported. Nested/opaque
  payloads stay unknown; no extra getRequestPostData request or decoding occurs.
- productBinding=observed means an explicit public field was observed. It is
  NOT UI/product/response correctness or live bookability acceptance. Repeated,
  conflicting and invalid identity fields are reported as ambiguous, not guessed.
- Preserve redirect hops separately, reject mismatched response origins/paths,
  distinguish missing response/body/network errors, and bound retained records.
- Expose dropped start/response EVENTS separately, unmatched responses, queue
  drain limits, invalid frames and unresolved response/body counts. Dropped
  event counts cannot be summed to obtain unique dropped requests.
- The date observer saves query metadata and coverage in finally, including
  failures, and declares its fresh temporary profile and late-attachment delay.

## Deliberate limits

fullNavigationCaptured=false and triggerRateEstimable=false remain explicit.
The observer still attaches after ordinary page initialization: it cannot
recover historical events. No startup order was changed to claim otherwise.
Its counters describe observed CDP events, not whole-browser or shared-IP traffic.
Requests using opaque bodies can still have unknown product/date binding.
No cache, session-age, human-verification lifetime or platform rule-ID evidence
is invented. This patch cannot establish a cooldown, safe request threshold,
CAPTCHA probability, or a successful BAWTT availability observation.

The known access challenge and normal stop conditions remain. Automatic site
workflows remain manual-only. The next usable data must come from ordinary
permitted access, paired with successful schedule data or provider diagnostics;
this commit does not collect that new data or resume challenge retries.

## Validation

Local Python3.13.5: 28 tests passed across the unchanged query-evidence tests
and new trace-metadata tests; the existing browser-JS test executes six fixture
cases in Node. Focused ruff check/format and Python compilation passed.
Fixtures are synthetic offline events, not new measurements of YDMap.

The reconstructed unchanged date observer and original test file were checked
against their exact Git blob hashes before patching. Local make verify was
attempted but stopped because .venv/bin/ruff is absent. The sandbox has no
outbound DNS, Python3.12 project environment, or Docker; focused checks do not
substitute for full exact-head GitHub CI. No all-green claim is made here.

Protocol reference: Chrome DevTools Protocol Network domain, especially
requestWillBeSent, responseReceived, loadingFinished, loadingFailed and the
request/response body contracts:
https://chromedevtools.github.io/devtools-protocol/tot/Network/
