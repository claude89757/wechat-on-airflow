export type DeliveryState = "submitted" | "delivered" | "failed";

export type TencentEmailStatusRecord = {
  MessageId?: string;
  ToEmailAddress?: string;
  SendStatus?: number | string;
  DeliverStatus?: number | string;
  DeliverTime?: number | string;
  DeliverMessage?: string;
};

export type NormalizedDeliveryStatus = {
  state: DeliveryState;
  providerStatus: string;
  deliveredAt: string | null;
  error: string | null;
};

function validDate(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  const numeric = Number(value);
  const date = Number.isFinite(numeric) && numeric > 0
    ? new Date(numeric > 10_000_000_000 ? numeric : numeric * 1000)
    : new Date(String(value));
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function normalizeTencentDeliveryStatus(
  record: TencentEmailStatusRecord | null,
): NormalizedDeliveryStatus {
  if (!record) {
    return {
      state: "submitted",
      providerStatus: "not_found",
      deliveredAt: null,
      error: null,
    };
  }
  const deliveredAt = validDate(record.DeliverTime);
  const deliver = String(record.DeliverStatus ?? "").trim().toLowerCase();
  const send = String(record.SendStatus ?? "").trim().toLowerCase();
  const message = String(record.DeliverMessage ?? "").trim();
  const explicitDelivered = deliveredAt !== null
    || ["delivered", "success", "succeeded", "投递成功"].includes(deliver);
  if (explicitDelivered) {
    return {
      state: "delivered",
      providerStatus: `send=${send || "unknown"};deliver=${deliver || "delivered"}`,
      deliveredAt: deliveredAt ?? new Date().toISOString(),
      error: null,
    };
  }
  const explicitFailure = [
    "failed", "failure", "bounced", "rejected", "blocked", "2", "3", "4", "5",
  ].includes(deliver)
    || ["failed", "failure", "rejected", "2", "3", "4", "5"].includes(send)
    || Boolean(message && !/success|deliver|投递成功/i.test(message));
  if (explicitFailure) {
    return {
      state: "failed",
      providerStatus: `send=${send || "unknown"};deliver=${deliver || "failed"}`,
      deliveredAt: null,
      error: message || "腾讯云报告邮件投递失败",
    };
  }
  return {
    state: "submitted",
    providerStatus: `send=${send || "unknown"};deliver=${deliver || "pending"}`,
    deliveredAt: null,
    error: null,
  };
}

export function shouldEnqueueExpiryReminder(
  activeUntil: string,
  now = new Date(),
): boolean {
  const expiry = Date.parse(activeUntil);
  if (!Number.isFinite(expiry)) return false;
  const remaining = expiry - now.getTime();
  return remaining > 0 && remaining <= 86_400_000;
}
