# Manual Refresh and Heartbeat-Free Observation Policy

## Decision

The Web dashboard does not poll for data after its initial load. A new dashboard
read is triggered only by an explicit user refresh or by a user action that
changes server state, such as verification, subscription creation/cancellation,
or priority redemption.

Venue watchers continue to inspect upstream booking systems at their existing
schedules. The change is only about publication into Cloudflare:

- a real availability, health, or error change is published immediately;
- an unchanged observation with no available slots remains on the Airflow host
  after its first successful publication and never emits a timed heartbeat;
- an unchanged observation that still contains available slots performs a cheap
  indexed rematch probe on each natural poll so a newly created subscription can
  match availability that was already open;
- identical failed publications retry no more often than every two minutes;
- Worker-side identical observations are read-only indexed dedupe checks and do
  not update `venue_status` or an observation timestamp.

The available-slot rematch probe is deliberately not a liveness heartbeat. It
exists only for subscription correctness and normally reads one indexed
fingerprint row before returning.

## Health semantics

Without heartbeats, Cloudflare cannot infer that an Airflow watcher is currently
alive from the age of `venue_status.last_inspection_at`. The dashboard therefore
shows the last reported health state and the age of that report. It does not turn
a stable venue red merely because no state change has been published recently.

Operational liveness remains a server concern and is checked through the
protected Airflow health and diagnosis workflows. Clicking refresh in a browser
only rereads stored state; it is not treated as proof that a watcher is running.

## Cost model

For stable empty venues, Cloudflare observation traffic falls to zero after the
initial successful state. Dashboard traffic becomes one request on first load,
plus explicit refreshes and state-changing user actions. Persistent available
slots may still generate indexed rematch probes at the existing watcher cadence,
but they do not re-enter subscription scans or notification writes unless the
Worker fingerprint was invalidated by a subscription change.

The five-minute Worker cron remains because it owns email delivery reconciliation,
subscription gate maintenance, and schema recovery. It is not a venue or browser
heartbeat.

## Correctness contracts

1. No upstream venue polling schedule is reduced.
2. Slot, health, and error changes bypass local dedupe on the first matching poll.
3. Stable empty observations never publish solely because time elapsed.
4. New subscriptions can match already-open availability on the next natural
   available-slot poll.
5. The page never schedules an automatic dashboard refresh.
6. The top refresh control bypasses both client and edge bootstrap caches.
7. Subscription mutations invalidate relevant caches and Worker observation
   fingerprints.
8. No existing subscription, notification, or observation record is deleted.

## Rollback

The previous behavior can be restored by redeploying the prior exact Web and
Airflow commits through the protected component workflows. The local state file
is backward compatible: version 3 reads valid version 2 entries and ignores the
obsolete per-venue heartbeat section. Deleting the file causes the next natural
poll to publish a complete baseline safely.
