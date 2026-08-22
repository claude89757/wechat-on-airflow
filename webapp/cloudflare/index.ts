import {
  VENUES,
  activeUntilIso,
  formatNotificationDigest,
  formatSlotLine,
  maskEmail,
  normalizeEmail,
  randomToken,
  randomVerificationCode,
  sha256Hex,
  slotMatchesTimeRange,
  validateSlotObservation,
  validateSubscriptionInput,
  type SlotObservation,
  type VenueId,
} from "./domain";
import {
  deliveryLimitForTier,
  normalizeDeliveryTier,
  remainingDailyDeliveries,
  type DeliveryTier,
} from "./delivery-tiers";
import {
  generateInviteCode,
  hashInviteCode,
  normalizeInviteCode,
} from "./invite-codes";
import { sendTencentTemplateEmail } from "./tencent-ses";
import { evaluateWeatherEmailGate } from "./weather-email-gate";

type WorkerSecrets = {
  TENCENT_SECRET_ID: string;
  TENCENT_SECRET_KEY: string;
  EMAIL_FROM_ADDRESS: string;
  EMAIL_REPLY_TO: string;
  EMAIL_TEMPLATE_ID: string;
  VERIFICATION_PEPPER: string;
  AIRFLOW_PUSH_TOKEN: string;
  NOTIFICATION_DAILY_SEND_LIMIT: string;
  WEATHER_EMAIL_GATE_ENABLED?: string;
  WEATHER_EMAIL_PRECIPITATION_THRESHOLD_MM?: string;
  WEATHER_EMAIL_GATE_LATITUDE?: string;
  WEATHER_EMAIL_GATE_LONGITUDE?: string;
  STANDARD_DAILY_EMAIL_LIMIT?: string;
  PRIORITY_DAILY_EMAIL_LIMIT?: string;
  INVITE_CODE_PEPPER: string;
  INVITE_ADMIN_TOKEN: string;
};

type WorkerEnv = Env & WorkerSecrets;

type Identity = {
  email: string;
  maskedEmail: string;
};

type VenueStatusRow = {
  venue_id: VenueId;
  venue_name: string;
  healthy: number;
  last_inspection_at: string | null;
  last_notification_at: string | null;
  subscriber_count: number;
};

type SubscriptionRow = {
  id: string;
  email: string;
  venue_ids: string;
  start_time: string;
  end_time: string;
  duration_days: number;
  active_until: string;
  active: number;
  created_at: string;
};

type OutboxRow = {
  id: string;
  email: string;
  subject: string;
  body: string;
  venue_id: VenueId;
  attempt_count: number;
  tier: DeliveryTier;
};

const JSON_HEADERS = {
  "Cache-Control": "no-store",
  "Content-Type": "application/json; charset=utf-8",
};
const MAX_JSON_BYTES = 32_768;
const RECEIPT_LIFETIME_MS = 180 * 86_400_000;
const CHALLENGE_LIFETIME_MS = 10 * 60_000;
const INSPECTION_FRESHNESS_MS = 10 * 60_000;
const MAX_OUTBOX_BATCH_ROWS = 100;
const DELIVERY_RESERVATION_LIFETIME_MS = 10 * 60_000;
const INVITE_ATTEMPT_WINDOW_MS = 60 * 60_000;
const INVITE_EMAIL_ATTEMPT_LIMIT = 10;
const INVITE_IP_ATTEMPT_LIMIT = 30;
const MAX_INVITES_PER_ADMIN_REQUEST = 25;

function json(data: unknown, status = 200): Response {
  return Response.json(data, { status, headers: JSON_HEADERS });
}

function errorResponse(error: unknown, status = 400): Response {
  return json(
    { error: error instanceof Error ? error.message : "请求处理失败" },
    status,
  );
}

async function readJson(request: Request): Promise<unknown> {
  const declaredLength = Number(request.headers.get("content-length") || 0);
  if (declaredLength > MAX_JSON_BYTES) {
    throw new Error("请求内容过大");
  }
  const text = await request.text();
  if (new TextEncoder().encode(text).byteLength > MAX_JSON_BYTES) {
    throw new Error("请求内容过大");
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new Error("请求格式无效");
  }
}

function requestToken(request: Request): string | null {
  const authorization = request.headers.get("authorization") || "";
  return authorization.startsWith("Bearer ") ? authorization.slice(7).trim() : null;
}

function constantTimeEqual(left: string, right: string): boolean {
  const encoder = new TextEncoder();
  const leftBytes = encoder.encode(left);
  const rightBytes = encoder.encode(right);
  if (leftBytes.byteLength !== rightBytes.byteLength) return false;
  let difference = 0;
  for (let index = 0; index < leftBytes.byteLength; index += 1) {
    difference |= leftBytes[index] ^ rightBytes[index];
  }
  return difference === 0;
}

async function getIdentity(request: Request, env: WorkerEnv): Promise<Identity | null> {
  const token = requestToken(request);
  if (!token) return null;

  const now = Date.now();
  const tokenHash = await sha256Hex(token);
  const receipt = await env.DB.prepare(
    `SELECT email, masked_email
       FROM verified_receipts
      WHERE token_hash = ?
        AND expires_at > ?
        AND revoked_at IS NULL`,
  ).bind(tokenHash, now).first<{ email: string; masked_email: string }>();
  if (!receipt) return null;

  await env.DB.prepare(
    "UPDATE verified_receipts SET last_used_at = ? WHERE token_hash = ?",
  ).bind(now, tokenHash).run();
  return { email: receipt.email, maskedEmail: receipt.masked_email };
}

function shanghaiDayStart(now = new Date()): string {
  const shifted = new Date(now.getTime() + 8 * 3_600_000);
  return new Date(
    Date.UTC(
      shifted.getUTCFullYear(),
      shifted.getUTCMonth(),
      shifted.getUTCDate(),
    ) - 8 * 3_600_000,
  ).toISOString();
}

async function bootstrap(request: Request, env: WorkerEnv): Promise<Response> {
  const identity = await getIdentity(request, env);
  const now = new Date();
  const nowIso = now.toISOString();
  const dayStart = shanghaiDayStart(now);

  const statements = [
    env.DB.prepare(
      "SELECT COUNT(*) AS count FROM subscriptions WHERE active = 1 AND active_until > ?",
    ).bind(nowIso),
    env.DB.prepare(
      "SELECT COUNT(DISTINCT message_id) AS count FROM notification_outbox WHERE status = 'sent' AND sent_at >= ?",
    ).bind(dayStart),
    env.DB.prepare(
      `SELECT
         v.venue_id,
         v.venue_name,
         v.healthy,
         v.last_inspection_at,
         v.last_notification_at,
         (
           SELECT COUNT(*)
             FROM subscriptions s, json_each(s.venue_ids) selected
            WHERE s.active = 1
              AND s.active_until > ?
              AND selected.value = v.venue_id
         ) AS subscriber_count
       FROM venue_status v
       ORDER BY v.last_inspection_at DESC, v.venue_id`,
    ).bind(nowIso),
  ];
  if (identity) {
    statements.push(
      env.DB.prepare(
        `SELECT id, email, venue_ids, start_time, end_time, duration_days,
                active_until, active, created_at
           FROM subscriptions
          WHERE email = ? AND active = 1 AND active_until > ?
          ORDER BY created_at DESC`,
      ).bind(identity.email, nowIso),
      env.DB.prepare(
        `SELECT COUNT(DISTINCT message_id) AS count
           FROM notification_outbox
          WHERE email = ?
            AND status = 'sent'
            AND sent_at >= ?`,
      ).bind(identity.email, dayStart),
      env.DB.prepare(
        `SELECT tier
           FROM user_delivery_tiers
          WHERE email = ?
            AND revoked_at IS NULL`,
      ).bind(identity.email),
    );
  }

  const results = await env.DB.batch(statements);
  const activeSubscriptions = Number(
    (results[0].results[0] as { count?: number } | undefined)?.count || 0,
  );
  const remindersToday = Number(
    (results[1].results[0] as { count?: number } | undefined)?.count || 0,
  );
  const venueRows = results[2].results as unknown as VenueStatusRow[];
  const venues = venueRows.map((venue) => ({
    id: venue.venue_id,
    name: venue.venue_name,
    healthy:
      Boolean(venue.healthy)
      && Boolean(venue.last_inspection_at)
      && Date.parse(venue.last_inspection_at || "") >= now.getTime() - INSPECTION_FRESHNESS_MS,
    subscriberCount: Number(venue.subscriber_count || 0),
    lastInspectionAt: venue.last_inspection_at,
    lastNotificationAt: venue.last_notification_at,
  }));
  const subscriptionRows = identity
    ? (results[3].results as unknown as SubscriptionRow[])
    : [];
  const identityRemindersToday = identity
    ? Number(
      (results[4].results[0] as { count?: number } | undefined)?.count || 0,
    )
    : 0;
  const identityTier = identity
    ? normalizeDeliveryTier(
      (results[5].results[0] as { tier?: string } | undefined)?.tier,
    )
    : "standard";
  const identityDailyLimit = deliveryLimitForTier(env, identityTier);

  return json({
    generatedAt: nowIso,
    metrics: {
      activeSubscriptions,
      remindersToday,
      healthyVenues: venues.filter((venue) => venue.healthy).length,
      totalVenues: venues.length,
    },
    venues,
    identity: {
      verified: Boolean(identity),
      maskedEmail: identity?.maskedEmail ?? null,
      remindersToday: identityRemindersToday,
      tier: identityTier,
      dailyLimit: identityDailyLimit,
      remainingToday: remainingDailyDeliveries(
        identityRemindersToday,
        identityDailyLimit,
      ),
    },
    subscriptions: subscriptionRows.map((subscription) => ({
      id: subscription.id,
      venueIds: JSON.parse(subscription.venue_ids),
      startTime: subscription.start_time,
      endTime: subscription.end_time,
      durationDays: subscription.duration_days,
      activeUntil: subscription.active_until,
      active: Boolean(subscription.active),
      createdAt: subscription.created_at,
    })),
  });
}

async function sendVerificationCode(request: Request, env: WorkerEnv): Promise<Response> {
  const payload = await readJson(request);
  const email = normalizeEmail(
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>).email
      : null,
  );
  const now = Date.now();
  const since = now - 3_600_000;
  const ip = request.headers.get("cf-connecting-ip") || "unknown";
  const ipHash = await sha256Hex(`${ip}:${env.VERIFICATION_PEPPER}`);

  const rateLimits = await env.DB.batch([
    env.DB.prepare(
      "SELECT COUNT(*) AS count FROM verification_challenges WHERE email = ? AND created_at >= ?",
    ).bind(email, since),
    env.DB.prepare(
      "SELECT COUNT(*) AS count FROM verification_challenges WHERE ip_hash = ? AND created_at >= ?",
    ).bind(ipHash, since),
  ]);
  const emailCount = Number(
    (rateLimits[0].results[0] as { count?: number } | undefined)?.count || 0,
  );
  const ipCount = Number(
    (rateLimits[1].results[0] as { count?: number } | undefined)?.count || 0,
  );
  if (emailCount >= 5 || ipCount >= 10) {
    return errorResponse(new Error("验证码发送过于频繁，请稍后再试"), 429);
  }

  const challengeId = crypto.randomUUID();
  const code = randomVerificationCode();
  const codeHash = await sha256Hex(`${challengeId}:${code}:${env.VERIFICATION_PEPPER}`);
  await env.DB.prepare(
    `INSERT INTO verification_challenges
       (id, email, code_hash, ip_hash, expires_at, attempts, created_at)
     VALUES (?, ?, ?, ?, ?, 0, ?)`,
  ).bind(challengeId, email, codeHash, ipHash, now + CHALLENGE_LIFETIME_MS, now).run();

  try {
    await sendTencentTemplateEmail(
      env,
      email,
      "网球订阅邮箱验证码",
      `验证码：${code}\n10 分钟内有效。`,
      "邮箱验证",
    );
  } catch (error) {
    await env.DB.prepare("DELETE FROM verification_challenges WHERE id = ?")
      .bind(challengeId)
      .run();
    console.error(JSON.stringify({
      event: "verification_email_failed",
      reason: error instanceof Error ? error.message.slice(0, 200) : "unknown",
    }));
    return errorResponse(new Error("验证码发送失败，请稍后重试"), 502);
  }

  return json({ challengeId, expiresInSeconds: CHALLENGE_LIFETIME_MS / 1000 });
}

async function verifyEmail(request: Request, env: WorkerEnv): Promise<Response> {
  const payload = await readJson(request);
  const candidate = payload && typeof payload === "object"
    ? payload as Record<string, unknown>
    : {};
  const challengeId = String(candidate.challengeId || "");
  const code = String(candidate.code || "");
  if (!/^[0-9a-f-]{36}$/i.test(challengeId) || !/^\d{6}$/.test(code)) {
    throw new Error("验证码无效");
  }

  const now = Date.now();
  const challenge = await env.DB.prepare(
    `SELECT email, code_hash, expires_at, attempts, consumed_at
       FROM verification_challenges
      WHERE id = ?`,
  ).bind(challengeId).first<{
    email: string;
    code_hash: string;
    expires_at: number;
    attempts: number;
    consumed_at: number | null;
  }>();
  if (
    !challenge
    || challenge.consumed_at
    || challenge.expires_at <= now
    || challenge.attempts >= 5
  ) {
    throw new Error("验证码已失效，请重新获取");
  }

  const suppliedHash = await sha256Hex(
    `${challengeId}:${code}:${env.VERIFICATION_PEPPER}`,
  );
  if (!constantTimeEqual(suppliedHash, challenge.code_hash)) {
    await env.DB.prepare(
      "UPDATE verification_challenges SET attempts = attempts + 1 WHERE id = ?",
    ).bind(challengeId).run();
    throw new Error("验证码不正确");
  }

  const token = randomToken();
  const tokenHash = await sha256Hex(token);
  const maskedEmail = maskEmail(challenge.email);
  const consumed = await env.DB.prepare(
    `UPDATE verification_challenges
        SET consumed_at = ?
      WHERE id = ? AND consumed_at IS NULL`,
  ).bind(now, challengeId).run();
  if (!consumed.meta.changes) throw new Error("验证码已失效，请重新获取");
  await env.DB.prepare(
    `INSERT INTO verified_receipts
       (token_hash, email, masked_email, expires_at, last_used_at, created_at)
     VALUES (?, ?, ?, ?, ?, ?)`,
  ).bind(tokenHash, challenge.email, maskedEmail, now + RECEIPT_LIFETIME_MS, now, now).run();

  return json({
    token,
    email: challenge.email,
    maskedEmail,
    verifiedAt: new Date(now).toISOString(),
  });
}

async function createSubscription(request: Request, env: WorkerEnv): Promise<Response> {
  const identity = await getIdentity(request, env);
  if (!identity) return errorResponse(new Error("请先验证邮箱"), 401);

  const input = validateSubscriptionInput(await readJson(request));
  const now = new Date();
  const subscription = {
    id: crypto.randomUUID(),
    venueIds: input.venueIds,
    startTime: input.startTime,
    endTime: input.endTime,
    durationDays: input.durationDays,
    activeUntil: activeUntilIso(input.durationDays, now),
    active: true,
    createdAt: now.toISOString(),
  };
  await env.DB.prepare(
    `INSERT INTO subscriptions
       (id, email, venue_ids, start_time, end_time, duration_days,
        active_until, active, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)`,
  ).bind(
    subscription.id,
    identity.email,
    JSON.stringify(subscription.venueIds),
    subscription.startTime,
    subscription.endTime,
    subscription.durationDays,
    subscription.activeUntil,
    subscription.createdAt,
    subscription.createdAt,
  ).run();
  return json({ subscription }, 201);
}

async function cancelSubscription(
  request: Request,
  env: WorkerEnv,
  subscriptionId: string,
): Promise<Response> {
  const identity = await getIdentity(request, env);
  if (!identity) return errorResponse(new Error("请先验证邮箱"), 401);
  const nowIso = new Date().toISOString();
  const result = await env.DB.prepare(
    `UPDATE subscriptions
        SET active = 0, updated_at = ?
      WHERE id = ? AND email = ? AND active = 1`,
  ).bind(nowIso, subscriptionId, identity.email).run();
  if (!result.meta.changes) return errorResponse(new Error("订阅不存在"), 404);
  return json({ success: true });
}

async function recordInviteAttempt(
  env: WorkerEnv,
  email: string,
  ipHash: string,
  success: boolean,
  now: number,
): Promise<void> {
  await env.DB.prepare(
    `INSERT INTO priority_invite_attempts
       (id, email, ip_hash, success, created_at)
     VALUES (?, ?, ?, ?, ?)`,
  ).bind(crypto.randomUUID(), email, ipHash, success ? 1 : 0, now).run();
}

async function redeemPriorityInvite(
  request: Request,
  env: WorkerEnv,
): Promise<Response> {
  const identity = await getIdentity(request, env);
  if (!identity) return errorResponse(new Error("请先验证邮箱"), 401);

  const now = Date.now();
  const existingPriority = await env.DB.prepare(
    `SELECT tier
       FROM user_delivery_tiers
      WHERE email = ?
        AND tier = 'priority'
        AND revoked_at IS NULL`,
  ).bind(identity.email).first<{ tier: string }>();
  if (existingPriority) {
    const tier: DeliveryTier = "priority";
    const dailyLimit = deliveryLimitForTier(env, tier);
    const dayStart = shanghaiDayStart(new Date(now));
    const sent = await env.DB.prepare(
      `SELECT COUNT(DISTINCT message_id) AS count
         FROM notification_outbox
        WHERE email = ?
          AND status = 'sent'
          AND sent_at >= ?`,
    ).bind(identity.email, dayStart).first<{ count: number }>();
    const remindersToday = Number(sent?.count || 0);
    return json({
      success: true,
      alreadyPriority: true,
      tier,
      dailyLimit,
      remindersToday,
      remainingToday: remainingDailyDeliveries(remindersToday, dailyLimit),
    });
  }

  const payload = await readJson(request);
  const rawCode = payload && typeof payload === "object"
    ? (payload as Record<string, unknown>).code
    : null;
  const since = now - INVITE_ATTEMPT_WINDOW_MS;
  const ip = request.headers.get("cf-connecting-ip") || "unknown";
  const ipHash = await sha256Hex(`${ip}:${env.INVITE_CODE_PEPPER}`);
  const limits = await env.DB.batch([
    env.DB.prepare(
      `SELECT COUNT(*) AS count
         FROM priority_invite_attempts
        WHERE email = ?
          AND created_at >= ?`,
    ).bind(identity.email, since),
    env.DB.prepare(
      `SELECT COUNT(*) AS count
         FROM priority_invite_attempts
        WHERE ip_hash = ?
          AND created_at >= ?`,
    ).bind(ipHash, since),
  ]);
  const emailAttempts = Number(
    (limits[0].results[0] as { count?: number } | undefined)?.count || 0,
  );
  const ipAttempts = Number(
    (limits[1].results[0] as { count?: number } | undefined)?.count || 0,
  );
  if (
    emailAttempts >= INVITE_EMAIL_ATTEMPT_LIMIT
    || ipAttempts >= INVITE_IP_ATTEMPT_LIMIT
  ) {
    return errorResponse(new Error("邀请码验证过于频繁，请稍后再试"), 429);
  }

  let code: string;
  try {
    code = normalizeInviteCode(rawCode);
  } catch (error) {
    await recordInviteAttempt(env, identity.email, ipHash, false, now);
    throw error;
  }
  const codeHash = await hashInviteCode(code, env.INVITE_CODE_PEPPER);
  const redemptionId = crypto.randomUUID();
  const result = await env.DB.batch([
    env.DB.prepare(
      `UPDATE priority_invite_codes
          SET redeemed_by = ?, redeemed_at = ?, redemption_id = ?
        WHERE code_hash = ?
          AND active = 1
          AND redeemed_by IS NULL
          AND expires_at > ?`,
    ).bind(identity.email, now, redemptionId, codeHash, now),
    env.DB.prepare(
      `INSERT INTO user_delivery_tiers
         (email, tier, source_invite_id, created_at, updated_at, revoked_at)
       SELECT ?, 'priority', id, ?, ?, NULL
         FROM priority_invite_codes
        WHERE redemption_id = ?
          AND redeemed_by = ?
       ON CONFLICT(email) DO UPDATE SET
         tier = 'priority',
         source_invite_id = excluded.source_invite_id,
         updated_at = excluded.updated_at,
         revoked_at = NULL`,
    ).bind(identity.email, now, now, redemptionId, identity.email),
  ]);
  const redeemed = Number(result[0].meta.changes || 0) === 1
    && Number(result[1].meta.changes || 0) >= 1;
  await recordInviteAttempt(env, identity.email, ipHash, redeemed, now);
  if (!redeemed) {
    return errorResponse(new Error("邀请码无效、已过期或已被使用"), 400);
  }

  const tier: DeliveryTier = "priority";
  const dailyLimit = deliveryLimitForTier(env, tier);
  const dayStart = shanghaiDayStart(new Date(now));
  const sent = await env.DB.prepare(
    `SELECT COUNT(DISTINCT message_id) AS count
       FROM notification_outbox
      WHERE email = ?
        AND status = 'sent'
        AND sent_at >= ?`,
  ).bind(identity.email, dayStart).first<{ count: number }>();
  const remindersToday = Number(sent?.count || 0);
  console.log(JSON.stringify({
    event: "priority_invite_redeemed",
    tier,
    dailyLimit,
  }));
  return json({
    success: true,
    tier,
    dailyLimit,
    remindersToday,
    remainingToday: remainingDailyDeliveries(remindersToday, dailyLimit),
  });
}

function positiveIntegerInput(
  value: unknown,
  fallback: number,
  maximum: number,
): number {
  const candidate = Number(value);
  return Number.isInteger(candidate) && candidate > 0
    ? Math.min(candidate, maximum)
    : fallback;
}

async function createPriorityInvites(
  request: Request,
  env: WorkerEnv,
): Promise<Response> {
  const token = requestToken(request);
  if (
    !token
    || !env.INVITE_ADMIN_TOKEN
    || !constantTimeEqual(token, env.INVITE_ADMIN_TOKEN)
  ) {
    return errorResponse(new Error("未授权"), 401);
  }
  const payload = await readJson(request);
  const candidate = payload && typeof payload === "object"
    ? payload as Record<string, unknown>
    : {};
  const count = positiveIntegerInput(
    candidate.count,
    1,
    MAX_INVITES_PER_ADMIN_REQUEST,
  );
  const expiresInDays = positiveIntegerInput(candidate.expiresInDays, 30, 90);
  const note = candidate.note ? String(candidate.note).slice(0, 120) : null;
  const now = Date.now();
  const expiresAt = now + expiresInDays * 86_400_000;
  const codes: string[] = [];
  const inserts: D1PreparedStatement[] = [];
  for (let index = 0; index < count; index += 1) {
    const code = generateInviteCode();
    codes.push(code);
    inserts.push(
      env.DB.prepare(
        `INSERT INTO priority_invite_codes
           (id, code_hash, expires_at, active, note, created_at)
         VALUES (?, ?, ?, 1, ?, ?)`,
      ).bind(
        crypto.randomUUID(),
        await hashInviteCode(code, env.INVITE_CODE_PEPPER),
        expiresAt,
        note,
        now,
      ),
    );
  }
  await env.DB.batch(inserts);
  console.log(JSON.stringify({
    event: "priority_invites_created",
    count,
    expiresAt: new Date(expiresAt).toISOString(),
  }));
  return json({
    codes,
    count,
    expiresAt: new Date(expiresAt).toISOString(),
  }, 201);
}

async function authorizeAirflow(request: Request, env: WorkerEnv): Promise<boolean> {
  const token = requestToken(request);
  return Boolean(token) && constantTimeEqual(token || "", env.AIRFLOW_PUSH_TOKEN);
}

function parseObservationPayload(value: unknown): {
  venueId: VenueId;
  venueName: string;
  healthy: boolean;
  checkedAt: string;
  error: string | null;
  slots: SlotObservation[];
} {
  if (!value || typeof value !== "object") throw new Error("巡检数据无效");
  const candidate = value as Record<string, unknown>;
  const venueId = String(candidate.venue_id || candidate.venueId || "") as VenueId;
  if (!(venueId in VENUES)) throw new Error("场地编号无效");
  const venueName = String(candidate.venue_name || candidate.venueName || VENUES[venueId]);
  if (venueName !== VENUES[venueId]) throw new Error("场地名称无效");
  const checkedAt = String(candidate.checked_at || candidate.checkedAt || "");
  if (
    !checkedAt
    || !Number.isFinite(Date.parse(checkedAt))
    || Math.abs(Date.now() - Date.parse(checkedAt)) > 86_400_000
  ) {
    throw new Error("巡检时间无效");
  }
  const values = candidate.slots;
  if (!Array.isArray(values) || values.length > 200) {
    throw new Error("场地时段数量无效");
  }
  return {
    venueId,
    venueName,
    healthy: candidate.healthy === true,
    checkedAt: new Date(checkedAt).toISOString(),
    error: candidate.error ? String(candidate.error).slice(0, 300) : null,
    slots: values.map(validateSlotObservation),
  };
}

async function ingestObservation(
  request: Request,
  env: WorkerEnv,
  context: ExecutionContext,
): Promise<Response> {
  if (!(await authorizeAirflow(request, env))) {
    return errorResponse(new Error("未授权"), 401);
  }
  const observation = parseObservationPayload(await readJson(request));
  const now = new Date();
  const nowIso = now.toISOString();
  const statements: D1PreparedStatement[] = [
    env.DB.prepare(
      `INSERT INTO venue_status
         (venue_id, venue_name, healthy, last_inspection_at, last_error, updated_at)
       VALUES (?, ?, ?, ?, ?, ?)
       ON CONFLICT(venue_id) DO UPDATE SET
         venue_name = excluded.venue_name,
         healthy = excluded.healthy,
         last_inspection_at = excluded.last_inspection_at,
         last_error = excluded.last_error,
         updated_at = excluded.updated_at`,
    ).bind(
      observation.venueId,
      observation.venueName,
      observation.healthy ? 1 : 0,
      observation.checkedAt,
      observation.error,
      nowIso,
    ),
  ];

  const subscriptions = observation.healthy
    ? (
      await env.DB.prepare(
        `SELECT id, email, venue_ids, start_time, end_time, duration_days,
                active_until, active, created_at
           FROM subscriptions
          WHERE active = 1 AND active_until > ?`,
      ).bind(nowIso).all<SubscriptionRow>()
    ).results.filter((subscription) =>
      (JSON.parse(subscription.venue_ids) as string[]).includes(observation.venueId)
    )
    : [];

  let matchedNotifications = 0;
  for (const slot of observation.slots) {
    const eventKey = await sha256Hex([
      observation.venueId,
      slot.date,
      slot.courtName,
      slot.startTime,
      slot.endTime,
    ].join("|"));
    statements.push(
      env.DB.prepare(
        `INSERT INTO observed_slots
           (event_key, venue_id, court_name, booking_date, start_time, end_time,
            first_observed_at, last_observed_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(event_key) DO UPDATE SET last_observed_at = excluded.last_observed_at`,
      ).bind(
        eventKey,
        observation.venueId,
        slot.courtName,
        slot.date,
        slot.startTime,
        slot.endTime,
        nowIso,
        nowIso,
      ),
    );

    for (const subscription of subscriptions) {
      if (!slotMatchesTimeRange(slot, subscription.start_time, subscription.end_time)) continue;
      if (matchedNotifications >= 500) break;
      const line = formatSlotLine(observation.venueName, slot);
      const outboxId = crypto.randomUUID();
      statements.push(
        env.DB.prepare(
          `INSERT OR IGNORE INTO subscription_events
             (subscription_id, event_key, created_at)
           VALUES (?, ?, ?)`,
        ).bind(subscription.id, eventKey, nowIso),
        env.DB.prepare(
          `INSERT OR IGNORE INTO notification_outbox
             (id, subscription_id, event_key, venue_id, email, subject, body,
              status, attempt_count, next_attempt_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)`,
        ).bind(
          outboxId,
          subscription.id,
          eventKey,
          observation.venueId,
          subscription.email,
          line,
          line,
          now.getTime(),
          nowIso,
        ),
      );
      matchedNotifications += 1;
    }
  }

  await env.DB.batch(statements);
  context.waitUntil(drainOutbox(env));
  console.log(JSON.stringify({
    event: "venue_observation_ingested",
    venueId: observation.venueId,
    healthy: observation.healthy,
    slotCount: observation.slots.length,
    matchedNotifications,
  }));
  return json({
    success: true,
    venueId: observation.venueId,
    slotsAccepted: observation.slots.length,
  });
}

function retryDelayMs(attempt: number): number {
  return Math.min(60 * 60_000, 60_000 * 2 ** Math.max(0, attempt - 1));
}

async function drainOutbox(env: WorkerEnv): Promise<void> {
  const now = Date.now();
  const pending = (
    await env.DB.prepare(
      `SELECT
         outbox.id,
         outbox.email,
         outbox.subject,
         outbox.body,
         outbox.venue_id,
         outbox.attempt_count,
         CASE
           WHEN tiers.tier = 'priority' AND tiers.revoked_at IS NULL
             THEN 'priority'
           ELSE 'standard'
         END AS tier
         FROM notification_outbox outbox
         LEFT JOIN user_delivery_tiers tiers ON tiers.email = outbox.email
        WHERE outbox.status IN ('pending', 'retry', 'processing')
          AND outbox.next_attempt_at <= ?
        ORDER BY
          CASE
            WHEN tiers.tier = 'priority' AND tiers.revoked_at IS NULL THEN 0
            ELSE 1
          END,
          outbox.created_at
        LIMIT ?`,
    ).bind(now, MAX_OUTBOX_BATCH_ROWS).all<OutboxRow>()
  ).results;
  if (!pending.length) return;

  const weather = await evaluateWeatherEmailGate(env);
  if (!weather.sendEmail) {
    const suppressionReason = [
      "weather_suppressed",
      weather.forecastDate || "unknown-date",
      `${weather.precipitationMm ?? "unknown"}mm`,
      `threshold=${weather.thresholdMm}mm`,
    ].join(":");
    const results = await env.DB.batch(pending.map((item) =>
      env.DB.prepare(
        `UPDATE notification_outbox
            SET status = 'suppressed', next_attempt_at = ?, last_error = ?
          WHERE id = ?
            AND status IN ('pending', 'retry', 'processing')
            AND next_attempt_at <= ?`,
      ).bind(now, suppressionReason, item.id, now)
    ));
    const itemCount = results.reduce(
      (count, result) => count + Number(result.meta.changes || 0),
      0,
    );
    console.log(JSON.stringify({
      event: "notification_weather_suppressed",
      forecastDate: weather.forecastDate,
      precipitationMm: weather.precipitationMm,
      thresholdMm: weather.thresholdMm,
      itemCount,
    }));
    return;
  }
  if (weather.reason === "weather_unavailable") {
    console.warn(JSON.stringify({
      event: "notification_weather_gate_fail_open",
      forecastDate: weather.forecastDate,
      thresholdMm: weather.thresholdMm,
      reason: weather.error,
    }));
  }

  const dayStart = shanghaiDayStart(new Date(now));
  const configuredLimit = Number(env.NOTIFICATION_DAILY_SEND_LIMIT);
  const dailyLimit = Number.isInteger(configuredLimit) && configuredLimit > 0
    ? configuredLimit
    : 1_000;
  const deliveryCountRow = await env.DB.prepare(
    `SELECT COUNT(DISTINCT message_id) AS count
       FROM notification_outbox
      WHERE status = 'sent' AND sent_at >= ?`,
  ).bind(dayStart).first<{ count: number }>();
  const remainingDeliveries = Math.max(0, dailyLimit - Number(deliveryCountRow?.count || 0));
  if (!remainingDeliveries) {
    console.log(JSON.stringify({ event: "notification_daily_budget_reserved", dailyLimit }));
    return;
  }

  const grouped = new Map<string, OutboxRow[]>();
  for (const item of pending) {
    const rows = grouped.get(item.email) || [];
    rows.push(item);
    grouped.set(item.email, rows);
  }

  let deliveredGroups = 0;
  const deliveryDay = new Date(now + 8 * 3_600_000).toISOString().slice(0, 10);
  for (const rows of grouped.values()) {
    if (deliveredGroups >= remainingDeliveries) break;
    const claimed: OutboxRow[] = [];
    for (const item of rows) {
      const attempt = item.attempt_count + 1;
      const lease = await env.DB.prepare(
        `UPDATE notification_outbox
            SET status = 'processing', attempt_count = ?, next_attempt_at = ?
          WHERE id = ?
            AND status IN ('pending', 'retry', 'processing')
            AND next_attempt_at <= ?`,
      ).bind(attempt, now + 5 * 60_000, item.id, now).run();
      if (lease.meta.changes) claimed.push(item);
    }
    if (!claimed.length) continue;

    const tier = claimed[0].tier;
    const dailyLimit = deliveryLimitForTier(env, tier);
    const deliveryClaimId = crypto.randomUUID();
    const reservation = await env.DB.prepare(
      `INSERT INTO email_delivery_claims
         (id, email, delivery_day, status, message_id, created_at, updated_at)
       SELECT ?, ?, ?, 'reserved', NULL, ?, ?
        WHERE (
          SELECT COUNT(DISTINCT message_id)
            FROM notification_outbox
           WHERE email = ?
             AND status = 'sent'
             AND sent_at >= ?
        ) + (
          SELECT COUNT(*)
            FROM email_delivery_claims
           WHERE email = ?
             AND delivery_day = ?
             AND status = 'reserved'
             AND updated_at >= ?
        ) < ?`,
    ).bind(
      deliveryClaimId,
      claimed[0].email,
      deliveryDay,
      now,
      now,
      claimed[0].email,
      dayStart,
      claimed[0].email,
      deliveryDay,
      now - DELIVERY_RESERVATION_LIFETIME_MS,
      dailyLimit,
    ).run();
    if (!reservation.meta.changes) {
      const reason = [
        "daily_tier_limit",
        deliveryDay,
        `tier=${tier}`,
        `limit=${dailyLimit}`,
      ].join(":");
      await env.DB.batch(claimed.map((item) =>
        env.DB.prepare(
          `UPDATE notification_outbox
              SET status = 'suppressed', next_attempt_at = ?, last_error = ?
            WHERE id = ?
              AND status = 'processing'`,
        ).bind(now, reason, item.id)
      ));
      console.log(JSON.stringify({
        event: "notification_daily_tier_suppressed",
        tier,
        dailyLimit,
        itemCount: claimed.length,
      }));
      continue;
    }

    try {
      const digest = formatNotificationDigest(claimed.map((item) => item.body));
      const sent = await sendTencentTemplateEmail(
        env,
        claimed[0].email,
        digest.subject,
        digest.body,
      );
      const sentAt = new Date().toISOString();
      const deliveryId = sent.messageId || `worker:${crypto.randomUUID()}`;
      const updates: D1PreparedStatement[] = claimed.map((item) =>
        env.DB.prepare(
          `UPDATE notification_outbox
              SET status = 'sent', sent_at = ?, message_id = ?, last_error = NULL
            WHERE id = ?`,
        ).bind(sentAt, deliveryId, item.id)
      );
      for (const venueId of new Set(claimed.map((item) => item.venue_id))) {
        updates.push(env.DB.prepare(
          "UPDATE venue_status SET last_notification_at = ?, updated_at = ? WHERE venue_id = ?",
        ).bind(sentAt, sentAt, venueId));
      }
      updates.push(env.DB.prepare(
        `UPDATE email_delivery_claims
            SET status = 'sent', message_id = ?, updated_at = ?
          WHERE id = ? AND status = 'reserved'`,
      ).bind(deliveryId, Date.now(), deliveryClaimId));
      await env.DB.batch(updates);
      deliveredGroups += 1;
      console.log(JSON.stringify({
        event: "notification_digest_sent",
        tier,
        dailyLimit,
        itemCount: claimed.length,
      }));
    } catch (error) {
      const reason = error instanceof Error ? error.message.slice(0, 300) : "unknown";
      const updates: D1PreparedStatement[] = claimed.map((item) => {
        const attempt = item.attempt_count + 1;
        const nextStatus = attempt >= 5 ? "failed" : "retry";
        return env.DB.prepare(
          `UPDATE notification_outbox
              SET status = ?, next_attempt_at = ?, last_error = ?
            WHERE id = ?`,
        ).bind(nextStatus, now + retryDelayMs(attempt), reason, item.id);
      });
      updates.push(env.DB.prepare(
        `UPDATE email_delivery_claims
            SET status = 'released', updated_at = ?
          WHERE id = ? AND status = 'reserved'`,
      ).bind(Date.now(), deliveryClaimId));
      await env.DB.batch(updates);
      console.error(JSON.stringify({
        event: "notification_digest_failed",
        itemCount: claimed.length,
        reason,
      }));
    }
  }
}

async function cleanup(env: WorkerEnv): Promise<void> {
  const now = Date.now();
  const nowIso = new Date(now).toISOString();
  const ninetyDaysAgo = new Date(now - 90 * 86_400_000).toISOString();
  await env.DB.batch([
    env.DB.prepare(
      "DELETE FROM verification_challenges WHERE expires_at < ?",
    ).bind(now - 86_400_000),
    env.DB.prepare(
      "DELETE FROM verified_receipts WHERE expires_at < ? OR revoked_at IS NOT NULL",
    ).bind(now),
    env.DB.prepare(
      "UPDATE subscriptions SET active = 0, updated_at = ? WHERE active = 1 AND active_until <= ?",
    ).bind(nowIso, nowIso),
    env.DB.prepare(
      "DELETE FROM observed_slots WHERE last_observed_at < ?",
    ).bind(ninetyDaysAgo),
    env.DB.prepare(
      `DELETE FROM notification_outbox
        WHERE (status = 'sent' AND sent_at < ?)
           OR (status = 'suppressed' AND created_at < ?)`,
    ).bind(ninetyDaysAgo, ninetyDaysAgo),
    env.DB.prepare(
      `UPDATE email_delivery_claims
          SET status = 'released', updated_at = ?
        WHERE status = 'reserved'
          AND updated_at < ?`,
    ).bind(now, now - DELIVERY_RESERVATION_LIFETIME_MS),
    env.DB.prepare(
      "DELETE FROM email_delivery_claims WHERE created_at < ?",
    ).bind(now - 30 * 86_400_000),
    env.DB.prepare(
      "DELETE FROM priority_invite_attempts WHERE created_at < ?",
    ).bind(now - 7 * 86_400_000),
    env.DB.prepare(
      `DELETE FROM priority_invite_codes
        WHERE expires_at < ?
          AND redeemed_at IS NULL`,
    ).bind(now - 90 * 86_400_000),
  ]);
}

function withSecurityHeaders(response: Response): Response {
  const secured = new Response(response.body, response);
  secured.headers.set(
    "Content-Security-Policy",
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
  );
  secured.headers.set("Cross-Origin-Opener-Policy", "same-origin");
  secured.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  secured.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  secured.headers.set("Strict-Transport-Security", "max-age=31536000; includeSubDomains");
  secured.headers.set("X-Content-Type-Options", "nosniff");
  secured.headers.set("X-Frame-Options", "DENY");
  return secured;
}

async function handleRequest(
  request: Request,
  env: WorkerEnv,
  context: ExecutionContext,
): Promise<Response> {
  const url = new URL(request.url);
  try {
    if (request.method === "GET" && url.pathname === "/api/healthz") {
      return json({ ok: true, service: "zacks-tennis-alerts" });
    }
    if (request.method === "GET" && url.pathname === "/api/bootstrap") {
      return await bootstrap(request, env);
    }
    if (request.method === "POST" && url.pathname === "/api/email/send-code") {
      return await sendVerificationCode(request, env);
    }
    if (request.method === "POST" && url.pathname === "/api/email/verify") {
      return await verifyEmail(request, env);
    }
    if (request.method === "POST" && url.pathname === "/api/subscriptions") {
      return await createSubscription(request, env);
    }
    if (request.method === "POST" && url.pathname === "/api/priority/redeem") {
      return await redeemPriorityInvite(request, env);
    }
    if (
      request.method === "POST"
      && url.pathname === "/api/internal/priority-invites"
    ) {
      return await createPriorityInvites(request, env);
    }
    const cancellation = url.pathname.match(/^\/api\/subscriptions\/([0-9a-f-]{36})$/i);
    if (request.method === "DELETE" && cancellation) {
      return await cancelSubscription(request, env, cancellation[1]);
    }
    if (request.method === "POST" && url.pathname === "/api/internal/observations") {
      return await ingestObservation(request, env, context);
    }
    if (url.pathname.startsWith("/api/")) {
      return errorResponse(new Error("接口不存在"), 404);
    }
    return withSecurityHeaders(await env.ASSETS.fetch(request));
  } catch (error) {
    console.error(JSON.stringify({
      event: "request_failed",
      path: url.pathname,
      reason: error instanceof Error ? error.message.slice(0, 200) : "unknown",
    }));
    return errorResponse(error);
  }
}

export default {
  fetch: handleRequest,
  async scheduled(
    _controller: ScheduledController,
    env: WorkerEnv,
    context: ExecutionContext,
  ): Promise<void> {
    context.waitUntil(Promise.all([drainOutbox(env), cleanup(env)]).then(() => undefined));
  },
} satisfies ExportedHandler<WorkerEnv>;
