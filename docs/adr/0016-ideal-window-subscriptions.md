# ADR 0016: Ideal-window subscriptions

- Status: Accepted
- Date: 2026-10-31

## Context

Subscribers already store one ISO weekday mask and one daily clock window.
`slot_matches` drops email for slots outside that window, while WeChat admission
is only "does this venue have any active subscription?". The product still
presented the window as a secondary time picker and defaulted new reminders
toward a broad evening range on every day.

A later multi-window model would need `time_windows jsonb`. That migration is
not required to make the current single window understandable.

## Decision

Productize the existing columns as named ideal-window presets:

| Preset | Weekdays | Clock | Label |
| --- | --- | --- | --- |
| `weekday_evening` | Monday–Friday | 19:00–22:00 | 下班后打球 |
| `weekday_noon` | Monday–Friday | 12:00–14:00 | 午休局 |
| `weekend_morning` | Saturday–Sunday | 08:00–12:00 | 周末上午 |
| `weekend_afternoon` | Saturday–Sunday | 14:00–18:00 | 周末下午 |
| `custom` | caller-selected | caller-selected | 自定义 |

- Do not add a table or column in this phase. The API accepts optional
  `preferencePreset`, maps a named preset onto `weekdays` / `startTime` /
  `endTime`, and rejects a preset that disagrees with those fields.
- Responses derive `preferencePreset` and `preferenceLabel` from the stored
  window. Historical rows that are not an exact preset stay `custom`. Omitting
  the preset keeps the previous contract, including "missing weekdays means
  every day".
- `PATCH /api/subscriptions/{id}` changes only that window, recomputes the
  existing dedupe key, bumps the venue subscription generation, and cancels
  pending or retry email rows that no longer overlap. Submitted mail and
  WeChat outbox rows are not rewritten. An unchanged window does not bump
  generation.
- Subscriber digests append one note that email was overlap-filtered and that
  WeChat groups remain venue-level. The note is not a slot line and does not
  change the subject count.
- The create form defaults to weekday evening. Covering two presets still means
  two subscriptions.
- WeChat enqueue stays venue-level.

## Consequences

- New subscribers start from a narrower window, so unmatched morning or weekend
  slots no longer become email.
- An explicit "custom" choice whose clock happens to equal a preset is read
  back as that preset, because the label is derived rather than stored.
- Narrowing a window can cancel not-yet-sent email. It does not delete
  `subscription_events`, so those event keys are not sent again if the window
  is later widened.
- In-flight `processing` or `dispatching` rows are not cancelled.
- Multi-window subscriptions, minimum slot length, and WeChat gating by a
  personal window remain out of scope.
