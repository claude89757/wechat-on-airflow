# ADR 0014: Default Venue Inspection Cadence

- Status: Accepted
- Date: 2026-08-30

## Context

Most venue adapters previously ran every 30 seconds. That cadence doubled the
number of upstream and public-proxy requests without a corresponding product
requirement, increased contention for the single-device WeChat sender, and made
new integrations likely to copy an unnecessarily aggressive default.

Two existing integrations have deliberate exceptions. Shenzhen Bay retains its
15-second low-latency polling requirement. Dashah International Tennis Center
retains a three-minute cadence because each run drives a Raspberry Pi Chromium
scrape and needs a slower resource-safe interval.

## Decision

- Set the default production tennis-venue inspection cadence to one minute.
- Keep Shenzhen Bay at 15 seconds and Dashah International Tennis Center at
  three minutes.
- Normalize every other active venue DAG, including Shenzhen Sports Center, to
  `timedelta(minutes=1)` and declare `every_1_minutes` in the active-component
  manifest.
- Keep `max_active_runs=1` so a slow inspection cannot overlap another run of
  the same venue.
- Record the default and approved exceptions in
  `config/venue-schedule-policy.yaml`.
- Require a documented policy exception and regression-test update before any
  future venue uses a cadence other than one minute.
- Enforce the manifest and source schedules in
  `tests/venue_schedule_policy_test.py` without importing Airflow or sending
  notifications.

## Consequences

- New venue integrations fail CI when they copy a sub-minute or otherwise
  non-default cadence without an explicit reviewed exception.
- Existing 30-second venue traffic is reduced by approximately half while the
  two approved latency/resource exceptions remain unchanged.
- A venue run that exceeds one minute remains serialized; its effective cadence
  becomes the task duration rather than creating overlapping upstream traffic.
