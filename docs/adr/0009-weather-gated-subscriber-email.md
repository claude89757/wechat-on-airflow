# ADR 0009: Weather-Gated Subscriber Email

- Status: Accepted
- Date: 2026-08-22

## Context

Subscriber venue reminders consume Tencent SES delivery capacity even when
Shenzhen rain makes outdoor tennis unlikely. The independent WeChat path is
still useful in those conditions and must not be disabled. Email verification
codes are required for account ownership and must also remain available.

A completed same-day rainfall observation is too late for a useful morning
notification decision, so the gate needs the current Shanghai calendar day's
forecast precipitation total. The decision must not turn an external weather
provider outage into silent alert loss.

## Decision

- The Cloudflare Worker evaluates Shenzhen's current-day forecast
  `precipitation_sum` only when eligible subscriber outbox rows exist.
- Open-Meteo is the initial provider because its forecast API exposes daily
  precipitation in millimetres without an API key for non-commercial use.
- The default suppression threshold is `2.5 mm/day`. This is a configurable
  product heuristic, not an official court-playability standard. It avoids
  treating trace drizzle as a shutdown while remaining within the national
  24-hour light-rain band defined by GB/T 28592-2012.
- Forecast precipitation greater than or equal to the threshold changes
  eligible outbox rows to `suppressed`. Those rows are not replayed when a
  later forecast becomes dry because the court-availability event may then be
  stale.
- Weather lookups time out after three seconds, cache successful decisions for
  ten minutes, coalesce concurrent lookups, and fail open on provider or
  parsing errors.
- The gate applies only to subscriber venue-reminder outbox delivery. Email
  verification codes, observation ingestion, and Airflow's independent WeChat
  delivery are unchanged.

## Consequences

- Rainy-day subscriber email volume and Tencent SES cost are reduced without
  reducing WeChat coverage.
- `sent` metrics continue to represent actual provider deliveries;
  weather-suppressed rows use a distinct D1 status and structured log event.
- A weather-provider outage can increase email volume but cannot silently drop
  alerts.
- One Shenzhen-centre forecast controls all subscribed venues, including
  covered courts. This intentionally follows the requested global switch and
  can be refined to venue-specific rules later.
- The free Open-Meteo endpoint is suitable only for non-commercial use and has
  no uptime guarantee. Commercial operation requires a compatible licensed or
  self-hosted source.
