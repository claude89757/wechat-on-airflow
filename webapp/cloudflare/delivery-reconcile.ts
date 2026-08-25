import { normalizeTencentDeliveryStatus } from "./email-lifecycle";
import { getTencentEmailStatus, type TencentSecrets } from "./tencent-ses";

type ReconcileEnv = TencentSecrets & {
  DB: D1Database;
};

type NotificationCandidate = {
  messageId: string;
  email: string;
  submittedAt: string;
};

type SystemEmailCandidate = {
  id: string;
  messageId: string;
  email: string;
  submittedAt: string;
};

export type QueueReconcileSummary = {
  selected: number;
  selectedRecent: number;
  selectedBacklog: number;
  claimed: number;
  checked: number;
  delivered: number;
  failed: number;
  pending: number;
  unavailable: number;
  errors: Record<string, number>;
};

export type DeliveryReconcileSummary = {
  notifications: QueueReconcileSummary;
  systemEmails: QueueReconcileSummary;
};

const REFRESH_MS = 5 * 60_000;
const RECENT_PRIORITY_MS = 48 * 60 * 60_000;
const PROVIDER_STATUS_RETENTION_MS = 30 * 86_400_000;
const BACKLOG_RESERVE_RATIO = 0.2;

function emptySummary(): QueueReconcileSummary {
  return {
    selected: 0,
    selectedRecent: 0,
    selectedBacklog: 0,
    claimed: 0,
    checked: 0,
    delivered: 0,
    failed: 0,
    pending: 0,
    unavailable: 0,
    errors: {},
  };
}

export function reconciliationLanePlan(limit: number): {
  recent: number;
  backlog: number;
} {
  const bounded = Math.max(1, Math.floor(limit));
  if (bounded < 5) return { recent: bounded, backlog: 0 };
  const backlog = Math.max(1, Math.floor(bounded * BACKLOG_RESERVE_RATIO));
  return { recent: bounded - backlog, backlog };
}

export function selectReconciliationCandidates<T>(
  recent: T[],
  backlog: T[],
  limit: number,
): { items: T[]; recentCount: number; backlogCount: number } {
  const bounded = Math.max(1, Math.floor(limit));
  const plan = reconciliationLanePlan(bounded);
  const selectedRecent = recent.slice(0, plan.recent);
  const selectedBacklog = backlog.slice(0, plan.backlog);
  let remaining = bounded - selectedRecent.length - selectedBacklog.length;

  if (remaining > 0) {
    selectedRecent.push(...recent.slice(plan.recent, plan.recent + remaining));
    remaining = bounded - selectedRecent.length - selectedBacklog.length;
  }
  if (remaining > 0) {
    selectedBacklog.push(...backlog.slice(plan.backlog, plan.backlog + remaining));
  }

  return {
    items: [...selectedRecent, ...selectedBacklog],
    recentCount: selectedRecent.length,
    backlogCount: selectedBacklog.length,
  };
}

export function providerCheckError(error: unknown): {
  code: string;
  reason: string;
  status: string;
} {
  const reason = error instanceof Error
    ? error.message.slice(0, 300)
    : "unknown delivery status error";
  const matched = reason.match(/^([A-Za-z0-9_.-]{1,80}):/);
  const code = matched?.[1] || "unknown";
  return {
    code,
    reason,
    status: `check_error:${code}`.slice(0, 120),
  };
}

function addError(summary: QueueReconcileSummary, code: string): void {
  summary.errors[code] = (summary.errors[code] || 0) + 1;
}

function reconciliationWindow(now = Date.now()): {
  recentCutoff: string;
  retentionCutoff: string;
} {
  return {
    recentCutoff: new Date(now - RECENT_PRIORITY_MS).toISOString(),
    retentionCutoff: new Date(now - PROVIDER_STATUS_RETENTION_MS).toISOString(),
  };
}

async function notificationCandidates(
  env: ReconcileEnv,
  limit: number,
  cutoff: number,
): Promise<{
  items: NotificationCandidate[];
  recentCount: number;
  backlogCount: number;
}> {
  const window = reconciliationWindow();
  const [recentResult, backlogResult] = await Promise.all([
    env.DB.prepare(
      `SELECT message_id, MIN(email) AS email,
              MIN(provider_submitted_at) AS submitted_at
         FROM notification_outbox
        WHERE status = 'submitted'
          AND message_id IS NOT NULL
          AND message_id NOT LIKE 'worker:%'
          AND provider_submitted_at >= ?
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)
        GROUP BY message_id
        ORDER BY submitted_at
        LIMIT ?`,
    ).bind(window.recentCutoff, cutoff, limit).all<{
      message_id: string;
      email: string;
      submitted_at: string;
    }>(),
    env.DB.prepare(
      `SELECT message_id, MIN(email) AS email,
              MIN(provider_submitted_at) AS submitted_at
         FROM notification_outbox
        WHERE status = 'submitted'
          AND message_id IS NOT NULL
          AND message_id NOT LIKE 'worker:%'
          AND provider_submitted_at >= ?
          AND provider_submitted_at < ?
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)
        GROUP BY message_id
        ORDER BY submitted_at
        LIMIT ?`,
    ).bind(
      window.retentionCutoff,
      window.recentCutoff,
      cutoff,
      limit,
    ).all<{
      message_id: string;
      email: string;
      submitted_at: string;
    }>(),
  ]);
  const recent = recentResult.results.map((row) => ({
    messageId: row.message_id,
    email: row.email,
    submittedAt: row.submitted_at,
  }));
  const backlog = backlogResult.results.map((row) => ({
    messageId: row.message_id,
    email: row.email,
    submittedAt: row.submitted_at,
  }));
  return selectReconciliationCandidates(recent, backlog, limit);
}

async function claimNotificationMessages(
  env: ReconcileEnv,
  limit: number,
): Promise<{
  selectedRecent: number;
  selectedBacklog: number;
  messages: NotificationCandidate[];
}> {
  const now = Date.now();
  const cutoff = now - REFRESH_MS;
  const candidates = await notificationCandidates(env, limit, cutoff);
  const messages: NotificationCandidate[] = [];
  for (const candidate of candidates.items) {
    const result = await env.DB.prepare(
      `UPDATE notification_outbox
          SET provider_checked_at = ?
        WHERE message_id = ?
          AND status = 'submitted'
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)`,
    ).bind(now, candidate.messageId, cutoff).run();
    if (Number(result.meta.changes || 0) > 0) messages.push(candidate);
  }
  return {
    selectedRecent: candidates.recentCount,
    selectedBacklog: candidates.backlogCount,
    messages,
  };
}

async function reconcileNotificationMessages(
  env: ReconcileEnv,
  limit: number,
): Promise<QueueReconcileSummary> {
  const claimed = await claimNotificationMessages(env, limit);
  const summary = emptySummary();
  summary.selectedRecent = claimed.selectedRecent;
  summary.selectedBacklog = claimed.selectedBacklog;
  summary.selected = claimed.selectedRecent + claimed.selectedBacklog;
  summary.claimed = claimed.messages.length;

  for (const message of claimed.messages) {
    try {
      const provider = await getTencentEmailStatus(env, message.messageId, message.email);
      const normalized = normalizeTencentDeliveryStatus(provider);
      const checkedAt = Date.now();
      summary.checked += 1;
      if (normalized.state === "delivered") {
        const deliveredAt = normalized.deliveredAt || new Date().toISOString();
        const venues = (
          await env.DB.prepare(
            `SELECT DISTINCT venue_id
               FROM notification_outbox
              WHERE message_id = ?`,
          ).bind(message.messageId).all<{ venue_id: string }>()
        ).results;
        const update = await env.DB.prepare(
          `UPDATE notification_outbox
              SET status = 'delivered', provider_status = ?,
                  provider_delivered_at = ?, provider_checked_at = ?,
                  provider_error = NULL, sent_at = ?
            WHERE message_id = ? AND status = 'submitted'`,
        ).bind(
          normalized.providerStatus,
          deliveredAt,
          checkedAt,
          deliveredAt,
          message.messageId,
        ).run();
        if (Number(update.meta.changes || 0) > 0) {
          if (venues.length) {
            await env.DB.batch(venues.map((venue) =>
              env.DB.prepare(
                `UPDATE venue_status
                    SET last_notification_at = ?, updated_at = ?
                  WHERE venue_id = ?`,
              ).bind(deliveredAt, deliveredAt, venue.venue_id)
            ));
          }
          summary.delivered += 1;
        }
      } else if (normalized.state === "failed") {
        const failedAt = new Date().toISOString();
        const update = await env.DB.prepare(
          `UPDATE notification_outbox
              SET status = 'failed', provider_status = ?,
                  provider_failed_at = ?, provider_checked_at = ?,
                  provider_error = ?, last_error = ?
            WHERE message_id = ? AND status = 'submitted'`,
        ).bind(
          normalized.providerStatus,
          failedAt,
          checkedAt,
          normalized.error,
          normalized.error,
          message.messageId,
        ).run();
        if (Number(update.meta.changes || 0) > 0) summary.failed += 1;
      } else {
        const update = await env.DB.prepare(
          `UPDATE notification_outbox
              SET provider_status = ?, provider_checked_at = ?, provider_error = NULL
            WHERE message_id = ? AND status = 'submitted'`,
        ).bind(normalized.providerStatus, checkedAt, message.messageId).run();
        if (Number(update.meta.changes || 0) > 0) summary.pending += 1;
      }
    } catch (error) {
      const detail = providerCheckError(error);
      const checkedAt = Date.now();
      await env.DB.prepare(
        `UPDATE notification_outbox
            SET provider_status = ?, provider_checked_at = ?, provider_error = ?
          WHERE message_id = ? AND status = 'submitted'`,
      ).bind(detail.status, checkedAt, detail.reason, message.messageId).run();
      summary.unavailable += 1;
      addError(summary, detail.code);
      console.warn(JSON.stringify({
        event: "notification_delivery_reconcile_failed",
        errorCode: detail.code,
      }));
    }
  }
  return summary;
}

async function systemEmailCandidates(
  env: ReconcileEnv,
  limit: number,
  cutoff: number,
): Promise<{
  items: SystemEmailCandidate[];
  recentCount: number;
  backlogCount: number;
}> {
  const window = reconciliationWindow();
  const [recentResult, backlogResult] = await Promise.all([
    env.DB.prepare(
      `SELECT id, provider_message_id, email, submitted_at
         FROM system_email_outbox
        WHERE status = 'submitted'
          AND provider_message_id IS NOT NULL
          AND provider_message_id NOT LIKE 'worker:%'
          AND submitted_at >= ?
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)
        ORDER BY submitted_at
        LIMIT ?`,
    ).bind(window.recentCutoff, cutoff, limit).all<{
      id: string;
      provider_message_id: string;
      email: string;
      submitted_at: string;
    }>(),
    env.DB.prepare(
      `SELECT id, provider_message_id, email, submitted_at
         FROM system_email_outbox
        WHERE status = 'submitted'
          AND provider_message_id IS NOT NULL
          AND provider_message_id NOT LIKE 'worker:%'
          AND submitted_at >= ?
          AND submitted_at < ?
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)
        ORDER BY submitted_at
        LIMIT ?`,
    ).bind(
      window.retentionCutoff,
      window.recentCutoff,
      cutoff,
      limit,
    ).all<{
      id: string;
      provider_message_id: string;
      email: string;
      submitted_at: string;
    }>(),
  ]);
  const recent = recentResult.results.map((row) => ({
    id: row.id,
    messageId: row.provider_message_id,
    email: row.email,
    submittedAt: row.submitted_at,
  }));
  const backlog = backlogResult.results.map((row) => ({
    id: row.id,
    messageId: row.provider_message_id,
    email: row.email,
    submittedAt: row.submitted_at,
  }));
  return selectReconciliationCandidates(recent, backlog, limit);
}

async function claimSystemEmails(
  env: ReconcileEnv,
  limit: number,
): Promise<{
  selectedRecent: number;
  selectedBacklog: number;
  rows: SystemEmailCandidate[];
}> {
  const now = Date.now();
  const cutoff = now - REFRESH_MS;
  const candidates = await systemEmailCandidates(env, limit, cutoff);
  const rows: SystemEmailCandidate[] = [];
  for (const candidate of candidates.items) {
    const result = await env.DB.prepare(
      `UPDATE system_email_outbox
          SET provider_checked_at = ?, updated_at = ?
        WHERE id = ?
          AND status = 'submitted'
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)`,
    ).bind(now, new Date(now).toISOString(), candidate.id, cutoff).run();
    if (Number(result.meta.changes || 0) > 0) rows.push(candidate);
  }
  return {
    selectedRecent: candidates.recentCount,
    selectedBacklog: candidates.backlogCount,
    rows,
  };
}

async function reconcileSystemEmails(
  env: ReconcileEnv,
  limit: number,
): Promise<QueueReconcileSummary> {
  const claimed = await claimSystemEmails(env, limit);
  const summary = emptySummary();
  summary.selectedRecent = claimed.selectedRecent;
  summary.selectedBacklog = claimed.selectedBacklog;
  summary.selected = claimed.selectedRecent + claimed.selectedBacklog;
  summary.claimed = claimed.rows.length;

  for (const row of claimed.rows) {
    try {
      const provider = await getTencentEmailStatus(env, row.messageId, row.email);
      const normalized = normalizeTencentDeliveryStatus(provider);
      const checkedAt = Date.now();
      const nowIso = new Date(checkedAt).toISOString();
      summary.checked += 1;
      if (normalized.state === "delivered") {
        const update = await env.DB.prepare(
          `UPDATE system_email_outbox
              SET status = 'delivered', provider_status = ?, delivered_at = ?,
                  provider_checked_at = ?, last_error = NULL, updated_at = ?
            WHERE id = ? AND status = 'submitted'`,
        ).bind(
          normalized.providerStatus,
          normalized.deliveredAt || nowIso,
          checkedAt,
          nowIso,
          row.id,
        ).run();
        if (Number(update.meta.changes || 0) > 0) summary.delivered += 1;
      } else if (normalized.state === "failed") {
        const update = await env.DB.prepare(
          `UPDATE system_email_outbox
              SET status = 'failed', provider_status = ?, failed_at = ?,
                  provider_checked_at = ?, last_error = ?, updated_at = ?
            WHERE id = ? AND status = 'submitted'`,
        ).bind(
          normalized.providerStatus,
          nowIso,
          checkedAt,
          normalized.error,
          nowIso,
          row.id,
        ).run();
        if (Number(update.meta.changes || 0) > 0) summary.failed += 1;
      } else {
        const update = await env.DB.prepare(
          `UPDATE system_email_outbox
              SET provider_status = ?, provider_checked_at = ?,
                  last_error = NULL, updated_at = ?
            WHERE id = ? AND status = 'submitted'`,
        ).bind(normalized.providerStatus, checkedAt, nowIso, row.id).run();
        if (Number(update.meta.changes || 0) > 0) summary.pending += 1;
      }
    } catch (error) {
      const detail = providerCheckError(error);
      const checkedAt = Date.now();
      const nowIso = new Date(checkedAt).toISOString();
      await env.DB.prepare(
        `UPDATE system_email_outbox
            SET provider_status = ?, provider_checked_at = ?,
                last_error = ?, updated_at = ?
          WHERE id = ? AND status = 'submitted'`,
      ).bind(detail.status, checkedAt, detail.reason, nowIso, row.id).run();
      summary.unavailable += 1;
      addError(summary, detail.code);
      console.warn(JSON.stringify({
        event: "system_email_delivery_reconcile_failed",
        errorCode: detail.code,
      }));
    }
  }
  return summary;
}

export async function reconcileDeliveryStatuses(
  env: ReconcileEnv,
  limitPerQueue = 5,
): Promise<DeliveryReconcileSummary> {
  const [notifications, systemEmails] = await Promise.all([
    reconcileNotificationMessages(env, limitPerQueue),
    reconcileSystemEmails(env, limitPerQueue),
  ]);
  return { notifications, systemEmails };
}
