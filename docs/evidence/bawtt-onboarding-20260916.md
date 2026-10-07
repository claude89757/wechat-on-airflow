# BAWTT 104036: DSH collaboration completed; venue rollout NOT activated

## Requested sources

| User label | Venue | Sales item | Public entry |
|---|---|---|---|
| Indoor | 104036 | 111317 | https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=111317 |
| Outdoor | 104036 | 103224 | https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=103224 |

Do not guess a venue name, court count, release horizon, price or release time
from these IDs. No active DAG, catalog entry, subscription route or real
notification has been added in this draft PR.

## Verified DSH execution receipt

The user requested collaboration with the already-running Pi DeepSeek Harness.
The existing service was reached through the protected production SSH route,
with pinned host-key verification. Normal service launch-link authentication
was used locally; neither the launch link nor authentication cookie was
exported to GitHub, the conversation or the developer environment.

- Run: https://github.com/claude89757/wechat-on-airflow/actions/runs/35050844670
- Job: `104650666039`; sanitized result at `2026-09-16T03:14:10.8704568Z`.
- Session: `dsh-5a8b6fbae1a6497a`.
- Request: `dccea048f9314d968e250d5a258c874a`.
- Actual model: provider `deepseek-official`, model `deepseek-flash`.
- `authenticated=true`, `delegationSubmitted=true`, `status=completed`.
- 19 tool calls; agent research result `partial`, NOT bookability acceptance.
- `externalTestSends=0`, `productionRuntimeChanged=false` in the client report.

Completion was correlated to the unique prompt and its durable turn, model
message and terminal event, not merely a successful HTTP submission. The task
used a dedicated workspace and workspace-write permission. No production
changes, notifications, bookings, payments, CAPTCHA bypass, other-agent-session
access or global model configuration changes were authorized.

The five files reported by the agent remain in its Pi task workspace:
`probe_ydmap.py`, `cdp_probe.py`, `cdp_probe2.py`, `cdp_result.json`,
`cdp_result2.json`. They have NOT been independently retrieved/reviewed by the
coordinator. A follow-up remote artifact reconciliation tool call was blocked
by the platform safety check and was not executed or retried through another
route. Distinguish the agent's observations below from independently reviewed
raw response fixtures.

## Agent findings: useful, but incomplete

The agent reports ordinary Pi GET requests returned HTTP 200 and a 5,592-byte
SPA shell for both sources, with `#app` and JavaScript. This differs from the
GitHub-hosted runner's 170-character/no-script response. The exact cause of
that network-dependent difference is not yet independently established.

Outdoor rendered a schedule table in the first isolated browser attempt.
Product tabs included outdoor, indoor, children's short tennis and covered
courts; the visible date bar included 09-16 and 09-17. This does NOT establish a
permanent two-day booking horizon. The page subsequently presented an Access
Verification / sliding puzzle challenge. The agent reported stopping that path
without solving or bypassing it. It did NOT verify court count, complete JSON
schema, release-state semantics or usable availability.

Indoor remained on the loading placeholder in the agent's attempts; a later
attempt also left outdoor on a loading placeholder. This is an acquisition
failure/unknown state, not zero bookable courts. Agent output uses `court_count=0`
as a placeholder; treat that count as UNKNOWN, not an observed zero.

The following paths were reported from actual outdoor browser requests:

```text
/srv100244/api/pub/sport/venue/getSalesItemList
/srv100244/api/pub/sport/venue/getSportVenueConfig
/srv100244/api/pub/sport/venue/getVenueCalendarList
/srv100244/api/pub/sport/venue/getVenueOrderList
/srv100244/api/pub/sport/venue/getWeather
/srv200/api/pub/basic/getConfig
```

HTTP 200 does not prove JSON success. The agent reports standalone HTTP API
requests encountered WAF HTML rather than usable JSON. Exact request/response
contracts and successful live bookability still require normal authorized
browser access. Do not forge fingerprint headers, synthesize challenge tokens,
bypass CAPTCHA or assume a shard prefix remains fixed.

## Corrected production-access finding

An earlier tunnel preflight returned `JSONDecodeError` for scraper `/healthz`:
https://github.com/claude89757/wechat-on-airflow/actions/runs/35046490262

A later independent direct-Pi check returned HTTP 200, `application/json` and
`ok=true` for `127.0.0.1:8788/healthz`:
https://github.com/claude89757/wechat-on-airflow/actions/runs/35050526213
Job `104649680650`.

Therefore the previous tunnel error must NOT be treated as proof the actual Pi
scraper is down. Health success still does not prove a BAWTT scrape succeeded.
The earlier Host Core/Sender runtime SHA and outbox-health warnings were not
repaired by this task and are outside this venue-query acceptance.

## Implementable next boundary

Use an ordinary authorized browser context to observe the real calendar/order
responses and explicit source/product/date/court identity. On CAPTCHA or login
requirements, report a blocked/unknown state and require normal human/platform
verification rather than an evasion workaround. Do not parse loading/WAF HTML
as availability. Preserve distinct states for usable availability, verified
empty availability and failed/unknown acquisition.

Only after successful response fixtures exist should the Pi scraper gain an
allowlisted source selector, separate indoor/outdoor identities and tested
bookability parsing. Preserve the existing Dashah profile/port/lock behavior;
never run copied services that kill one another's browsers. Do not copy Dashah's
fifth-day noon rule or its emergency six-court full-day heuristic as BAWTT rules.
Use proper URL construction and shell quoting before adding query parameters.

Acceptance still requires source/date mismatch tests, disabled/unreleased and
stale-data rejection, independent target failure handling, timeout/CAPTCHA
handling, real-page comparison without bookings or notifications, full checks,
reviewed exact-SHA deployment and natural successful observation cycles.

## Repository and test state

The original credential-free page probe and its 15 regression tests remain.
GitHub Python 3.12.14 ran those tests successfully in run `35047108939`; both
live page acquisitions failed, which was correctly not treated as empty courts.

Temporary DSH discovery/collaboration workflows and the one-off remote client
are retired from the proposed PR tree after the completed research. Their
historical commits and workflow logs retain evidence. This avoids shipping a
second general-purpose DSH client or permanent diagnostic production entrypoint.
It does not delete the Pi's service, session, private receipts or task files.

The temporary client passed `ruff check`, but its formatting failed CI run
`35050847979`. That temporary file is removed, not exempted from formatting.
Final PR CI must be checked on the new head; no all-green claim is made here.
