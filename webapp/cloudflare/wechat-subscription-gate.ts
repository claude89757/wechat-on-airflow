import { VENUES, type VenueId } from "./domain";

const GATE_STALE_MS = 10 * 60_000;

export type WeChatVenueGate = {
  allowed: boolean;
  evaluatedAt: string;
  validUntil: string;
  revision: number;
};

type GateRow = {
  allowed: number;
  evaluated_at: number;
  revision: number;
};

type GateEnv = Env & { DB: D1Database };

function activeSubscriptionSql(): string {
  return `SELECT s.venue_ids
            FROM subscriptions s
            LEFT JOIN user_delivery_tiers tiers ON tiers.email = s.email
           WHERE s.active = 1
             AND s.active_until > ?
             AND (
               s.auto_renew = 0
               OR (tiers.tier = 'priority' AND tiers.revoked_at IS NULL)
             )`;
}

export async function refreshWechatVenueGates(
  env: GateEnv,
  now = Date.now(),
): Promise<void> {
  const nowIso = new Date(now).toISOString();
  const rows = (await env.DB.prepare(activeSubscriptionSql())
    .bind(nowIso)
    .all<{ venue_ids: string }>()).results;

  const enabled = new Set<string>();
  for (const row of rows) {
    try {
      const venueIds = JSON.parse(row.venue_ids) as unknown;
      if (!Array.isArray(venueIds)) continue;
      for (const venueId of venueIds) {
        if (typeof venueId === "string" && venueId in VENUES) enabled.add(venueId);
      }
    } catch {
      // Ignore malformed legacy rows; the subscription API always writes valid JSON.
    }
  }

  const revision = now;
  await env.DB.batch(
    (Object.keys(VENUES) as VenueId[]).map((venueId) =>
      env.DB.prepare(
        `INSERT INTO wechat_venue_gates
           (venue_id, allowed, evaluated_at, revision)
         VALUES (?, ?, ?, ?)
         ON CONFLICT(venue_id) DO UPDATE SET
           allowed = excluded.allowed,
           evaluated_at = excluded.evaluated_at,
           revision = excluded.revision`,
      ).bind(venueId, enabled.has(venueId) ? 1 : 0, now, revision)
    ),
  );

  console.log(JSON.stringify({
    event: "wechat_subscription_gates_refreshed",
    activeVenueCount: enabled.size,
    evaluatedAt: nowIso,
  }));
}

export async function wechatGateForVenue(
  env: GateEnv,
  venueId: string,
  now = Date.now(),
): Promise<WeChatVenueGate> {
  if (!(venueId in VENUES)) {
    return {
      allowed: false,
      evaluatedAt: new Date(now).toISOString(),
      validUntil: new Date(now).toISOString(),
      revision: now,
    };
  }

  let row = await env.DB.prepare(
    `SELECT allowed, evaluated_at, revision
       FROM wechat_venue_gates
      WHERE venue_id = ?`,
  ).bind(venueId).first<GateRow>();

  if (!row || now - Number(row.evaluated_at) >= GATE_STALE_MS) {
    await refreshWechatVenueGates(env, now);
    row = await env.DB.prepare(
      `SELECT allowed, evaluated_at, revision
         FROM wechat_venue_gates
        WHERE venue_id = ?`,
    ).bind(venueId).first<GateRow>();
  }

  const evaluatedAt = Number(row?.evaluated_at || now);
  return {
    allowed: Boolean(row?.allowed),
    evaluatedAt: new Date(evaluatedAt).toISOString(),
    validUntil: new Date(evaluatedAt + GATE_STALE_MS).toISOString(),
    revision: Number(row?.revision || evaluatedAt),
  };
}
