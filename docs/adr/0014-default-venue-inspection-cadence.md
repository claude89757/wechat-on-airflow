# ADR 0014: Default Venue Inspection Cadence

- Status: Accepted
- Date: 2026-08-30
- Updated: 2026-09-20 (Shenzhen Bay returns to the one-minute default)

## Context

Most venue adapters previously ran every 30 seconds. That cadence doubled the
number of upstream and public-proxy requests without a corresponding product
requirement, increased contention for the single-device WeChat sender, and made
new integrations likely to copy an unnecessarily aggressive default.

Two integrations have deliberate exceptions. Dashah River free courts use a
15-second low-latency polling requirement. Dashah International Tennis Center
uses a two-minute cadence because each run drives a Raspberry Pi Chromium scrape
and still needs a slower resource-safe interval than ordinary API polling.
Shenzhen Bay's previous 15-second exception was explicitly withdrawn on
2026-09-20; it now follows the one-minute default.

## Decision

- Set the default production tennis-venue inspection cadence to one minute.
- Keep Dashah River free courts at 15 seconds, and Dashah International Tennis
  Center at two minutes.
- Normalize every other active venue DAG, including Shenzhen Bay and Shenzhen
  Sports Center, to `timedelta(minutes=1)` and declare `every_1_minutes` in the
  active-component manifest.
- Keep `max_active_runs=1` so a slow inspection cannot overlap another run of
  the same venue.
- Record the default and approved exceptions in
  `config/venue-schedule-policy.yaml`.
- Require a documented policy exception and regression-test update before any
  future venue uses a cadence other than one minute.
- Enforce the manifest and source schedules in
  `tests/venue_schedule_policy_test.py` without importing Airflow or sending
  notifications.

## Shenzhen Bay Schedule Migration

Deploy the updated Airflow DAG and Web cadence display through the protected
exact-commit release workflow. Preserve `深圳湾网球场巡检`, all four
`check_and_notify_day_*` task IDs, `max_active_runs=1`, and `catchup=False`.
Do not clear historical runs, replay notifications, or change other venues.
After deployment, verify the serialized schedule is one minute, observe three
natural successful runs with one-minute logical intervals, and check that the
Web display reads `1分钟/次`. A reversible cadence rollback restores the
15-second DAG, manifest, policy exception, and Web display together; it must not
replace production databases or replay notification state.

## Consequences

- New venue integrations fail CI when they copy a sub-minute or otherwise
  non-default cadence without an explicit reviewed exception.
- Shenzhen Bay's nominal polling frequency decreases from four runs per minute
  to one; its four-day query coverage and notification behavior are unchanged.
- Dashah River free-court polling makes four checks per minute to reduce latency
  for rapidly released inventory; Dashah International increases from one check
  every three minutes to one every two minutes while remaining serialized.
- A venue run that exceeds its configured interval remains serialized; its
  effective cadence becomes the task duration rather than creating overlapping
  upstream traffic.
