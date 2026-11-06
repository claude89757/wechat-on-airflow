# ADR 0017: Remove named ideal windows

- Status: Accepted
- Date: 2026-11-07
- Supersedes: [ADR 0016](0016-ideal-window-subscriptions.md)

## Context

ADR 0016 layered named presets (工作日晚间, 午休局, 周末上午, 周末下午, 自定义)
on top of the stored weekday mask and daily clock window. The create form then
offered two controls for the same value: 理想时段 and 希望打球的时间段. The owner
asked to remove the former and keep only the latter.

## Decision

- A subscription window is what the user picks: 选择打球星期 plus
  希望打球的时间段. Nothing names or relabels it.
- The create form keeps its previous starting values (Monday–Friday,
  19:00–22:00), now as plain weekday and clock defaults.
- The API no longer reads `preferencePreset` or returns `preferencePreset` and
  `preferenceLabel`. A page opened before this release still posts explicit
  weekdays and clock, so its stray `preferencePreset` is ignored rather than
  rejected. A payload relying on the preset alone now fails validation.
- `PATCH /api/subscriptions/{id}` and the 改成周末上午 list action are removed.
  To change a window, cancel the reminder and create another.

## Consequences

- No schema change or data migration. Stored windows, dedupe keys, and delivery
  history are untouched, and email matching still uses `slot_matches` on the
  stored window. WeChat enqueue stays venue-level.
- Windows can no longer change in place, so nothing new writes
  `ideal_window_changed`. Rows already cancelled with that value keep it as
  history. The ADR 0016 follow-ups about window changes no longer apply.
- A second window remains a second subscription.
