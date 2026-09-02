import {
  ALL_WEEKDAY_MASK,
  VENUES,
  formatNotificationDigest,
  formatSlotLine,
  maskEmail,
  normalizeEmail,
  randomToken,
  randomVerificationCode,
  sha256Hex,
  slotMatchesTimeRange,
  slotMatchesWeekday,
  validateSlotObservation,
  validateSubscriptionInput,
  weekdayMaskFromDays,
  weekdaysFromMask,
  type SlotObservation,
  type VenueId,
} from "./domain";
import {
  currentObservationSnapshotStatement,
  enqueueCurrentSnapshotMatches,
} from "./current-observation";
import {
  deliveryLimitForTier,
  deliveryTierLimits,
  normalizeDeliveryTier,
  remainingDailyDeliveries,
  type DeliveryTier,
} from "./delivery-tiers";
import {
  generateInviteCode,
  hashInviteCode,
  normalizeInviteCode,
} from "./invite-codes";
import {
  COFFEE_CLAIM_DELAY_MS,
  COFFEE_IP_CLAIM_LIMIT,
  COFFEE_IP_CLAIM_WINDOW_MS,
  COFFEE_SESSION_EMAIL_LIMIT,
  COFFEE_SESSION_IP_LIMIT,
  COFFEE_SESSION_LIFETIME_MS,
  COFFEE_SESSION_RATE_WINDOW_MS,
  coffeeInviteExpiresAt,
  coffeeSessionState,
} from "./coffee-invites";
import {
  getTencentEmailStatus,
  sendTencentTemplateEmail,
} from "./tencent-ses";
import { evaluateWeatherEmailGate } from "./weather-email-gate";
import {
  partitionWeatherDeliveries,
  weatherSuppressedForTier,
} from "./weather-delivery-policy";
import {
  LONG_TERM_LEASE_DAYS,
  LONG_TERM_RENEW_THRESHOLD_DAYS,
  normalizeSubscriptionTerm,
  resolveSubscriptionTerm,
  subscriptionTermAllowed,
  subscriptionTermsForTier,
  type SubscriptionTerm,
} from "./subscription-terms";
import {
  activityBucket,
  maskCommunityEmail,
  volumeBucket,
} from "./admin-privacy";
import { normalizeTencentDeliveryStatus } from "./email-lifecycle";

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
  STANDARD_ACTIVE_SUBSCRIPTION_LIMIT?: string;
  PRIORITY_ACTIVE_SUBSCRIPTION_LIMIT?: string;
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
  weekday_mask: number;
  duration_days: number;
  term_code: SubscriptionTerm;
  auto_renew: number;
  dedupe_key: string | null;
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

type CoffeeInviteClaimRow = {
  email: string;
  session_id: string;
  invite_id: string;
  claimed_at: number;
  encrypted_code: string | null;
  encryption_iv: string | null;
  invite_expires_at: number | null;
  invite_active: number | null;
  redeemed_at: number | null;
  deleted_at: number | null;
};

type CoffeeInviteSessionRow = {
  id: string;
  email: string;
  shown_at: number;
  claimable_at: number;
  expires_at: number;
  consumed_at: number | null;
};

const JSON_HEADERS = {
  "Cache-Control": "no-store",
  "Content-Type": "application/json; charset=utf-8",
};
const MAX_JSON_BYTES = 32_768;
const RECEIPT_LIFETIME_MS = 180 * 86_400_000;
const CHALLENGE_LIFETIME_MS = 10 * 60_000;
const MAX_OUTBOX_BATCH_ROWS = 100;
const DELIVERY_RESERVATION_LIFETIME_MS = 10 * 60_000;
const INVITE_ATTEMPT_WINDOW_MS = 60 * 60_000;
const INVITE_EMAIL_ATTEMPT_LIMIT = 10;
const INVITE_IP_ATTEMPT_LIMIT = 30;
const MAX_INVITES_PER_ADMIN_REQUEST = 25;
const DEFAULT_STANDARD_ACTIVE_SUBSCRIPTION_LIMIT = 5;
const DEFAULT_PRIORITY_ACTIVE_SUBSCRIPTION_LIMIT = 20;
const DELIVERY_STATUS_REFRESH_MS = 5 * 60_000;
const MAX_DELIVERY_STATUS_BATCH = 20;
const SYSTEM_EMAIL_BATCH = 20;

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

  await env.DB.batch([
    env.DB.prepare(
      "UPDATE verified_receipts SET last_used_at = ? WHERE token_hash = ?",
    ).bind(now, tokenHash),
    env.DB.prepare(
      `INSERT INTO user_profiles
         (email, masked_email, first_verified_at, last_verified_at,
          last_login_at, last_active_at, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(email) DO UPDATE SET
         masked_email = excluded.masked_email,
         last_active_at = excluded.last_active_at,
         updated_at = excluded.updated_at`,
    ).bind(
      receipt.email,
      receipt.masked_email,
      now,
      now,
      now,
      now,
      now,
      now,
    ),
  ]);
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


function configuredPositiveInteger(value: string | undefined, fallback: number): number {
  const candidate = Number(value);
  return Number.isInteger(candidate) && candidate > 0 ? candidate : fallback;
}

function activeSubscriptionLimitForTier(env: WorkerEnv, tier: DeliveryTier): number {
  return tier === "priority"
    ? configuredPositiveInteger(
      env.PRIORITY_ACTIVE_SUBSCRIPTION_LIMIT,
      DEFAULT_PRIORITY_ACTIVE_SUBSCRIPTION_LIMIT,
    )
    : configuredPositiveInteger(
      env.STANDARD_ACTIVE_SUBSCRIPTION_LIMIT,
      DEFAULT_STANDARD_ACTIVE_SUBSCRIPTION_LIMIT,
    );
}

async function deliveryTierForEmail(env: WorkerEnv, email: string): Promise<DeliveryTier> {
  const row = await env.DB.prepare(
    `SELECT tier
       FROM user_delivery_tiers
      WHERE email = ?
        AND revoked_at IS NULL`,
  ).bind(email).first<{ tier?: string }>();
  return normalizeDeliveryTier(row?.tier);
}

async function isAdministrator(env: WorkerEnv, email: string): Promise<boolean> {
  const role = await env.DB.prepare(
    `SELECT 1 AS allowed
       FROM user_roles
      WHERE email = ?
        AND role = 'admin'
        AND revoked_at IS NULL`,
  ).bind(email).first<{ allowed: number }>();
  return Boolean(role?.allowed);
}

async function requireIdentity(request: Request, env: WorkerEnv): Promise<Identity> {
  const identity = await getIdentity(request, env);
  if (!identity) throw new Error("请先验证邮箱");
  return identity;
}

async function requireAdministrator(request: Request, env: WorkerEnv): Promise<Identity> {
  const identity = await requireIdentity(request, env);
  if (!(await isAdministrator(env, identity.email))) {
    throw new Error("仅管理员可以执行此操作");
  }
  return identity;
}

function bytesToBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function base64UrlToBytes(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replaceAll("-", "+").replaceAll("_", "/")
    + "=".repeat((4 - value.length % 4) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

async function inviteEncryptionKey(pepper: string): Promise<CryptoKey> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(`zacks-invite-encryption:${pepper}`),
  );
  return crypto.subtle.importKey("raw", digest, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
}

async function encryptInviteCode(
  code: string,
  pepper: string,
): Promise<{ encryptedCode: string; encryptionIv: string }> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encrypted = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    await inviteEncryptionKey(pepper),
    new TextEncoder().encode(code),
  );
  return {
    encryptedCode: bytesToBase64Url(new Uint8Array(encrypted)),
    encryptionIv: bytesToBase64Url(iv),
  };
}

async function decryptInviteCode(
  encryptedCode: string | null,
  encryptionIv: string | null,
  pepper: string,
): Promise<string | null> {
  if (!encryptedCode || !encryptionIv) return null;
  try {
    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: base64UrlToBytes(encryptionIv) },
      await inviteEncryptionKey(pepper),
      base64UrlToBytes(encryptedCode),
    );
    return new TextDecoder().decode(decrypted);
  } catch {
    return null;
  }
}

function epochIso(value: number | null | undefined): string | null {
  return value ? new Date(value).toISOString() : null;
}

async function clientIpHash(request: Request, pepper: string): Promise<string> {
  const ip = request.headers.get("cf-connecting-ip") || "unknown";
  return sha256Hex(`coffee-invite:${ip}:${pepper}`);
}

async function coffeeInviteClaimForEmail(
  env: WorkerEnv,
  email: string,
): Promise<CoffeeInviteClaimRow | null> {
  return env.DB.prepare(
    `SELECT
       claims.email,
       claims.session_id,
       claims.invite_id,
       claims.claimed_at,
       invites.encrypted_code,
       invites.encryption_iv,
       invites.expires_at AS invite_expires_at,
       invites.active AS invite_active,
       invites.redeemed_at,
       invites.deleted_at
       FROM coffee_invite_claims claims
       LEFT JOIN priority_invite_codes invites ON invites.id = claims.invite_id
      WHERE claims.email = ?`,
  ).bind(email).first<CoffeeInviteClaimRow>();
}

async function coffeeInviteSession(
  env: WorkerEnv,
  email: string,
  sessionId: string,
): Promise<CoffeeInviteSessionRow | null> {
  return env.DB.prepare(
    `SELECT id, email, shown_at, claimable_at, expires_at, consumed_at
       FROM coffee_invite_sessions
      WHERE id = ? AND email = ?`,
  ).bind(sessionId, email).first<CoffeeInviteSessionRow>();
}

async function coffeeInvitePayload(
  env: WorkerEnv,
  row: CoffeeInviteClaimRow,
  reused: boolean,
): Promise<Record<string, unknown>> {
  const code = await decryptInviteCode(
    row.encrypted_code,
    row.encryption_iv,
    env.INVITE_CODE_PEPPER,
  );
  if (!code || !row.invite_expires_at) {
    throw new Error("彩蛋邀请码暂时无法读取，请稍后再试");
  }
  const now = Date.now();
  const status = row.deleted_at
    ? "deleted"
    : row.redeemed_at
      ? "redeemed"
      : row.invite_expires_at <= now
        ? "expired"
        : row.invite_active
          ? "available"
          : "disabled";
  return {
    code,
    expiresAt: new Date(row.invite_expires_at).toISOString(),
    claimedAt: new Date(row.claimed_at).toISOString(),
    reused,
    status,
  };
}


async function bootstrap(request: Request, env: WorkerEnv): Promise<Response> {
  const identity = await getIdentity(request, env);
  const now = new Date();
  const nowIso = now.toISOString();
  const dayStart = shanghaiDayStart(now);
  const weatherEmailGate = await evaluateWeatherEmailGate(env);

  const globalResults = await env.DB.batch([
    env.DB.prepare(
      `SELECT COUNT(*) AS count
         FROM subscriptions s
        WHERE s.active = 1
          AND s.active_until > ?
          AND (
            s.auto_renew = 0
            OR EXISTS (
              SELECT 1 FROM user_delivery_tiers tiers
               WHERE tiers.email = s.email
                 AND tiers.tier = 'priority'
                 AND tiers.revoked_at IS NULL
            )
          )`,
    ).bind(nowIso),
    env.DB.prepare(
      `SELECT COUNT(DISTINCT message_id) AS count
         FROM notification_outbox
        WHERE status = 'delivered'
          AND provider_delivered_at >= ?`,
    ).bind(dayStart),
    env.DB.prepare(
      `SELECT
         v.venue_id,
         v.venue_name,
         v.healthy,
         v.last_inspection_at,
         v.last_notification_at,
         (
           SELECT COUNT(DISTINCT s.email)
             FROM subscriptions s, json_each(s.venue_ids) selected
            WHERE s.active = 1
              AND s.active_until > ?
              AND (
                s.auto_renew = 0
                OR EXISTS (
                  SELECT 1 FROM user_delivery_tiers tiers
                   WHERE tiers.email = s.email
                     AND tiers.tier = 'priority'
                     AND tiers.revoked_at IS NULL
                )
              )
              AND selected.value = v.venue_id
         ) AS subscriber_count
       FROM venue_status v
       ORDER BY subscriber_count DESC, v.venue_name COLLATE NOCASE, v.venue_id`,
    ).bind(nowIso),
  ]);

  const activeSubscriptions = Number(
    (globalResults[0].results[0] as { count?: number } | undefined)?.count || 0,
  );
  const remindersToday = Number(
    (globalResults[1].results[0] as { count?: number } | undefined)?.count || 0,
  );
  const venueRows = globalResults[2].results as unknown as VenueStatusRow[];
  const venues = venueRows.map((venue) => ({
    id: venue.venue_id,
    name: venue.venue_name,
    healthy: Boolean(venue.healthy),
    subscriberCount: Number(venue.subscriber_count || 0),
    lastInspectionAt: venue.last_inspection_at,
    lastNotificationAt: venue.last_notification_at,
  }));

  let subscriptionRows: SubscriptionRow[] = [];
  let submittedToday = 0;
  let deliveredToday = 0;
  let failedToday = 0;
  let identityTier: DeliveryTier = "standard";
  let admin = false;
  if (identity) {
    const identityResults = await env.DB.batch([
      env.DB.prepare(
        `SELECT id, email, venue_ids, start_time, end_time, weekday_mask, duration_days,
                term_code, auto_renew, dedupe_key, active_until, active, created_at
           FROM subscriptions
          WHERE email = ? AND active = 1 AND active_until > ?
          ORDER BY created_at DESC`,
      ).bind(identity.email, nowIso),
      env.DB.prepare(
        `SELECT COUNT(DISTINCT message_id) AS count
           FROM notification_outbox
          WHERE email = ?
            AND provider_submitted_at >= ?`,
      ).bind(identity.email, dayStart),
      env.DB.prepare(
        `SELECT COUNT(DISTINCT message_id) AS count
           FROM notification_outbox
          WHERE email = ?
            AND status = 'delivered'
            AND provider_delivered_at >= ?`,
      ).bind(identity.email, dayStart),
      env.DB.prepare(
        `SELECT COUNT(DISTINCT message_id) AS count
           FROM notification_outbox
          WHERE email = ?
            AND status = 'failed'
            AND provider_submitted_at >= ?`,
      ).bind(identity.email, dayStart),
      env.DB.prepare(
        `SELECT tier FROM user_delivery_tiers
          WHERE email = ? AND revoked_at IS NULL`,
      ).bind(identity.email),
      env.DB.prepare(
        `SELECT 1 AS allowed FROM user_roles
          WHERE email = ? AND role = 'admin' AND revoked_at IS NULL`,
      ).bind(identity.email),
    ]);
    subscriptionRows = identityResults[0].results as unknown as SubscriptionRow[];
    submittedToday = Number(
      (identityResults[1].results[0] as { count?: number } | undefined)?.count || 0,
    );
    deliveredToday = Number(
      (identityResults[2].results[0] as { count?: number } | undefined)?.count || 0,
    );
    failedToday = Number(
      (identityResults[3].results[0] as { count?: number } | undefined)?.count || 0,
    );
    identityTier = normalizeDeliveryTier(
      (identityResults[4].results[0] as { tier?: string } | undefined)?.tier,
    );
    admin = Boolean(
      (identityResults[5].results[0] as { allowed?: number } | undefined)?.allowed,
    );
  }

  const tierLimits = deliveryTierLimits(env);
  const subscriptionLimits = {
    standard: activeSubscriptionLimitForTier(env, "standard"),
    priority: activeSubscriptionLimitForTier(env, "priority"),
  };
  const identityDailyLimit = tierLimits[identityTier];
  const identityActiveSubscriptionLimit = subscriptionLimits[identityTier];

  return json({
    generatedAt: nowIso,
    weatherEmailGate: {
      suppressed: weatherSuppressedForTier(weatherEmailGate, identityTier),
      precipitationMm: weatherEmailGate.precipitationMm,
      thresholdMm: weatherEmailGate.thresholdMm,
    },
    metrics: {
      activeSubscriptions,
      remindersToday,
      healthyVenues: venues.filter((venue) => venue.healthy).length,
      totalVenues: venues.length,
    },
    deliveryTiers: tierLimits,
    subscriptionTerms: {
      standard: subscriptionTermsForTier("standard"),
      priority: subscriptionTermsForTier("priority"),
    },
    subscriptionLimits,
    venues,
    identity: {
      verified: Boolean(identity),
      maskedEmail: identity?.maskedEmail ?? null,
      remindersToday: submittedToday,
      submittedToday,
      deliveredToday,
      failedToday,
      tier: identityTier,
      isAdmin: admin,
      dailyLimit: identityDailyLimit,
      remainingToday: remainingDailyDeliveries(submittedToday, identityDailyLimit),
      activeSubscriptionLimit: identityActiveSubscriptionLimit,
      activeSubscriptionCount: subscriptionRows.length,
      remainingSubscriptions: Math.max(
        0,
        identityActiveSubscriptionLimit - subscriptionRows.length,
      ),
    },
    subscriptions: subscriptionRows.map((subscription) => ({
      id: subscription.id,
      venueIds: JSON.parse(subscription.venue_ids),
      startTime: subscription.start_time,
      endTime: subscription.end_time,
      weekdays: weekdaysFromMask(subscription.weekday_mask),
      durationDays: subscription.duration_days,
      termCode: subscription.term_code,
      autoRenew: Boolean(subscription.auto_renew),
      eligible: !Boolean(subscription.auto_renew) || identityTier === "priority",
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
  if (!challenge || challenge.consumed_at || challenge.expires_at <= now || challenge.attempts >= 5) {
    throw new Error("验证码已失效，请重新获取");
  }

  const suppliedHash = await sha256Hex(`${challengeId}:${code}:${env.VERIFICATION_PEPPER}`);
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
    `UPDATE verification_challenges SET consumed_at = ?
      WHERE id = ? AND consumed_at IS NULL`,
  ).bind(now, challengeId).run();
  if (!consumed.meta.changes) throw new Error("验证码已失效，请重新获取");

  await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO verified_receipts
         (token_hash, email, masked_email, expires_at, last_used_at, created_at)
       VALUES (?, ?, ?, ?, ?, ?)`,
    ).bind(tokenHash, challenge.email, maskedEmail, now + RECEIPT_LIFETIME_MS, now, now),
    env.DB.prepare(
      `INSERT INTO user_profiles
         (email, masked_email, first_verified_at, last_verified_at,
          last_login_at, last_active_at, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(email) DO UPDATE SET
         masked_email = excluded.masked_email,
         last_verified_at = excluded.last_verified_at,
         last_login_at = excluded.last_login_at,
         last_active_at = excluded.last_active_at,
         updated_at = excluded.updated_at`,
    ).bind(
      challenge.email,
      maskedEmail,
      now,
      now,
      now,
      now,
      now,
      now,
    ),
  ]);

  return json({
    token,
    email: challenge.email,
    maskedEmail,
    verifiedAt: new Date(now).toISOString(),
  });
}


async function createSubscription(
  request: Request,
  env: WorkerEnv,
  context: ExecutionContext,
): Promise<Response> {
  const identity = await getIdentity(request, env);
  if (!identity) return errorResponse(new Error("请先验证邮箱"), 401);

  const payload = await readJson(request);
  const candidate = payload && typeof payload === "object"
    ? payload as Record<string, unknown>
    : {};
  const input = validateSubscriptionInput(candidate);
  const tier = await deliveryTierForEmail(env, identity.email);
  const termCode = normalizeSubscriptionTerm(candidate.termCode, candidate.durationDays);
  if (!subscriptionTermAllowed(tier, termCode)) {
    return errorResponse(new Error("该订阅有效期仅限优先用户"), 403);
  }

  const now = new Date();
  const nowIso = now.toISOString();
  const activeCount = await env.DB.prepare(
    `SELECT COUNT(*) AS count FROM subscriptions
      WHERE email = ? AND active = 1 AND active_until > ?`,
  ).bind(identity.email, nowIso).first<{ count: number }>();
  const activeLimit = activeSubscriptionLimitForTier(env, tier);
  if (Number(activeCount?.count || 0) >= activeLimit) {
    return errorResponse(new Error(`最多同时保留 ${activeLimit} 个有效订阅`), 409);
  }

  const sortedVenueIds = [...input.venueIds].sort();
  const weekdayMask = weekdayMaskFromDays(input.weekdays);
  const legacyDedupeKey = await sha256Hex([
    identity.email,
    sortedVenueIds.join(","),
    input.startTime,
    input.endTime,
  ].join("|"));
  const dedupeKey = await sha256Hex([
    identity.email,
    sortedVenueIds.join(","),
    input.startTime,
    input.endTime,
    String(weekdayMask),
  ].join("|"));
  const duplicate = await env.DB.prepare(
    `SELECT id FROM subscriptions
      WHERE email = ?
        AND active = 1
        AND (
          dedupe_key = ?
          OR (? = ${ALL_WEEKDAY_MASK} AND dedupe_key = ?)
        )
      LIMIT 1`,
  ).bind(identity.email, dedupeKey, weekdayMask, legacyDedupeKey).first<{ id: string }>();
  if (duplicate) {
    return errorResponse(new Error("你已经创建了相同场地、星期和时间条件的订阅"), 409);
  }

  const resolved = resolveSubscriptionTerm(termCode, now);
  const subscription = {
    id: crypto.randomUUID(),
    venueIds: sortedVenueIds,
    weekdays: input.weekdays,
    startTime: input.startTime,
    endTime: input.endTime,
    durationDays: resolved.durationDays,
    termCode: resolved.termCode,
    autoRenew: resolved.autoRenew,
    activeUntil: resolved.activeUntil,
    active: true,
    createdAt: nowIso,
  };
  await env.DB.prepare(
    `INSERT INTO subscriptions
       (id, email, venue_ids, start_time, end_time, weekday_mask, duration_days,
        term_code, auto_renew, dedupe_key, active_until, active, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)`,
  ).bind(
    subscription.id,
    identity.email,
    JSON.stringify(subscription.venueIds),
    subscription.startTime,
    subscription.endTime,
    weekdayMask,
    subscription.durationDays,
    subscription.termCode,
    subscription.autoRenew ? 1 : 0,
    dedupeKey,
    subscription.activeUntil,
    subscription.createdAt,
    subscription.createdAt,
  ).run();

  let matchedCurrentAvailability = 0;
  try {
    matchedCurrentAvailability = await enqueueCurrentSnapshotMatches(env.DB, {
      id: subscription.id,
      email: identity.email,
      venueIds: subscription.venueIds,
      weekdayMask,
      startTime: subscription.startTime,
      endTime: subscription.endTime,
    }, now);
    if (matchedCurrentAvailability > 0) {
      context.waitUntil(drainOutbox(env));
    }
  } catch (error) {
    console.warn(JSON.stringify({
      event: "current_snapshot_subscription_match_failed",
      subscriptionId: subscription.id,
      reason: error instanceof Error ? error.message.slice(0, 160) : "unknown",
    }));
  }

  return json({
    subscription: { ...subscription, eligible: true },
    matchedCurrentAvailability,
  }, 201);
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

async function startCoffeeInviteSession(
  request: Request,
  env: WorkerEnv,
): Promise<Response> {
  const identity = await getIdentity(request, env);
  if (!identity) return errorResponse(new Error("请先验证邮箱"), 401);

  const now = Date.now();
  const ipHash = await clientIpHash(request, env.INVITE_CODE_PEPPER);
  const since = now - COFFEE_SESSION_RATE_WINDOW_MS;
  const sessionId = crypto.randomUUID();
  const claimableAt = now + COFFEE_CLAIM_DELAY_MS;
  const expiresAt = now + COFFEE_SESSION_LIFETIME_MS;
  const inserted = await env.DB.prepare(
    `INSERT INTO coffee_invite_sessions
       (id, email, ip_hash, shown_at, claimable_at, expires_at, consumed_at, created_at)
     SELECT ?, ?, ?, ?, ?, ?, NULL, ?
      WHERE (
        SELECT COUNT(*) FROM coffee_invite_sessions
         WHERE email = ? AND created_at >= ?
      ) < ?
        AND (
          SELECT COUNT(*) FROM coffee_invite_sessions
           WHERE ip_hash = ? AND created_at >= ?
        ) < ?`,
  ).bind(
    sessionId,
    identity.email,
    ipHash,
    now,
    claimableAt,
    expiresAt,
    now,
    identity.email,
    since,
    COFFEE_SESSION_EMAIL_LIMIT,
    ipHash,
    since,
    COFFEE_SESSION_IP_LIMIT,
  ).run();
  if (!inserted.meta.changes) {
    return errorResponse(new Error("二维码打开过于频繁，请稍后再试"), 429);
  }
  return json({
    claimToken: sessionId,
    availableAt: new Date(claimableAt).toISOString(),
    expiresAt: new Date(expiresAt).toISOString(),
    alreadyClaimed: Boolean(await coffeeInviteClaimForEmail(env, identity.email)),
  }, 201);
}

async function claimCoffeeInvite(
  request: Request,
  env: WorkerEnv,
): Promise<Response> {
  const identity = await getIdentity(request, env);
  if (!identity) return errorResponse(new Error("请先验证邮箱"), 401);

  const payload = await readJson(request);
  const claimToken = payload && typeof payload === "object"
    ? String((payload as Record<string, unknown>).claimToken || "").trim()
    : "";
  if (!/^[0-9a-f-]{36}$/i.test(claimToken)) {
    return errorResponse(new Error("彩蛋领取凭证无效"), 400);
  }

  const now = Date.now();
  const existingClaim = await coffeeInviteClaimForEmail(env, identity.email);
  if (existingClaim) {
    return json(await coffeeInvitePayload(env, existingClaim, true));
  }
  const session = await coffeeInviteSession(env, identity.email, claimToken);
  if (!session) {
    return errorResponse(new Error("彩蛋领取凭证无效，请重新打开二维码"), 404);
  }
  const state = coffeeSessionState({
    claimableAt: session.claimable_at,
    expiresAt: session.expires_at,
    inviteId: null,
  }, now);
  if (state === "too_early") {
    return errorResponse(new Error("请在二维码显示 5 秒后再确认"), 425);
  }
  if (state === "expired") {
    return errorResponse(new Error("二维码停留时间过长，请重新打开后再试"), 410);
  }

  const ipHash = await clientIpHash(request, env.INVITE_CODE_PEPPER);
  const recentIpClaims = await env.DB.prepare(
    `SELECT COUNT(*) AS count
       FROM coffee_invite_claims
      WHERE ip_hash = ?
        AND claimed_at >= ?`,
  ).bind(ipHash, now - COFFEE_IP_CLAIM_WINDOW_MS).first<{ count: number }>();
  if (Number(recentIpClaims?.count || 0) >= COFFEE_IP_CLAIM_LIMIT) {
    return errorResponse(new Error("当前网络领取次数已达上限，请稍后再试"), 429);
  }

  const inviteId = crypto.randomUUID();
  const code = generateInviteCode();
  const encrypted = await encryptInviteCode(code, env.INVITE_CODE_PEPPER);
  const codeHint = code.split("-").slice(0, 3).join("-");
  const inviteExpiresAt = coffeeInviteExpiresAt(now);
  const results = await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO priority_invite_codes
         (id, code_hash, expires_at, active, note, created_at,
          encrypted_code, encryption_iv, code_hint, updated_at, deleted_at)
       SELECT ?, ?, ?, 1, 'coffee_reward', ?, ?, ?, ?, ?, NULL
        WHERE EXISTS (
          SELECT 1 FROM coffee_invite_sessions sessions
           WHERE sessions.id = ?
             AND sessions.email = ?
             AND sessions.consumed_at IS NULL
             AND sessions.claimable_at <= ?
             AND sessions.expires_at > ?
        )
          AND NOT EXISTS (
            SELECT 1 FROM coffee_invite_claims claims WHERE claims.email = ?
          )
          AND (
            SELECT COUNT(*) FROM coffee_invite_claims claims
             WHERE claims.ip_hash = ?
               AND claims.claimed_at >= ?
          ) < ?`,
    ).bind(
      inviteId,
      await hashInviteCode(code, env.INVITE_CODE_PEPPER),
      inviteExpiresAt,
      now,
      encrypted.encryptedCode,
      encrypted.encryptionIv,
      codeHint,
      now,
      claimToken,
      identity.email,
      now,
      now,
      identity.email,
      ipHash,
      now - COFFEE_IP_CLAIM_WINDOW_MS,
      COFFEE_IP_CLAIM_LIMIT,
    ),
    env.DB.prepare(
      `INSERT INTO coffee_invite_claims
         (email, session_id, invite_id, ip_hash, claimed_at)
       SELECT ?, ?, ?, ?, ?
        WHERE EXISTS (SELECT 1 FROM priority_invite_codes WHERE id = ?)
       ON CONFLICT(email) DO NOTHING`,
    ).bind(
      identity.email,
      claimToken,
      inviteId,
      ipHash,
      now,
      inviteId,
    ),
    env.DB.prepare(
      `UPDATE coffee_invite_sessions
          SET consumed_at = ?
        WHERE id = ?
          AND email = ?
          AND consumed_at IS NULL
          AND EXISTS (
            SELECT 1 FROM coffee_invite_claims claims
             WHERE claims.email = ?
               AND claims.session_id = ?
               AND claims.invite_id = ?
          )`,
    ).bind(
      now,
      claimToken,
      identity.email,
      identity.email,
      claimToken,
      inviteId,
    ),
  ]);

  const created = Number(results[0].meta.changes || 0) === 1
    && Number(results[1].meta.changes || 0) === 1
    && Number(results[2].meta.changes || 0) === 1;
  const claimed = await coffeeInviteClaimForEmail(env, identity.email);
  if (!claimed?.invite_id) {
    const refreshedSession = await coffeeInviteSession(env, identity.email, claimToken);
    if (!refreshedSession) {
      return errorResponse(new Error("彩蛋领取凭证无效，请重新打开二维码"), 404);
    }
    const refreshedState = coffeeSessionState({
      claimableAt: refreshedSession.claimable_at,
      expiresAt: refreshedSession.expires_at,
      inviteId: null,
    }, Date.now());
    if (refreshedState === "too_early") {
      return errorResponse(new Error("请在二维码显示 5 秒后再确认"), 425);
    }
    if (refreshedState === "expired") {
      return errorResponse(new Error("二维码停留时间过长，请重新打开后再试"), 410);
    }
    return errorResponse(new Error("彩蛋邀请码生成失败，请稍后再试"), 409);
  }
  console.log(JSON.stringify({
    event: "coffee_invite_claimed",
    created,
    expiresInDays: 30,
  }));
  return json(await coffeeInvitePayload(env, claimed, !created), created ? 201 : 200);
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


async function createInviteRecords(
  env: WorkerEnv,
  count: number,
  expiresInDays: number,
  note: string | null,
): Promise<Array<{
  id: string;
  code: string;
  codeHint: string;
  expiresAt: string;
  createdAt: string;
}>> {
  const now = Date.now();
  const expiresAt = now + expiresInDays * 86_400_000;
  const records: Array<{
    id: string;
    code: string;
    codeHint: string;
    expiresAt: string;
    createdAt: string;
  }> = [];
  const inserts: D1PreparedStatement[] = [];
  for (let index = 0; index < count; index += 1) {
    const id = crypto.randomUUID();
    const code = generateInviteCode();
    const encrypted = await encryptInviteCode(code, env.INVITE_CODE_PEPPER);
    const codeHint = code.split("-").slice(0, 3).join("-");
    records.push({
      id,
      code,
      codeHint,
      expiresAt: new Date(expiresAt).toISOString(),
      createdAt: new Date(now).toISOString(),
    });
    inserts.push(
      env.DB.prepare(
        `INSERT INTO priority_invite_codes
           (id, code_hash, expires_at, active, note, created_at,
            encrypted_code, encryption_iv, code_hint, updated_at, deleted_at)
         VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, NULL)`,
      ).bind(
        id,
        await hashInviteCode(code, env.INVITE_CODE_PEPPER),
        expiresAt,
        note,
        now,
        encrypted.encryptedCode,
        encrypted.encryptionIv,
        codeHint,
        now,
      ),
    );
  }
  await env.DB.batch(inserts);
  return records;
}

async function createPriorityInvites(
  request: Request,
  env: WorkerEnv,
): Promise<Response> {
  const token = requestToken(request);
  if (!token || !env.INVITE_ADMIN_TOKEN || !constantTimeEqual(token, env.INVITE_ADMIN_TOKEN)) {
    return errorResponse(new Error("未授权"), 401);
  }
  const payload = await readJson(request);
  const candidate = payload && typeof payload === "object"
    ? payload as Record<string, unknown>
    : {};
  const count = positiveIntegerInput(candidate.count, 1, MAX_INVITES_PER_ADMIN_REQUEST);
  const expiresInDays = positiveIntegerInput(candidate.expiresInDays, 30, 365);
  const note = candidate.note ? String(candidate.note).slice(0, 120) : null;
  const records = await createInviteRecords(env, count, expiresInDays, note);
  return json({
    codes: records.map((record) => record.code),
    count: records.length,
    expiresAt: records[0]?.expiresAt ?? null,
  }, 201);
}

async function communityUsers(request: Request, env: WorkerEnv): Promise<Response> {
  await requireIdentity(request, env);
  const rows = (
    await env.DB.prepare(
      `SELECT
         p.email,
         p.last_active_at,
         CASE WHEN tiers.tier = 'priority' AND tiers.revoked_at IS NULL
              THEN 'priority' ELSE 'standard' END AS tier,
         (SELECT COUNT(*) FROM subscriptions s
           WHERE s.email = p.email AND s.active = 1 AND s.active_until > ?) AS active_subscriptions,
         (SELECT COUNT(DISTINCT n.message_id) FROM notification_outbox n
           WHERE n.email = p.email AND n.status = 'delivered') AS delivered_total
       FROM user_profiles p
       LEFT JOIN user_delivery_tiers tiers ON tiers.email = p.email
       ORDER BY p.last_active_at DESC
       LIMIT 100`,
    ).bind(new Date().toISOString()).all<{
      email: string;
      last_active_at: number;
      tier: DeliveryTier;
      active_subscriptions: number;
      delivered_total: number;
    }>()
  ).results;
  return json({
    generatedAt: new Date().toISOString(),
    users: rows.map((row) => ({
      email: maskCommunityEmail(row.email),
      tier: normalizeDeliveryTier(row.tier),
      activity: activityBucket(row.last_active_at),
      activeSubscriptions: Number(row.active_subscriptions || 0),
      deliveredVolume: volumeBucket(Number(row.delivered_total || 0)),
    })),
  });
}

async function adminUsers(request: Request, env: WorkerEnv): Promise<Response> {
  await requireAdministrator(request, env);
  const dayStart = shanghaiDayStart();
  const rows = (
    await env.DB.prepare(
      `SELECT
         p.email,
         p.masked_email,
         p.first_verified_at,
         p.last_verified_at,
         p.last_login_at,
         p.last_active_at,
         CASE WHEN tiers.tier = 'priority' AND tiers.revoked_at IS NULL
              THEN 'priority' ELSE 'standard' END AS tier,
         CASE WHEN roles.role = 'admin' AND roles.revoked_at IS NULL THEN 1 ELSE 0 END AS is_admin,
         (SELECT COUNT(*) FROM subscriptions s
           WHERE s.email = p.email AND s.active = 1 AND s.active_until > ?) AS active_subscriptions,
         (SELECT COUNT(DISTINCT n.message_id) FROM notification_outbox n
           WHERE n.email = p.email AND n.provider_submitted_at >= ?) AS submitted_today,
         (SELECT COUNT(DISTINCT n.message_id) FROM notification_outbox n
           WHERE n.email = p.email AND n.status = 'delivered' AND n.provider_delivered_at >= ?) AS delivered_today,
         (SELECT COUNT(DISTINCT n.message_id) FROM notification_outbox n
           WHERE n.email = p.email AND n.status = 'failed' AND n.provider_submitted_at >= ?) AS failed_today,
         (SELECT COUNT(DISTINCT n.message_id) FROM notification_outbox n
           WHERE n.email = p.email AND n.status = 'delivered') AS delivered_all_time
       FROM user_profiles p
       LEFT JOIN user_delivery_tiers tiers ON tiers.email = p.email
       LEFT JOIN user_roles roles ON roles.email = p.email AND roles.role = 'admin'
       ORDER BY p.last_active_at DESC
       LIMIT 250`,
    ).bind(
      new Date().toISOString(),
      dayStart,
      dayStart,
      dayStart,
    ).all<{
      email: string;
      masked_email: string;
      first_verified_at: number;
      last_verified_at: number;
      last_login_at: number;
      last_active_at: number;
      tier: DeliveryTier;
      is_admin: number;
      active_subscriptions: number;
      submitted_today: number;
      delivered_today: number;
      failed_today: number;
      delivered_all_time: number;
    }>()
  ).results;
  return json({
    generatedAt: new Date().toISOString(),
    users: rows.map((row) => ({
      email: row.email,
      maskedEmail: row.masked_email,
      tier: normalizeDeliveryTier(row.tier),
      isAdmin: Boolean(row.is_admin),
      firstVerifiedAt: epochIso(row.first_verified_at),
      lastVerifiedAt: epochIso(row.last_verified_at),
      lastLoginAt: epochIso(row.last_login_at),
      lastActiveAt: epochIso(row.last_active_at),
      activeSubscriptions: Number(row.active_subscriptions || 0),
      submittedToday: Number(row.submitted_today || 0),
      deliveredToday: Number(row.delivered_today || 0),
      failedToday: Number(row.failed_today || 0),
      deliveredAllTime: Number(row.delivered_all_time || 0),
    })),
  });
}

type InviteAdminRow = {
  id: string;
  encrypted_code: string | null;
  encryption_iv: string | null;
  code_hint: string | null;
  active: number;
  note: string | null;
  created_at: number;
  updated_at: number | null;
  expires_at: number;
  redeemed_by: string | null;
  redeemed_at: number | null;
  deleted_at: number | null;
};

async function serializeInvite(env: WorkerEnv, row: InviteAdminRow): Promise<Record<string, unknown>> {
  const code = await decryptInviteCode(
    row.encrypted_code,
    row.encryption_iv,
    env.INVITE_CODE_PEPPER,
  );
  const now = Date.now();
  const status = row.deleted_at
    ? "deleted"
    : row.redeemed_at
      ? "redeemed"
      : row.expires_at <= now
        ? "expired"
        : row.active
          ? "available"
          : "disabled";
  return {
    id: row.id,
    code,
    codeHint: row.code_hint,
    recoverable: Boolean(code),
    active: Boolean(row.active),
    status,
    note: row.note,
    createdAt: new Date(row.created_at).toISOString(),
    expiresAt: new Date(row.expires_at).toISOString(),
    redeemedBy: row.redeemed_by,
    redeemedAt: epochIso(row.redeemed_at),
  };
}

async function adminInvites(request: Request, env: WorkerEnv): Promise<Response> {
  await requireAdministrator(request, env);
  if (request.method === "POST") {
    const payload = await readJson(request);
    const candidate = payload && typeof payload === "object"
      ? payload as Record<string, unknown>
      : {};
    const count = positiveIntegerInput(candidate.count, 1, 20);
    const expiresInDays = positiveIntegerInput(candidate.expiresInDays, 90, 365);
    const note = candidate.note ? String(candidate.note).slice(0, 120) : null;
    const records = await createInviteRecords(env, count, expiresInDays, note);
    return json({
      invites: records.map((record) => ({
        id: record.id,
        code: record.code,
        codeHint: record.codeHint,
        recoverable: true,
        active: true,
        status: "available",
        note,
        createdAt: record.createdAt,
        expiresAt: record.expiresAt,
        redeemedBy: null,
        redeemedAt: null,
      })),
    }, 201);
  }
  const rows = (
    await env.DB.prepare(
      `SELECT id, encrypted_code, encryption_iv, code_hint, active, note,
              created_at, updated_at, expires_at, redeemed_by, redeemed_at, deleted_at
         FROM priority_invite_codes
        ORDER BY created_at DESC
        LIMIT 250`,
    ).all<InviteAdminRow>()
  ).results;
  return json({
    generatedAt: new Date().toISOString(),
    invites: await Promise.all(rows.map((row) => serializeInvite(env, row))),
  });
}

async function updateAdminInvite(
  request: Request,
  env: WorkerEnv,
  inviteId: string,
): Promise<Response> {
  await requireAdministrator(request, env);
  const current = await env.DB.prepare(
    `SELECT id, active, note, expires_at, redeemed_at, deleted_at
       FROM priority_invite_codes WHERE id = ?`,
  ).bind(inviteId).first<{
    id: string;
    active: number;
    note: string | null;
    expires_at: number;
    redeemed_at: number | null;
    deleted_at: number | null;
  }>();
  if (!current || current.deleted_at) return errorResponse(new Error("邀请码不存在"), 404);
  if (current.redeemed_at) return errorResponse(new Error("已兑换的邀请码不能修改"), 409);
  const payload = await readJson(request);
  const candidate = payload && typeof payload === "object"
    ? payload as Record<string, unknown>
    : {};
  const active = typeof candidate.active === "boolean" ? candidate.active : Boolean(current.active);
  const note = candidate.note === undefined ? current.note : String(candidate.note).slice(0, 120);
  const expiresAt = candidate.expiresInDays === undefined
    ? current.expires_at
    : Date.now() + positiveIntegerInput(candidate.expiresInDays, 90, 365) * 86_400_000;
  const result = await env.DB.prepare(
    `UPDATE priority_invite_codes
        SET active = ?, note = ?, expires_at = ?, updated_at = ?
      WHERE id = ? AND redeemed_at IS NULL AND deleted_at IS NULL`,
  ).bind(active ? 1 : 0, note, expiresAt, Date.now(), inviteId).run();
  if (!result.meta.changes) return errorResponse(new Error("邀请码更新失败"), 409);
  return json({ success: true });
}

async function deleteAdminInvite(
  request: Request,
  env: WorkerEnv,
  inviteId: string,
): Promise<Response> {
  await requireAdministrator(request, env);
  const result = await env.DB.prepare(
    `UPDATE priority_invite_codes
        SET active = 0, deleted_at = ?, updated_at = ?
      WHERE id = ? AND deleted_at IS NULL`,
  ).bind(Date.now(), Date.now(), inviteId).run();
  if (!result.meta.changes) return errorResponse(new Error("邀请码不存在"), 404);
  return json({ success: true });
}

async function authorizeAirflow(request: Request, env: WorkerEnv): Promise<boolean> {
  const token = requestToken(request);
  return Boolean(token) && constantTimeEqual(token || "", env.AIRFLOW_PUSH_TOKEN);
}

function parseObservationPayload(value: unknown): {
  observationKey: string;
  observationScope: string;
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
  const observationScope = String(
    candidate.observation_scope || candidate.observationScope || "default",
  ).trim();
  if (!observationScope || observationScope.length > 120) {
    throw new Error("巡检范围无效");
  }
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
    observationKey: `v3:${venueId}:${observationScope}`,
    observationScope,
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
    currentObservationSnapshotStatement(env.DB, observation, nowIso),
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
        `SELECT s.id, s.email, s.venue_ids, s.start_time, s.end_time, s.weekday_mask,
                s.duration_days,
                s.term_code, s.auto_renew, s.dedupe_key,
                s.active_until, s.active, s.created_at
           FROM subscriptions s
           LEFT JOIN user_delivery_tiers tiers ON tiers.email = s.email
          WHERE s.active = 1
            AND s.active_until > ?
            AND (
              s.auto_renew = 0
              OR (tiers.tier = 'priority' AND tiers.revoked_at IS NULL)
            )`,
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
      if (!slotMatchesWeekday(slot, subscription.weekday_mask)) continue;
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

let sendable = pending;
const standardPending = pending.filter((item) => item.tier === "standard");
if (standardPending.length) {
  const weather = await evaluateWeatherEmailGate(env);
  if (!weather.sendEmail) {
    const partition = partitionWeatherDeliveries(pending, weather);
    const suppressionReason = [
      "weather_suppressed",
      weather.forecastDate || "unknown-date",
      `${weather.precipitationMm ?? "unknown"}mm`,
      `threshold=${weather.thresholdMm}mm`,
    ].join(":");
    const results = partition.suppressed.length
      ? await env.DB.batch(partition.suppressed.map((item) =>
        env.DB.prepare(
          `UPDATE notification_outbox
              SET status = 'suppressed', next_attempt_at = ?, last_error = ?
            WHERE id = ?
              AND status IN ('pending', 'retry', 'processing')
              AND next_attempt_at <= ?`,
        ).bind(now, suppressionReason, item.id, now)
      ))
      : [];
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
      priorityBypassCount: partition.priorityBypass.length,
    }));
    sendable = partition.sendable;
    if (!sendable.length) return;
  }
  if (weather.reason === "weather_unavailable") {
    console.warn(JSON.stringify({
      event: "notification_weather_gate_fail_open",
      forecastDate: weather.forecastDate,
      thresholdMm: weather.thresholdMm,
      reason: weather.error,
    }));
  }
}

  const dayStart = shanghaiDayStart(new Date(now));
  const configuredLimit = Number(env.NOTIFICATION_DAILY_SEND_LIMIT);
  const dailyLimit = Number.isInteger(configuredLimit) && configuredLimit > 0
    ? configuredLimit
    : 1_000;
  const deliveryCountRow = await env.DB.prepare(
    `SELECT COUNT(DISTINCT message_id) AS count
       FROM notification_outbox
      WHERE provider_submitted_at >= ?`,
  ).bind(dayStart).first<{ count: number }>();
  const remainingDeliveries = Math.max(0, dailyLimit - Number(deliveryCountRow?.count || 0));
  if (!remainingDeliveries) {
    console.log(JSON.stringify({ event: "notification_daily_budget_reserved", dailyLimit }));
    return;
  }

  const grouped = new Map<string, OutboxRow[]>();
  for (const item of sendable) {
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
             AND provider_submitted_at >= ?
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
      const submittedAt = new Date().toISOString();
      const deliveryId = sent.messageId || `worker:${crypto.randomUUID()}`;
      const updates: D1PreparedStatement[] = claimed.map((item) =>
        env.DB.prepare(
          `UPDATE notification_outbox
              SET status = 'submitted',
                  sent_at = NULL,
                  message_id = ?,
                  provider_request_id = ?,
                  provider_status = 'accepted',
                  provider_submitted_at = ?,
                  provider_checked_at = NULL,
                  provider_error = NULL,
                  last_error = NULL
            WHERE id = ?`,
        ).bind(deliveryId, sent.requestId, submittedAt, item.id)
      );
      updates.push(env.DB.prepare(
        `UPDATE email_delivery_claims
            SET status = 'sent', message_id = ?, updated_at = ?
          WHERE id = ? AND status = 'reserved'`,
      ).bind(deliveryId, Date.now(), deliveryClaimId));
      await env.DB.batch(updates);
      deliveredGroups += 1;
      console.log(JSON.stringify({
        event: "notification_digest_submitted",
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


async function renewLongTermSubscriptions(env: WorkerEnv): Promise<void> {
  const now = Date.now();
  const threshold = new Date(now + LONG_TERM_RENEW_THRESHOLD_DAYS * 86_400_000).toISOString();
  const renewedUntil = new Date(now + LONG_TERM_LEASE_DAYS * 86_400_000).toISOString();
  await env.DB.prepare(
    `UPDATE subscriptions
        SET active_until = ?, updated_at = ?
      WHERE active = 1
        AND auto_renew = 1
        AND active_until <= ?
        AND EXISTS (
          SELECT 1 FROM user_delivery_tiers tiers
           WHERE tiers.email = subscriptions.email
             AND tiers.tier = 'priority'
             AND tiers.revoked_at IS NULL
        )`,
  ).bind(renewedUntil, new Date(now).toISOString(), threshold).run();
}

async function enqueueExpiryReminders(env: WorkerEnv): Promise<void> {
  const now = Date.now();
  const nowIso = new Date(now).toISOString();
  const finalDay = new Date(now + 86_400_000).toISOString();
  await env.DB.prepare(
    `INSERT OR IGNORE INTO system_email_outbox
       (id, dedupe_key, email, email_type, subject, body, status,
        attempt_count, next_attempt_at, created_at, updated_at)
     SELECT lower(hex(randomblob(16))),
            'subscription-expiry:' || s.id,
            s.email,
            'subscription_expiry',
            '网球提醒订阅将在1天内到期',
            '你的网球提醒订阅将在 ' || substr(s.active_until, 1, 16)
              || ' 到期。请登录 Zacks 网球提醒续订或创建新的订阅。',
            'pending',
            0,
            ?,
            ?,
            ?
       FROM subscriptions s
      WHERE s.active = 1
        AND s.auto_renew = 0
        AND s.active_until > ?
        AND s.active_until <= ?`,
  ).bind(now, nowIso, nowIso, nowIso, finalDay).run();
}

async function drainSystemEmailOutbox(env: WorkerEnv): Promise<void> {
  const now = Date.now();
  const rows = (
    await env.DB.prepare(
      `SELECT id, email, subject, body, attempt_count
         FROM system_email_outbox
        WHERE status IN ('pending', 'retry')
          AND next_attempt_at <= ?
        ORDER BY created_at
        LIMIT ?`,
    ).bind(now, SYSTEM_EMAIL_BATCH).all<{
      id: string;
      email: string;
      subject: string;
      body: string;
      attempt_count: number;
    }>()
  ).results;
  for (const row of rows) {
    const attempt = row.attempt_count + 1;
    const lease = await env.DB.prepare(
      `UPDATE system_email_outbox
          SET status = 'processing', attempt_count = ?, next_attempt_at = ?, updated_at = ?
        WHERE id = ? AND status IN ('pending', 'retry')`,
    ).bind(attempt, now + 5 * 60_000, new Date().toISOString(), row.id).run();
    if (!lease.meta.changes) continue;
    try {
      const sent = await sendTencentTemplateEmail(
        env,
        row.email,
        row.subject,
        row.body,
        "订阅到期提醒",
      );
      const submittedAt = new Date().toISOString();
      await env.DB.prepare(
        `UPDATE system_email_outbox
            SET status = 'submitted',
                provider_message_id = ?, provider_request_id = ?,
                provider_status = 'accepted', submitted_at = ?,
                provider_checked_at = NULL, last_error = NULL, updated_at = ?
          WHERE id = ?`,
      ).bind(
        sent.messageId || `worker:${crypto.randomUUID()}`,
        sent.requestId,
        submittedAt,
        submittedAt,
        row.id,
      ).run();
    } catch (error) {
      const reason = error instanceof Error ? error.message.slice(0, 300) : "unknown";
      const nextStatus = attempt >= 5 ? "failed" : "retry";
      await env.DB.prepare(
        `UPDATE system_email_outbox
            SET status = ?, next_attempt_at = ?, last_error = ?, updated_at = ?
          WHERE id = ?`,
      ).bind(
        nextStatus,
        now + retryDelayMs(attempt),
        reason,
        new Date().toISOString(),
        row.id,
      ).run();
    }
  }
}

async function reconcileNotificationDeliveries(env: WorkerEnv): Promise<void> {
  const now = Date.now();
  const messages = (
    await env.DB.prepare(
      `SELECT message_id, MIN(email) AS email
         FROM notification_outbox
        WHERE status = 'submitted'
          AND message_id IS NOT NULL
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)
        GROUP BY message_id
        ORDER BY MIN(provider_submitted_at)
        LIMIT ?`,
    ).bind(now - DELIVERY_STATUS_REFRESH_MS, MAX_DELIVERY_STATUS_BATCH).all<{
      message_id: string;
      email: string;
    }>()
  ).results;
  for (const message of messages) {
    try {
      const provider = await getTencentEmailStatus(env, message.message_id, message.email);
      const normalized = normalizeTencentDeliveryStatus(provider);
      if (normalized.state === "delivered") {
        const deliveredAt = normalized.deliveredAt || new Date().toISOString();
        const venues = (
          await env.DB.prepare(
            `SELECT DISTINCT venue_id FROM notification_outbox WHERE message_id = ?`,
          ).bind(message.message_id).all<{ venue_id: VenueId }>()
        ).results;
        const updates: D1PreparedStatement[] = [
          env.DB.prepare(
            `UPDATE notification_outbox
                SET status = 'delivered', provider_status = ?,
                    provider_delivered_at = ?, provider_checked_at = ?,
                    provider_error = NULL, sent_at = ?
              WHERE message_id = ? AND status = 'submitted'`,
          ).bind(normalized.providerStatus, deliveredAt, now, deliveredAt, message.message_id),
        ];
        for (const venue of venues) {
          updates.push(env.DB.prepare(
            `UPDATE venue_status
                SET last_notification_at = ?, updated_at = ?
              WHERE venue_id = ?`,
          ).bind(deliveredAt, deliveredAt, venue.venue_id));
        }
        await env.DB.batch(updates);
      } else if (normalized.state === "failed") {
        await env.DB.prepare(
          `UPDATE notification_outbox
              SET status = 'failed', provider_status = ?,
                  provider_failed_at = ?, provider_checked_at = ?,
                  provider_error = ?, last_error = ?
            WHERE message_id = ? AND status = 'submitted'`,
        ).bind(
          normalized.providerStatus,
          new Date().toISOString(),
          now,
          normalized.error,
          normalized.error,
          message.message_id,
        ).run();
      } else {
        await env.DB.prepare(
          `UPDATE notification_outbox
              SET provider_status = ?, provider_checked_at = ?
            WHERE message_id = ? AND status = 'submitted'`,
        ).bind(normalized.providerStatus, now, message.message_id).run();
      }
    } catch (error) {
      console.warn(JSON.stringify({
        event: "notification_delivery_status_unavailable",
        messageId: message.message_id,
        reason: error instanceof Error ? error.message.slice(0, 200) : "unknown",
      }));
    }
  }
}

async function reconcileSystemEmailDeliveries(env: WorkerEnv): Promise<void> {
  const now = Date.now();
  const rows = (
    await env.DB.prepare(
      `SELECT id, email, provider_message_id
         FROM system_email_outbox
        WHERE status = 'submitted'
          AND provider_message_id IS NOT NULL
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)
        ORDER BY submitted_at
        LIMIT ?`,
    ).bind(now - DELIVERY_STATUS_REFRESH_MS, MAX_DELIVERY_STATUS_BATCH).all<{
      id: string;
      email: string;
      provider_message_id: string;
    }>()
  ).results;
  for (const row of rows) {
    try {
      const provider = await getTencentEmailStatus(env, row.provider_message_id, row.email);
      const normalized = normalizeTencentDeliveryStatus(provider);
      const currentIso = new Date().toISOString();
      if (normalized.state === "delivered") {
        await env.DB.prepare(
          `UPDATE system_email_outbox
              SET status = 'delivered', provider_status = ?, delivered_at = ?,
                  provider_checked_at = ?, last_error = NULL, updated_at = ?
            WHERE id = ?`,
        ).bind(
          normalized.providerStatus,
          normalized.deliveredAt || currentIso,
          now,
          currentIso,
          row.id,
        ).run();
      } else if (normalized.state === "failed") {
        await env.DB.prepare(
          `UPDATE system_email_outbox
              SET status = 'failed', provider_status = ?, failed_at = ?,
                  provider_checked_at = ?, last_error = ?, updated_at = ?
            WHERE id = ?`,
        ).bind(
          normalized.providerStatus,
          currentIso,
          now,
          normalized.error,
          currentIso,
          row.id,
        ).run();
      } else {
        await env.DB.prepare(
          `UPDATE system_email_outbox
              SET provider_status = ?, provider_checked_at = ?, updated_at = ?
            WHERE id = ?`,
        ).bind(normalized.providerStatus, now, currentIso, row.id).run();
      }
    } catch (error) {
      console.warn(JSON.stringify({
        event: "system_email_delivery_status_unavailable",
        messageId: row.provider_message_id,
        reason: error instanceof Error ? error.message.slice(0, 200) : "unknown",
      }));
    }
  }
}

async function cleanup(env: WorkerEnv): Promise<void> {
  const now = Date.now();
  const nowIso = new Date(now).toISOString();
  const ninetyDaysAgo = new Date(now - 90 * 86_400_000).toISOString();
  await env.DB.batch([
    env.DB.prepare("DELETE FROM verification_challenges WHERE expires_at < ?")
      .bind(now - 86_400_000),
    env.DB.prepare("DELETE FROM verified_receipts WHERE expires_at < ? OR revoked_at IS NOT NULL")
      .bind(now),
    env.DB.prepare(
      "UPDATE subscriptions SET active = 0, updated_at = ? WHERE active = 1 AND active_until <= ?",
    ).bind(nowIso, nowIso),
    env.DB.prepare("DELETE FROM observed_slots WHERE last_observed_at < ?")
      .bind(ninetyDaysAgo),
    env.DB.prepare(
      `DELETE FROM notification_outbox
        WHERE (status IN ('delivered', 'failed', 'suppressed') AND created_at < ?)`,
    ).bind(ninetyDaysAgo),
    env.DB.prepare(
      `UPDATE email_delivery_claims SET status = 'released', updated_at = ?
        WHERE status = 'reserved' AND updated_at < ?`,
    ).bind(now, now - DELIVERY_RESERVATION_LIFETIME_MS),
    env.DB.prepare("DELETE FROM email_delivery_claims WHERE created_at < ?")
      .bind(now - 30 * 86_400_000),
    env.DB.prepare("DELETE FROM priority_invite_attempts WHERE created_at < ?")
      .bind(now - 30 * 86_400_000),
    env.DB.prepare("DELETE FROM coffee_invite_sessions WHERE created_at < ?")
      .bind(now - 86_400_000),
    env.DB.prepare(
      `DELETE FROM priority_invite_codes
        WHERE expires_at < ? AND redeemed_at IS NULL AND deleted_at IS NOT NULL`,
    ).bind(now - 90 * 86_400_000),
    env.DB.prepare(
      `DELETE FROM system_email_outbox
        WHERE status IN ('delivered', 'failed') AND created_at < ?`,
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
      return await createSubscription(request, env, context);
    }
    if (request.method === "POST" && url.pathname === "/api/coffee/session") {
      return await startCoffeeInviteSession(request, env);
    }
    if (request.method === "POST" && url.pathname === "/api/coffee/invite") {
      return await claimCoffeeInvite(request, env);
    }
    if (request.method === "POST" && url.pathname === "/api/priority/redeem") {
      return await redeemPriorityInvite(request, env);
    }
    if (request.method === "GET" && url.pathname === "/api/community/users") {
      const identity = await getIdentity(request, env);
      if (!identity) return errorResponse(new Error("请先验证邮箱"), 401);
      return await communityUsers(request, env);
    }
    if (url.pathname === "/api/admin/users" && request.method === "GET") {
      const identity = await getIdentity(request, env);
      if (!identity) return errorResponse(new Error("请先验证邮箱"), 401);
      if (!(await isAdministrator(env, identity.email))) {
        return errorResponse(new Error("仅管理员可以查看"), 403);
      }
      return await adminUsers(request, env);
    }
    if (url.pathname === "/api/admin/invites" && ["GET", "POST"].includes(request.method)) {
      const identity = await getIdentity(request, env);
      if (!identity) return errorResponse(new Error("请先验证邮箱"), 401);
      if (!(await isAdministrator(env, identity.email))) {
        return errorResponse(new Error("仅管理员可以查看"), 403);
      }
      return await adminInvites(request, env);
    }
    const adminInvite = url.pathname.match(/^\/api\/admin\/invites\/([0-9a-f-]{36})$/i);
    if (adminInvite && request.method === "PATCH") {
      return await updateAdminInvite(request, env, adminInvite[1]);
    }
    if (adminInvite && request.method === "DELETE") {
      return await deleteAdminInvite(request, env, adminInvite[1]);
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
    context.waitUntil((async () => {
      await renewLongTermSubscriptions(env);
      await enqueueExpiryReminders(env);
      await Promise.all([drainOutbox(env), drainSystemEmailOutbox(env)]);
      await Promise.all([
        reconcileNotificationDeliveries(env),
        reconcileSystemEmailDeliveries(env),
      ]);
      await cleanup(env);
    })());
  },
} satisfies ExportedHandler<WorkerEnv>;
