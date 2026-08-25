import { normalizeTencentDeliveryStatus } from "./email-lifecycle";
import {
  getTencentEmailStatus,
  type TencentSecrets,
} from "./tencent-ses";

export type EmailReconciliationEnv = TencentSecrets & {
  DB: D1Database;
};

type ReconciliationLogger = Pick<Console, "info" | "warn" | "error">;

type ReconciliationCounters = {
  selected: number;
  delivered: number;
  failed: number;
  pending: number;
  errors: number;
};

export type EmailReconciliationSummary = {
  notifications: ReconciliationCounters;
  systemEmails: ReconciliationCounters;
};

const DELIVERY_STATUS_REFRESH_MS = 5 * 60_000;
const NOTIFICATION_BATCH_SIZE = 20;
const SYSTEM_EMAIL_BATCH_SIZE = 20;

function counters(selected: number): ReconciliationCounters {
  return {
    selected,
    delivered: 0,
    failed: 0,
    pending: 0,
    errors: 0,
  };
}

function errorReason(error: unknown): string {
  return error instanceof Error ? error.message.slice(0, 200) : "unknown";
}

async function reconcileNotificationDeliveries(
  env: EmailReconciliationEnv,
  logger: ReconciliationLogger,
): Promise<ReconciliationCounters> {
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
    ).bind(now - DELIVERY_STATUS_REFRESH_MS, NOTIFICATION_BATCH_SIZE).all<{
      message_id: string;
      email: string;
    }>()
  ).results;
  const result = counters(messages.length);

  for (const message of messages) {
    try {
      const provider = await getTencentEmailStatus(env, message.message_id, message.email);
      const normalized = normalizeTencentDeliveryStatus(provider);
      const checkedAt = Date.now();

      if (normalized.state === "delivered") {
        const deliveredAt = normalized.deliveredAt || new Date().toISOString();
        const venues = (
          await env.DB.prepare(
            `SELECT DISTINCT venue_id
               FROM notification_outbox
              WHERE message_id = ?`,
          ).bind(message.message_id).all<{ venue_id: string }>()
        ).results;
        const updates: D1PreparedStatement[] = [
          env.DB.prepare(
            `UPDATE notification_outbox
                SET status = 'delivered',
                    provider_status = ?,
                    provider_delivered_at = ?,
                    provider_checked_at = ?,
                    provider_error = NULL,
                    last_error = NULL,
                    sent_at = ?
              WHERE message_id = ?
                AND status = 'submitted'`,
          ).bind(
            normalized.providerStatus,
            deliveredAt,
            checkedAt,
            deliveredAt,
            message.message_id,
          ),
        ];
        for (const venue of venues) {
          updates.push(
            env.DB.prepare(
              `UPDATE venue_status
                  SET last_notification_at = ?, updated_at = ?
                WHERE venue_id = ?`,
            ).bind(deliveredAt, deliveredAt, venue.venue_id),
          );
        }
        await env.DB.batch(updates);
        result.delivered += 1;
        continue;
      }

      if (normalized.state === "failed") {
        const failedAt = new Date().toISOString();
        await env.DB.prepare(
          `UPDATE notification_outbox
              SET status = 'failed',
                  provider_status = ?,
                  provider_failed_at = ?,
                  provider_checked_at = ?,
                  provider_error = ?,
                  last_error = ?
            WHERE message_id = ?
              AND status = 'submitted'`,
        ).bind(
          normalized.providerStatus,
          failedAt,
          checkedAt,
          normalized.error,
          normalized.error,
          message.message_id,
        ).run();
        result.failed += 1;
        continue;
      }

      await env.DB.prepare(
        `UPDATE notification_outbox
            SET provider_status = ?,
                provider_checked_at = ?,
                provider_error = NULL
          WHERE message_id = ?
            AND status = 'submitted'`,
      ).bind(normalized.providerStatus, checkedAt, message.message_id).run();
      result.pending += 1;
    } catch (error) {
      const reason = errorReason(error);
      const checkedAt = Date.now();
      result.errors += 1;
      try {
        await env.DB.prepare(
          `UPDATE notification_outbox
              SET provider_status = 'check_error',
                  provider_checked_at = ?,
                  provider_error = ?,
                  last_error = ?
            WHERE message_id = ?
              AND status = 'submitted'`,
        ).bind(checkedAt, reason, reason, message.message_id).run();
      } catch (recordError) {
        logger.error(JSON.stringify({
          event: "notification_delivery_check_record_failed",
          reason: errorReason(recordError),
        }));
      }
      logger.warn(JSON.stringify({
        event: "notification_delivery_status_unavailable",
        reason,
      }));
    }
  }

  return result;
}

async function reconcileSystemEmailDeliveries(
  env: EmailReconciliationEnv,
  logger: ReconciliationLogger,
): Promise<ReconciliationCounters> {
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
    ).bind(now - DELIVERY_STATUS_REFRESH_MS, SYSTEM_EMAIL_BATCH_SIZE).all<{
      id: string;
      email: string;
      provider_message_id: string;
    }>()
  ).results;
  const result = counters(rows.length);

  for (const row of rows) {
    try {
      const provider = await getTencentEmailStatus(env, row.provider_message_id, row.email);
      const normalized = normalizeTencentDeliveryStatus(provider);
      const checkedAt = Date.now();
      const currentIso = new Date().toISOString();

      if (normalized.state === "delivered") {
        await env.DB.prepare(
          `UPDATE system_email_outbox
              SET status = 'delivered',
                  provider_status = ?,
                  delivered_at = ?,
                  provider_checked_at = ?,
                  last_error = NULL,
                  updated_at = ?
            WHERE id = ?
              AND status = 'submitted'`,
        ).bind(
          normalized.providerStatus,
          normalized.deliveredAt || currentIso,
          checkedAt,
          currentIso,
          row.id,
        ).run();
        result.delivered += 1;
        continue;
      }

      if (normalized.state === "failed") {
        await env.DB.prepare(
          `UPDATE system_email_outbox
              SET status = 'failed',
                  provider_status = ?,
                  failed_at = ?,
                  provider_checked_at = ?,
                  last_error = ?,
                  updated_at = ?
            WHERE id = ?
              AND status = 'submitted'`,
        ).bind(
          normalized.providerStatus,
          currentIso,
          checkedAt,
          normalized.error,
          currentIso,
          row.id,
        ).run();
        result.failed += 1;
        continue;
      }

      await env.DB.prepare(
        `UPDATE system_email_outbox
            SET provider_status = ?,
                provider_checked_at = ?,
                last_error = NULL,
                updated_at = ?
          WHERE id = ?
            AND status = 'submitted'`,
      ).bind(normalized.providerStatus, checkedAt, currentIso, row.id).run();
      result.pending += 1;
    } catch (error) {
      const reason = errorReason(error);
      const checkedAt = Date.now();
      const currentIso = new Date().toISOString();
      result.errors += 1;
      try {
        await env.DB.prepare(
          `UPDATE system_email_outbox
              SET provider_status = 'check_error',
                  provider_checked_at = ?,
                  last_error = ?,
                  updated_at = ?
            WHERE id = ?
              AND status = 'submitted'`,
        ).bind(checkedAt, reason, currentIso, row.id).run();
      } catch (recordError) {
        logger.error(JSON.stringify({
          event: "system_email_delivery_check_record_failed",
          reason: errorReason(recordError),
        }));
      }
      logger.warn(JSON.stringify({
        event: "system_email_delivery_status_unavailable",
        reason,
      }));
    }
  }

  return result;
}

export async function reconcileEmailDeliveries(
  env: EmailReconciliationEnv,
  logger: ReconciliationLogger = console,
): Promise<EmailReconciliationSummary> {
  const notifications = await reconcileNotificationDeliveries(env, logger);
  const systemEmails = await reconcileSystemEmailDeliveries(env, logger);
  const summary = { notifications, systemEmails };
  logger.info(JSON.stringify({
    event: "email_delivery_reconciliation_completed",
    ...summary,
  }));
  return summary;
}

export async function runEmailReconciliationSafely(
  env: EmailReconciliationEnv,
  logger: ReconciliationLogger = console,
  reconcile: typeof reconcileEmailDeliveries = reconcileEmailDeliveries,
): Promise<EmailReconciliationSummary | null> {
  try {
    return await reconcile(env, logger);
  } catch (error) {
    logger.error(JSON.stringify({
      event: "email_delivery_reconciliation_failed",
      reason: errorReason(error),
    }));
    return null;
  }
}
