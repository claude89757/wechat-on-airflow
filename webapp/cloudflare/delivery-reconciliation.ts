import type { VenueId } from "./domain";
import { normalizeTencentDeliveryStatus } from "./email-lifecycle";
import {
  getTencentEmailStatus,
  type TencentSecrets,
} from "./tencent-ses";

export type DeliveryReconciliationEnv = TencentSecrets & {
  DB: D1Database;
};

export type ReconciliationSummary = {
  selected: number;
  leased: number;
  checked: number;
  delivered: number;
  failed: number;
  pending: number;
  unavailable: number;
  errors: Record<string, number>;
};

export type DeliveryLifecycleSummary = {
  notifications: ReconciliationSummary;
  systemEmails: ReconciliationSummary;
};

const DEFAULT_BATCH_LIMIT = 20;
const MAX_BATCH_LIMIT = 50;
const REFRESH_INTERVAL_MS = 5 * 60_000;

function emptySummary(selected = 0): ReconciliationSummary {
  return {
    selected,
    leased: 0,
    checked: 0,
    delivered: 0,
    failed: 0,
    pending: 0,
    unavailable: 0,
    errors: {},
  };
}

function batchLimit(value: number | undefined): number {
  return Number.isInteger(value) && Number(value) > 0
    ? Math.min(Number(value), MAX_BATCH_LIMIT)
    : DEFAULT_BATCH_LIMIT;
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

function incrementError(summary: ReconciliationSummary, code: string): void {
  summary.errors[code] = (summary.errors[code] || 0) + 1;
}

async function reconcileNotificationDeliveries(
  env: DeliveryReconciliationEnv,
  limit: number,
): Promise<ReconciliationSummary> {
  const now = Date.now();
  const cutoff = now - REFRESH_INTERVAL_MS;
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
    ).bind(cutoff, limit).all<{
      message_id: string;
      email: string;
    }>()
  ).results;
  const summary = emptySummary(messages.length);

  for (const message of messages) {
    const lease = await env.DB.prepare(
      `UPDATE notification_outbox
          SET provider_checked_at = ?
        WHERE message_id = ?
          AND status = 'submitted'
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)`,
    ).bind(now, message.message_id, cutoff).run();
    if (!lease.meta.changes) continue;
    summary.leased += 1;

    if (message.message_id.startsWith("worker:")) {
      const detail = {
        code: "missing_provider_message_id",
        reason: "Tencent SendEmail did not return a provider MessageId",
        status: "check_error:missing_provider_message_id",
      };
      await env.DB.prepare(
        `UPDATE notification_outbox
            SET provider_status = ?, provider_error = ?, provider_checked_at = ?
          WHERE message_id = ? AND status = 'submitted'`,
      ).bind(detail.status, detail.reason, now, message.message_id).run();
      summary.unavailable += 1;
      incrementError(summary, detail.code);
      continue;
    }

    try {
      const provider = await getTencentEmailStatus(env, message.message_id, message.email);
      summary.checked += 1;
      const normalized = normalizeTencentDeliveryStatus(provider);
      if (normalized.state === "delivered") {
        const deliveredAt = normalized.deliveredAt || new Date().toISOString();
        const venues = (
          await env.DB.prepare(
            `SELECT DISTINCT venue_id
               FROM notification_outbox
              WHERE message_id = ?`,
          ).bind(message.message_id).all<{ venue_id: VenueId }>()
        ).results;
        const updates: D1PreparedStatement[] = [
          env.DB.prepare(
            `UPDATE notification_outbox
                SET status = 'delivered', provider_status = ?,
                    provider_delivered_at = ?, provider_checked_at = ?,
                    provider_error = NULL, sent_at = ?
              WHERE message_id = ? AND status = 'submitted'`,
          ).bind(
            normalized.providerStatus,
            deliveredAt,
            now,
            deliveredAt,
            message.message_id,
          ),
        ];
        for (const venue of venues) {
          updates.push(env.DB.prepare(
            `UPDATE venue_status
                SET last_notification_at = ?, updated_at = ?
              WHERE venue_id = ?`,
          ).bind(deliveredAt, deliveredAt, venue.venue_id));
        }
        await env.DB.batch(updates);
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
          now,
          normalized.error,
          normalized.error,
          message.message_id,
        ).run();
        summary.failed += 1;
      } else {
        await env.DB.prepare(
          `UPDATE notification_outbox
              SET provider_status = ?, provider_checked_at = ?, provider_error = NULL
            WHERE message_id = ? AND status = 'submitted'`,
        ).bind(normalized.providerStatus, now, message.message_id).run();
        summary.pending += 1;
      }
    } catch (error) {
      const detail = providerCheckError(error);
      await env.DB.prepare(
        `UPDATE notification_outbox
            SET provider_status = ?, provider_checked_at = ?, provider_error = ?
          WHERE message_id = ? AND status = 'submitted'`,
      ).bind(detail.status, now, detail.reason, message.message_id).run();
      summary.unavailable += 1;
      incrementError(summary, detail.code);
      console.warn(JSON.stringify({
        event: "notification_delivery_status_unavailable",
        errorCode: detail.code,
      }));
    }
  }
  return summary;
}

async function reconcileSystemEmailDeliveries(
  env: DeliveryReconciliationEnv,
  limit: number,
): Promise<ReconciliationSummary> {
  const now = Date.now();
  const cutoff = now - REFRESH_INTERVAL_MS;
  const rows = (
    await env.DB.prepare(
      `SELECT id, email, provider_message_id
         FROM system_email_outbox
        WHERE status = 'submitted'
          AND provider_message_id IS NOT NULL
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)
        ORDER BY submitted_at
        LIMIT ?`,
    ).bind(cutoff, limit).all<{
      id: string;
      email: string;
      provider_message_id: string;
    }>()
  ).results;
  const summary = emptySummary(rows.length);

  for (const row of rows) {
    const lease = await env.DB.prepare(
      `UPDATE system_email_outbox
          SET provider_checked_at = ?, updated_at = ?
        WHERE id = ?
          AND status = 'submitted'
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)`,
    ).bind(now, new Date(now).toISOString(), row.id, cutoff).run();
    if (!lease.meta.changes) continue;
    summary.leased += 1;

    if (row.provider_message_id.startsWith("worker:")) {
      const detail = {
        code: "missing_provider_message_id",
        reason: "Tencent SendEmail did not return a provider MessageId",
        status: "check_error:missing_provider_message_id",
      };
      await env.DB.prepare(
        `UPDATE system_email_outbox
            SET provider_status = ?, provider_checked_at = ?,
                last_error = ?, updated_at = ?
          WHERE id = ? AND status = 'submitted'`,
      ).bind(
        detail.status,
        now,
        detail.reason,
        new Date(now).toISOString(),
        row.id,
      ).run();
      summary.unavailable += 1;
      incrementError(summary, detail.code);
      continue;
    }

    try {
      const provider = await getTencentEmailStatus(
        env,
        row.provider_message_id,
        row.email,
      );
      summary.checked += 1;
      const normalized = normalizeTencentDeliveryStatus(provider);
      const currentIso = new Date().toISOString();
      if (normalized.state === "delivered") {
        await env.DB.prepare(
          `UPDATE system_email_outbox
              SET status = 'delivered', provider_status = ?, delivered_at = ?,
                  provider_checked_at = ?, last_error = NULL, updated_at = ?
            WHERE id = ? AND status = 'submitted'`,
        ).bind(
          normalized.providerStatus,
          normalized.deliveredAt || currentIso,
          now,
          currentIso,
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
          currentIso,
          now,
          normalized.error,
          currentIso,
          row.id,
        ).run();
        summary.failed += 1;
      } else {
        await env.DB.prepare(
          `UPDATE system_email_outbox
              SET provider_status = ?, provider_checked_at = ?,
                  last_error = NULL, updated_at = ?
            WHERE id = ? AND status = 'submitted'`,
        ).bind(normalized.providerStatus, now, currentIso, row.id).run();
        summary.pending += 1;
      }
    } catch (error) {
      const detail = providerCheckError(error);
      const currentIso = new Date().toISOString();
      await env.DB.prepare(
        `UPDATE system_email_outbox
            SET provider_status = ?, provider_checked_at = ?,
                last_error = ?, updated_at = ?
          WHERE id = ? AND status = 'submitted'`,
      ).bind(detail.status, now, detail.reason, currentIso, row.id).run();
      summary.unavailable += 1;
      incrementError(summary, detail.code);
      console.warn(JSON.stringify({
        event: "system_email_delivery_status_unavailable",
        errorCode: detail.code,
      }));
    }
  }
  return summary;
}

export async function reconcileDeliveryLifecycle(
  env: DeliveryReconciliationEnv,
  options: { limit?: number; source?: string } = {},
): Promise<DeliveryLifecycleSummary> {
  const limit = batchLimit(options.limit);
  const [notifications, systemEmails] = await Promise.all([
    reconcileNotificationDeliveries(env, limit),
    reconcileSystemEmailDeliveries(env, limit),
  ]);
  console.log(JSON.stringify({
    event: "delivery_lifecycle_reconciled",
    source: options.source || "unknown",
    notifications,
    systemEmails,
  }));
  return { notifications, systemEmails };
}
