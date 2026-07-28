import {
  VENUES,
  activeUntilIso,
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
import { sendTencentTemplateEmail } from "./tencent-ses";

type WorkerSecrets = {
  TENCENT_SECRET_ID: string;
  TENCENT_SECRET_KEY: string;
  EMAIL_FROM_ADDRESS: string;
  EMAIL_REPLY_TO: string;
  EMAIL_TEMPLATE_ID: string;
  VERIFICATION_PEPPER: string;
  AIRFLOW_PUSH_TOKEN: string;
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
};

const JSON_HEADERS = {
  "Cache-Control": "no-store",
  "Content-Type": "application/json; charset=utf-8",
};
const MAX_JSON_BYTES = 32_768;
const RECEIPT_LIFETIME_MS = 180 * 86_400_000;
const CHALLENGE_LIFETIME_MS = 10 * 60_000;
const INSPECTION_FRESHNESS_MS = 10 * 60_000;

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
      "SELECT COUNT(*) AS count FROM notification_outbox WHERE status = 'sent' AND sent_at >= ?",
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
        `SELECT COUNT(*) AS count
           FROM notification_outbox
          WHERE email = ?
            AND status = 'sent'
            AND sent_at >= ?`,
      ).bind(identity.email, dayStart),
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
      `SELECT id, email, subject, body, venue_id, attempt_count
         FROM notification_outbox
        WHERE status IN ('pending', 'retry', 'processing')
          AND next_attempt_at <= ?
        ORDER BY created_at
        LIMIT 10`,
    ).bind(now).all<OutboxRow>()
  ).results;

  for (const item of pending) {
    const attempt = item.attempt_count + 1;
    const lease = await env.DB.prepare(
      `UPDATE notification_outbox
          SET status = 'processing', attempt_count = ?, next_attempt_at = ?
        WHERE id = ?
          AND status IN ('pending', 'retry', 'processing')
          AND next_attempt_at <= ?`,
    ).bind(attempt, now + 5 * 60_000, item.id, now).run();
    if (!lease.meta.changes) continue;

    try {
      const sent = await sendTencentTemplateEmail(
        env,
        item.email,
        item.subject,
        item.body,
      );
      const sentAt = new Date().toISOString();
      await env.DB.batch([
        env.DB.prepare(
          `UPDATE notification_outbox
              SET status = 'sent', sent_at = ?, message_id = ?, last_error = NULL
            WHERE id = ?`,
        ).bind(sentAt, sent.messageId, item.id),
        env.DB.prepare(
          "UPDATE venue_status SET last_notification_at = ?, updated_at = ? WHERE venue_id = ?",
        ).bind(sentAt, sentAt, item.venue_id),
      ]);
      console.log(JSON.stringify({ event: "notification_sent", outboxId: item.id }));
    } catch (error) {
      const nextStatus = attempt >= 5 ? "failed" : "retry";
      const reason = error instanceof Error ? error.message.slice(0, 300) : "unknown";
      await env.DB.prepare(
        `UPDATE notification_outbox
            SET status = ?, next_attempt_at = ?, last_error = ?
          WHERE id = ?`,
      ).bind(nextStatus, now + retryDelayMs(attempt), reason, item.id).run();
      console.error(JSON.stringify({
        event: "notification_failed",
        outboxId: item.id,
        attempt,
        final: nextStatus === "failed",
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
      "DELETE FROM notification_outbox WHERE status = 'sent' AND sent_at < ?",
    ).bind(ninetyDaysAgo),
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
