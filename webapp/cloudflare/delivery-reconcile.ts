import { normalizeTencentDeliveryStatus } from "./email-lifecycle";
import { getTencentEmailStatus, type TencentSecrets } from "./tencent-ses";

type ReconcileEnv = TencentSecrets & {
  DB: D1Database;
};

const REFRESH_MS = 5 * 60_000;

async function claimNotificationMessages(
  env: ReconcileEnv,
  limit: number,
): Promise<Array<{ messageId: string }>> {
  const now = Date.now();
  const candidates = (
    await env.DB.prepare(
      `SELECT message_id
         FROM notification_outbox
        WHERE status = 'submitted'
          AND message_id IS NOT NULL
          AND message_id NOT LIKE 'worker:%'
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)
        GROUP BY message_id
        ORDER BY MIN(provider_submitted_at)
        LIMIT ?`,
    ).bind(now - REFRESH_MS, limit).all<{ message_id: string }>()
  ).results;

  const claimed: Array<{ messageId: string }> = [];
  for (const candidate of candidates) {
    const result = await env.DB.prepare(
      `UPDATE notification_outbox
          SET provider_checked_at = ?
        WHERE message_id = ?
          AND status = 'submitted'
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)`,
    ).bind(now, candidate.message_id, now - REFRESH_MS).run();
    if (Number(result.meta.changes || 0) > 0) claimed.push({ messageId: candidate.message_id });
  }
  return claimed;
}

async function reconcileNotificationMessages(env: ReconcileEnv, limit: number): Promise<void> {
  const messages = await claimNotificationMessages(env, limit);
  for (const message of messages) {
    try {
      // MessageId is globally sufficient for GetSendEmailStatus and avoids a
      // second matching condition that can cause a valid provider record to be missed.
      const provider = await getTencentEmailStatus(env, message.messageId);
      const normalized = normalizeTencentDeliveryStatus(provider);
      const checkedAt = Date.now();
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
      } else {
        await env.DB.prepare(
          `UPDATE notification_outbox
              SET provider_status = ?, provider_checked_at = ?
            WHERE message_id = ? AND status = 'submitted'`,
        ).bind(normalized.providerStatus, checkedAt, message.messageId).run();
      }
    } catch (error) {
      console.warn(JSON.stringify({
        event: "notification_delivery_reconcile_failed",
        reason: error instanceof Error ? error.message.slice(0, 200) : "unknown",
      }));
    }
  }
}

async function claimSystemEmails(
  env: ReconcileEnv,
  limit: number,
): Promise<Array<{ id: string; messageId: string }>> {
  const now = Date.now();
  const candidates = (
    await env.DB.prepare(
      `SELECT id, provider_message_id
         FROM system_email_outbox
        WHERE status = 'submitted'
          AND provider_message_id IS NOT NULL
          AND provider_message_id NOT LIKE 'worker:%'
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)
        ORDER BY submitted_at
        LIMIT ?`,
    ).bind(now - REFRESH_MS, limit).all<{ id: string; provider_message_id: string }>()
  ).results;

  const claimed: Array<{ id: string; messageId: string }> = [];
  for (const candidate of candidates) {
    const result = await env.DB.prepare(
      `UPDATE system_email_outbox
          SET provider_checked_at = ?, updated_at = ?
        WHERE id = ?
          AND status = 'submitted'
          AND (provider_checked_at IS NULL OR provider_checked_at < ?)`,
    ).bind(now, new Date(now).toISOString(), candidate.id, now - REFRESH_MS).run();
    if (Number(result.meta.changes || 0) > 0) {
      claimed.push({ id: candidate.id, messageId: candidate.provider_message_id });
    }
  }
  return claimed;
}

async function reconcileSystemEmails(env: ReconcileEnv, limit: number): Promise<void> {
  const rows = await claimSystemEmails(env, limit);
  for (const row of rows) {
    try {
      const provider = await getTencentEmailStatus(env, row.messageId);
      const normalized = normalizeTencentDeliveryStatus(provider);
      const checkedAt = Date.now();
      const nowIso = new Date(checkedAt).toISOString();
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
      } else {
        await env.DB.prepare(
          `UPDATE system_email_outbox
              SET provider_status = ?, provider_checked_at = ?, updated_at = ?
            WHERE id = ? AND status = 'submitted'`,
        ).bind(normalized.providerStatus, checkedAt, nowIso, row.id).run();
      }
    } catch (error) {
      console.warn(JSON.stringify({
        event: "system_email_delivery_reconcile_failed",
        reason: error instanceof Error ? error.message.slice(0, 200) : "unknown",
      }));
    }
  }
}

export async function reconcileDeliveryStatuses(
  env: ReconcileEnv,
  limitPerQueue = 5,
): Promise<void> {
  await Promise.all([
    reconcileNotificationMessages(env, limitPerQueue),
    reconcileSystemEmails(env, limitPerQueue),
  ]);
}
