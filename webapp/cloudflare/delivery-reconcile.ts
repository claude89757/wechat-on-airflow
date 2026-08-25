import { normalizeTencentDeliveryStatus } from "./email-lifecycle";
import { getTencentEmailStatus, type TencentSecrets } from "./tencent-ses";

type ReconcileEnv = TencentSecrets & {
  DB: D1Database;
};

export type QueueReconcileSummary = {
  selected: number;
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

function emptySummary(selected = 0): QueueReconcileSummary {
  return {
    selected,
    claimed: 0,
    checked: 0,
    delivered: 0,
    failed: 0,
    pending: 0,
    unavailable: 0,
    errors: {},
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

async function claimNotificationMessages(
  env: ReconcileEnv,
  limit: number,
): Promise<{
  selected: number;
  messages: Array<{ messageId: string; email: string }>;
}> {
  const now = Date.now();
  const cutoff = now - REFRESH_MS;
  const candidates = (
    await env.DB.prepare(
      `SELECT DISTINCT message_id, email, provider_submitted_at
         FROM notification_outbox
        WHERE status = 'submitted'
          AND message_id IS NOT NULL
          AND message_id NOT LIKE 'worker:%'
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)
        ORDER BY provider_submitted_at
        LIMIT ?`,
    ).bind(cutoff, limit).all<{
      message_id: string;
      email: string;
      provider_submitted_at: string;
    }>()
  ).results;

  const messages: Array<{ messageId: string; email: string }> = [];
  for (const candidate of candidates) {
    const result = await env.DB.prepare(
      `UPDATE notification_outbox
          SET provider_checked_at = ?
        WHERE message_id = ?
          AND status = 'submitted'
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)`,
    ).bind(now, candidate.message_id, cutoff).run();
    if (Number(result.meta.changes || 0) > 0) {
      messages.push({ messageId: candidate.message_id, email: candidate.email });
    }
  }
  return { selected: candidates.length, messages };
}

async function reconcileNotificationMessages(
  env: ReconcileEnv,
  limit: number,
): Promise<QueueReconcileSummary> {
  const claimed = await claimNotificationMessages(env, limit);
  const summary = emptySummary(claimed.selected);
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
        const statements: D1PreparedStatement[] = [
          env.DB.prepare(
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
          ),
        ];
        for (const venue of venues) {
          statements.push(
            env.DB.prepare(
              `UPDATE venue_status
                  SET last_notification_at = ?, updated_at = ?
                WHERE venue_id = ?`,
            ).bind(deliveredAt, deliveredAt, venue.venue_id),
          );
        }
        await env.DB.batch(statements);
        summary.delivered += 1;
      } else if (normalized.state === "failed") {
        const failedAt = new Date().toISOString();
        await env.DB.prepare(
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
        summary.failed += 1;
      } else {
        await env.DB.prepare(
          `UPDATE notification_outbox
              SET provider_status = ?, provider_checked_at = ?, provider_error = NULL
            WHERE message_id = ? AND status = 'submitted'`,
        ).bind(normalized.providerStatus, checkedAt, message.messageId).run();
        summary.pending += 1;
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

async function claimSystemEmails(
  env: ReconcileEnv,
  limit: number,
): Promise<{
  selected: number;
  rows: Array<{ id: string; messageId: string; email: string }>;
}> {
  const now = Date.now();
  const cutoff = now - REFRESH_MS;
  const candidates = (
    await env.DB.prepare(
      `SELECT id, provider_message_id, email
         FROM system_email_outbox
        WHERE status = 'submitted'
          AND provider_message_id IS NOT NULL
          AND provider_message_id NOT LIKE 'worker:%'
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)
        ORDER BY submitted_at
        LIMIT ?`,
    ).bind(cutoff, limit).all<{
      id: string;
      provider_message_id: string;
      email: string;
    }>()
  ).results;

  const rows: Array<{ id: string; messageId: string; email: string }> = [];
  for (const candidate of candidates) {
    const result = await env.DB.prepare(
      `UPDATE system_email_outbox
          SET provider_checked_at = ?, updated_at = ?
        WHERE id = ?
          AND status = 'submitted'
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)`,
    ).bind(now, new Date(now).toISOString(), candidate.id, cutoff).run();
    if (Number(result.meta.changes || 0) > 0) {
      rows.push({
        id: candidate.id,
        messageId: candidate.provider_message_id,
        email: candidate.email,
      });
    }
  }
  return { selected: candidates.length, rows };
}

async function reconcileSystemEmails(
  env: ReconcileEnv,
  limit: number,
): Promise<QueueReconcileSummary> {
  const claimed = await claimSystemEmails(env, limit);
  const summary = emptySummary(claimed.selected);
  summary.claimed = claimed.rows.length;

  for (const row of claimed.rows) {
    try {
      const provider = await getTencentEmailStatus(env, row.messageId, row.email);
      const normalized = normalizeTencentDeliveryStatus(provider);
      const checkedAt = Date.now();
      const nowIso = new Date(checkedAt).toISOString();
      summary.checked += 1;
      if (normalized.state === "delivered") {
        await env.DB.prepare(
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
        summary.delivered += 1;
      } else if (normalized.state === "failed") {
        await env.DB.prepare(
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
        summary.failed += 1;
      } else {
        await env.DB.prepare(
          `UPDATE system_email_outbox
              SET provider_status = ?, provider_checked_at = ?,
                  last_error = NULL, updated_at = ?
            WHERE id = ? AND status = 'submitted'`,
        ).bind(normalized.providerStatus, checkedAt, nowIso, row.id).run();
        summary.pending += 1;
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
