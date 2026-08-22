from __future__ import annotations

from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing replacement marker: {label}")
    return text.replace(old, new, 1)


def replace_section(text: str, start: str, end: str, replacement: str, label: str) -> str:
    try:
        start_index = text.index(start)
        end_index = text.index(end, start_index)
    except ValueError as exc:
        raise SystemExit(f"missing section marker: {label}") from exc
    return text[:start_index] + replacement.rstrip() + "\n\n" + text[end_index:]


# Domain accepts the new explicit term contract while retaining the legacy 7-14 day contract.
domain = read("webapp/cloudflare/domain.ts")
domain = replace_once(
    domain,
    '''  const durationDays = Number(candidate.durationDays);
  if (!Number.isInteger(durationDays) || durationDays < 7 || durationDays > 14) {
    throw new Error("订阅有效期必须为 7–14 天");
  }

  return { venueIds, startTime, endTime, durationDays };''',
    '''  const legacyDurationDays = Number(candidate.durationDays);
  const hasExplicitTerm = typeof candidate.termCode === "string"
    && candidate.termCode.trim().length > 0;
  if (
    !hasExplicitTerm
    && (!Number.isInteger(legacyDurationDays)
      || legacyDurationDays < 7
      || legacyDurationDays > 14)
  ) {
    throw new Error("订阅有效期必须为 7–14 天");
  }
  const durationDays = Number.isInteger(legacyDurationDays)
    && legacyDurationDays >= 7
    && legacyDurationDays <= 14
    ? legacyDurationDays
    : 7;

  return { venueIds, startTime, endTime, durationDays };''',
    "domain duration",
)
write("webapp/cloudflare/domain.ts", domain)

index = read("webapp/cloudflare/index.ts")
index = index.replace("  activeUntilIso,\n", "", 1)
index = replace_once(
    index,
    '''import { sendTencentTemplateEmail } from "./tencent-ses";
import { evaluateWeatherEmailGate } from "./weather-email-gate";''',
    '''import {
  getTencentEmailStatus,
  sendTencentTemplateEmail,
} from "./tencent-ses";
import { evaluateWeatherEmailGate } from "./weather-email-gate";
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
import { normalizeTencentDeliveryStatus } from "./email-lifecycle";''',
    "index imports",
)
index = replace_once(
    index,
    '''  PRIORITY_DAILY_EMAIL_LIMIT?: string;
  INVITE_CODE_PEPPER: string;''',
    '''  PRIORITY_DAILY_EMAIL_LIMIT?: string;
  STANDARD_ACTIVE_SUBSCRIPTION_LIMIT?: string;
  PRIORITY_ACTIVE_SUBSCRIPTION_LIMIT?: string;
  INVITE_CODE_PEPPER: string;''',
    "worker secrets",
)
index = replace_once(
    index,
    '''  duration_days: number;
  active_until: string;''',
    '''  duration_days: number;
  term_code: SubscriptionTerm;
  auto_renew: number;
  dedupe_key: string | null;
  active_until: string;''',
    "subscription row",
)
index = replace_once(
    index,
    '''const MAX_INVITES_PER_ADMIN_REQUEST = 25;''',
    '''const MAX_INVITES_PER_ADMIN_REQUEST = 25;
const DEFAULT_STANDARD_ACTIVE_SUBSCRIPTION_LIMIT = 5;
const DEFAULT_PRIORITY_ACTIVE_SUBSCRIPTION_LIMIT = 20;
const DELIVERY_STATUS_REFRESH_MS = 5 * 60_000;
const MAX_DELIVERY_STATUS_BATCH = 20;
const SYSTEM_EMAIL_BATCH = 20;''',
    "constants",
)

helpers = r'''
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

function base64UrlToBytes(value: string): Uint8Array {
  const padded = value.replaceAll("-", "+").replaceAll("_", "/")
    + "=".repeat((4 - value.length % 4) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
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
'''
index = replace_once(index, "async function bootstrap(", helpers + "\nasync function bootstrap(", "helper insertion")

# Keep authenticated activity and profile timestamps current.
index = replace_once(
    index,
    '''  await env.DB.prepare(
    "UPDATE verified_receipts SET last_used_at = ? WHERE token_hash = ?",
  ).bind(now, tokenHash).run();
  return { email: receipt.email, maskedEmail: receipt.masked_email };''',
    '''  await env.DB.batch([
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
  return { email: receipt.email, maskedEmail: receipt.masked_email };''',
    "identity activity",
)

bootstrap = r'''
async function bootstrap(request: Request, env: WorkerEnv): Promise<Response> {
  const identity = await getIdentity(request, env);
  const now = new Date();
  const nowIso = now.toISOString();
  const dayStart = shanghaiDayStart(now);

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
           SELECT COUNT(*)
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
       ORDER BY v.last_inspection_at DESC, v.venue_id`,
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
    healthy:
      Boolean(venue.healthy)
      && Boolean(venue.last_inspection_at)
      && Date.parse(venue.last_inspection_at || "") >= now.getTime() - INSPECTION_FRESHNESS_MS,
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
        `SELECT id, email, venue_ids, start_time, end_time, duration_days,
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
'''
index = replace_section(index, "async function bootstrap(", "async function sendVerificationCode(", bootstrap, "bootstrap")

verify = r'''
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
'''
index = replace_section(index, "async function verifyEmail(", "async function createSubscription(", verify, "verify email")

create_subscription = r'''
async function createSubscription(request: Request, env: WorkerEnv): Promise<Response> {
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

  const dedupeKey = await sha256Hex([
    identity.email,
    [...input.venueIds].sort().join(","),
    input.startTime,
    input.endTime,
  ].join("|"));
  const duplicate = await env.DB.prepare(
    `SELECT id FROM subscriptions
      WHERE email = ? AND active = 1 AND dedupe_key = ? LIMIT 1`,
  ).bind(identity.email, dedupeKey).first<{ id: string }>();
  if (duplicate) {
    return errorResponse(new Error("你已经创建了相同场地和时间条件的订阅"), 409);
  }

  const resolved = resolveSubscriptionTerm(termCode, now);
  const subscription = {
    id: crypto.randomUUID(),
    venueIds: input.venueIds,
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
       (id, email, venue_ids, start_time, end_time, duration_days,
        term_code, auto_renew, dedupe_key, active_until, active, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)`,
  ).bind(
    subscription.id,
    identity.email,
    JSON.stringify(subscription.venueIds),
    subscription.startTime,
    subscription.endTime,
    subscription.durationDays,
    subscription.termCode,
    subscription.autoRenew ? 1 : 0,
    dedupeKey,
    subscription.activeUntil,
    subscription.createdAt,
    subscription.createdAt,
  ).run();
  return json({ subscription: { ...subscription, eligible: true } }, 201);
}
'''
index = replace_section(
    index,
    "async function createSubscription(",
    "async function cancelSubscription(",
    create_subscription,
    "create subscription",
)

admin_and_invites = r'''
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
'''
index = replace_section(
    index,
    "async function createPriorityInvites(",
    "async function authorizeAirflow(",
    admin_and_invites,
    "admin and invites",
)

# Long-term subscriptions only match while the email retains priority status.
index = replace_once(
    index,
    '''      await env.DB.prepare(
        `SELECT id, email, venue_ids, start_time, end_time, duration_days,
                active_until, active, created_at
           FROM subscriptions
          WHERE active = 1 AND active_until > ?`,
      ).bind(nowIso).all<SubscriptionRow>()''',
    '''      await env.DB.prepare(
        `SELECT s.id, s.email, s.venue_ids, s.start_time, s.end_time, s.duration_days,
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
      ).bind(nowIso).all<SubscriptionRow>()''',
    "observation subscription eligibility",
)

# Quota is consumed when Tencent accepts a request, while delivery is counted separately.
index = replace_once(
    index,
    '''    `SELECT COUNT(DISTINCT message_id) AS count
       FROM notification_outbox
      WHERE status = 'sent' AND sent_at >= ?`,''',
    '''    `SELECT COUNT(DISTINCT message_id) AS count
       FROM notification_outbox
      WHERE provider_submitted_at >= ?`,''',
    "global submitted quota",
)
index = replace_once(
    index,
    '''          SELECT COUNT(DISTINCT message_id)
            FROM notification_outbox
           WHERE email = ?
             AND status = 'sent'
             AND sent_at >= ?''',
    '''          SELECT COUNT(DISTINCT message_id)
            FROM notification_outbox
           WHERE email = ?
             AND provider_submitted_at >= ?''',
    "per user submitted quota",
)

old_send_block = '''      const sentAt = new Date().toISOString();
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
      }));'''
new_send_block = '''      const submittedAt = new Date().toISOString();
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
      }));'''
index = replace_once(index, old_send_block, new_send_block, "submitted send state")

maintenance = r'''
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
'''
index = replace_section(index, "async function cleanup(", "function withSecurityHeaders(", maintenance, "maintenance")

# Add authenticated community/admin routes and invite management.
index = replace_once(
    index,
    '''    if (request.method === "POST" && url.pathname === "/api/priority/redeem") {
      return await redeemPriorityInvite(request, env);
    }
    if (
      request.method === "POST"
      && url.pathname === "/api/internal/priority-invites"
    ) {''',
    '''    if (request.method === "POST" && url.pathname === "/api/priority/redeem") {
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
    ) {''',
    "admin routes",
)

index = replace_once(
    index,
    '''    context.waitUntil(Promise.all([drainOutbox(env), cleanup(env)]).then(() => undefined));''',
    '''    context.waitUntil((async () => {
      await renewLongTermSubscriptions(env);
      await enqueueExpiryReminders(env);
      await Promise.all([drainOutbox(env), drainSystemEmailOutbox(env)]);
      await Promise.all([
        reconcileNotificationDeliveries(env),
        reconcileSystemEmailDeliveries(env),
      ]);
      await cleanup(env);
    })());''',
    "scheduled lifecycle",
)

write("webapp/cloudflare/index.ts", index)

wrangler = read("webapp/wrangler.jsonc")
wrangler = replace_once(
    wrangler,
    '''    "STANDARD_DAILY_EMAIL_LIMIT": "30",
    "PRIORITY_DAILY_EMAIL_LIMIT": "100"''',
    '''    "STANDARD_DAILY_EMAIL_LIMIT": "30",
    "PRIORITY_DAILY_EMAIL_LIMIT": "100",
    "STANDARD_ACTIVE_SUBSCRIPTION_LIMIT": "5",
    "PRIORITY_ACTIVE_SUBSCRIPTION_LIMIT": "20"''',
    "wrangler limits",
)
write("webapp/wrangler.jsonc", wrangler)
