import {
  normalizeDeliveryTier,
  type DeliveryTier,
} from "./delivery-tiers";

export const SUBSCRIBER_REMINDER_CATEGORY = "场地提醒";
export const PRIORITY_EMAIL_LEAD_MS = 10_000;
export const PRIORITY_EMAIL_GATE_POLL_MS = 1_000;
export const PRIORITY_EMAIL_GATE_MAX_WAIT_MS = 15_000;

export type PriorityEmailGateEnv = {
  DB?: D1Database;
};

export type PriorityEmailGateSnapshot = {
  recipientTier: DeliveryTier;
  priorityOutstanding: boolean;
  lastPriorityCompletedAt: number | null;
};

type PriorityEmailGateRow = {
  recipient_tier?: string;
  priority_outstanding?: number;
  last_priority_completed_at?: number | null;
};

type PriorityEmailWaitOptions = {
  now?: () => number;
  sleep?: (delayMs: number) => Promise<void>;
  readSnapshot?: (now: number) => Promise<PriorityEmailGateSnapshot>;
  maxWaitMs?: number;
};

export class PriorityEmailWindowPendingError extends Error {
  readonly code = "priority_email_window_pending";
  readonly retryAfterMs: number;

  constructor(retryAfterMs = PRIORITY_EMAIL_GATE_POLL_MS) {
    super("priority subscriber email window is still active");
    this.name = "PriorityEmailWindowPendingError";
    this.retryAfterMs = retryAfterMs;
  }
}

function shanghaiDeliveryDay(now: number): string {
  return new Date(now + 8 * 3_600_000).toISOString().slice(0, 10);
}

export function standardReminderWaitMs(
  snapshot: PriorityEmailGateSnapshot,
  now: number,
): number {
  if (snapshot.recipientTier === "priority") return 0;
  if (snapshot.priorityOutstanding) return PRIORITY_EMAIL_GATE_POLL_MS;
  if (
    snapshot.lastPriorityCompletedAt === null
    || !Number.isFinite(snapshot.lastPriorityCompletedAt)
  ) {
    return 0;
  }
  return Math.max(
    0,
    Math.ceil(snapshot.lastPriorityCompletedAt + PRIORITY_EMAIL_LEAD_MS - now),
  );
}

export async function readPriorityEmailGateSnapshot(
  env: PriorityEmailGateEnv,
  recipient: string,
  now = Date.now(),
): Promise<PriorityEmailGateSnapshot> {
  if (!env.DB) {
    return {
      recipientTier: "standard",
      priorityOutstanding: false,
      lastPriorityCompletedAt: null,
    };
  }

  const row = await env.DB.prepare(
    `SELECT
       CASE WHEN EXISTS (
         SELECT 1
           FROM user_delivery_tiers recipient_tier
          WHERE recipient_tier.email = ?
            AND recipient_tier.tier = 'priority'
            AND recipient_tier.revoked_at IS NULL
       ) THEN 'priority' ELSE 'standard' END AS recipient_tier,
       EXISTS (
         SELECT 1
           FROM notification_outbox outbox
           JOIN user_delivery_tiers tiers ON tiers.email = outbox.email
          WHERE tiers.tier = 'priority'
            AND tiers.revoked_at IS NULL
            AND (
              outbox.status = 'processing'
              OR (
                outbox.status IN ('pending', 'retry')
                AND outbox.next_attempt_at <= ?
              )
            )
          LIMIT 1
       ) AS priority_outstanding,
       (
         SELECT MAX(claims.updated_at)
           FROM email_delivery_claims claims
           JOIN user_delivery_tiers tiers ON tiers.email = claims.email
          WHERE claims.delivery_day = ?
            AND claims.status IN ('sent', 'released')
            AND claims.updated_at >= ?
            AND tiers.tier = 'priority'
            AND tiers.revoked_at IS NULL
       ) AS last_priority_completed_at`,
  ).bind(
    recipient,
    now,
    shanghaiDeliveryDay(now),
    now - PRIORITY_EMAIL_LEAD_MS,
  ).first<PriorityEmailGateRow>();

  const completedAt = Number(row?.last_priority_completed_at);
  return {
    recipientTier: normalizeDeliveryTier(row?.recipient_tier),
    priorityOutstanding: Boolean(row?.priority_outstanding),
    lastPriorityCompletedAt: row?.last_priority_completed_at === null
      || row?.last_priority_completed_at === undefined
      || !Number.isFinite(completedAt)
      ? null
      : completedAt,
  };
}

export async function waitForSubscriberReminderWindow(
  env: PriorityEmailGateEnv,
  recipient: string,
  options: PriorityEmailWaitOptions = {},
): Promise<void> {
  if (!env.DB && !options.readSnapshot) return;

  const now = options.now ?? Date.now;
  const sleep = options.sleep ?? ((delayMs: number) =>
    new Promise<void>((resolve) => setTimeout(resolve, delayMs))
  );
  const readSnapshot = options.readSnapshot
    ?? ((current: number) => readPriorityEmailGateSnapshot(env, recipient, current));
  const configuredMaxWait = options.maxWaitMs ?? PRIORITY_EMAIL_GATE_MAX_WAIT_MS;
  const maxWaitMs = Number.isFinite(configuredMaxWait)
    ? Math.max(0, Math.trunc(configuredMaxWait))
    : PRIORITY_EMAIL_GATE_MAX_WAIT_MS;
  const startedAt = now();

  while (true) {
    const current = now();
    const snapshot = await readSnapshot(current);
    const waitMs = standardReminderWaitMs(snapshot, current);
    if (waitMs <= 0) return;

    const elapsed = Math.max(0, current - startedAt);
    const remaining = maxWaitMs - elapsed;
    if (remaining <= 0) {
      throw new PriorityEmailWindowPendingError(waitMs);
    }
    await sleep(Math.min(waitMs, remaining));
  }
}
