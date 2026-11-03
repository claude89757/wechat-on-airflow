# ADR 0014: Default Venue Inspection Cadence

- Status: Accepted
- Date: 2026-08-30
- Updated: 2026-10-20 (CRLand daytime polling and Shenzhen Bay three-day coverage)

## Context

Most venue adapters previously ran every 30 seconds. That cadence doubled the
number of upstream and public-proxy requests without a corresponding product
requirement, increased contention for the single-device WeChat sender, and made
new integrations likely to copy an unnecessarily aggressive default.

Dashah River free courts use a 15-second low-latency polling requirement.
Dashah International Tennis Center
uses a two-minute cadence because each run drives a Raspberry Pi Chromium scrape
and still needs a slower resource-safe interval than ordinary API polling.
Shenzhen Bay's previous 15-second exception was explicitly withdrawn on
2026-09-20, when it returned to the one-minute default. After the three-account
CRLand pool was introduced on 2026-10-19, the user approved lower polling
frequency and a daily active window on 2026-10-20: Shenzhen Bay every two
minutes and Greater Bay Area every three minutes, from 08:00 inclusive to
21:00 exclusive in Asia/Shanghai.
Later the same day, the user explicitly requested removal of Shenzhen Bay's
fourth-day inspection. Its approved coverage is now today and the next two
calendar days; this is a product policy, not an inferred upstream API limit.

## Decision

- Set the default production tennis-venue inspection cadence to one minute.
- Keep Dashah River free courts at 15 seconds, and Dashah International Tennis
  Center at two minutes.
- Set Shenzhen Bay to `timedelta(minutes=2)` / `every_2_minutes`, and Greater
  Bay Area to `timedelta(minutes=3)` / `every_3_minutes`.
- Guard CRLand venue queries with the Asia/Shanghai 08:00–21:00 window at task
  entry, before each upstream attempt, and before final publication. Interval
  runs outside that window retain internal healthy empty observations for
  freshness and stale-availability clearing, without upstream queries or
  reminder attempts.
- Keep every other active venue DAG at `timedelta(minutes=1)` and declare
  `every_1_minutes` in the active-component manifest.
- Keep `max_active_runs=1` so a slow inspection cannot overlap another run of
  the same venue.
- Record the default and approved exceptions in
  `config/venue-schedule-policy.yaml`.
- Require a documented policy exception and regression-test update before any
  future venue uses a cadence other than one minute.
- Enforce the manifest and source schedules in
  `tests/venue_schedule_policy_test.py` without importing Airflow or sending
  notifications.

## CRLand Schedule Migration (2026-10-20)

Deploy the DAG schedules, watcher window guard, and Web cadence labels through
the protected exact-commit Airflow and Web release workflows. Preserve
`深圳湾网球场巡检` and `大湾区网球场巡检`, each with the existing
`check_and_notify_day_0` through `check_and_notify_day_2` task IDs,
`max_active_runs=1`, and `catchup=False`. Retire Shenzhen Bay's
`check_and_notify_day_3` from the DAG, active manifest and bounded diagnosis.
Keep historical runs and failures, booking areas, and notification rules.

Rotate the three shared accounts independently by each venue's scheduled
round: `floor(scheduled_timestamp / (interval_minutes * 60)) % 3`. This
advances the selected account on every two- or three-minute interval and keeps
date tasks, booking areas, delayed execution, and retries consistent within a
venue round. It uses no daily reset or mutable counter.

After deployment, verify the serialized 120- and 180-second schedules and Web
labels `2分钟/次` and `3分钟/次`. Observe three successful natural polling
rounds per venue inside the active window, including the scheduled intervals
and all three account slots. Off-hours no-query successes alone do not prove
polling acceptance. Use clock-controlled checks for the inclusive 08:00 and
exclusive 21:00 boundaries, including a round that crosses closing time and
discards partial results. Future cadence changes must update the DAGs,
manifest, policy, rotation interval, and Web labels together.

## Consequences

- New venue integrations fail CI when they copy a sub-minute or otherwise
  non-default cadence without an explicit reviewed exception.
- Shenzhen Bay and Greater Bay Area make venue queries less frequently and
  only during the active window. Both inspect today and the next two calendar
  days; notification eligibility rules are unchanged.
- Dashah River free-court polling remains at four checks per minute to reduce
  latency for rapidly released inventory; Dashah International remains at one
  check every two minutes while staying serialized.
- A venue run that exceeds its configured interval remains serialized; its
  effective cadence becomes the task duration rather than creating overlapping
  upstream traffic.
