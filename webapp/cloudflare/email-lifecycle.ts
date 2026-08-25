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

function isNumericCode(value: string): boolean {
  return /^\d+$/.test(value);
}

function indicatesSendFailure(value: string): boolean {
  if (!value || value === "0") return false;
  if (isNumericCode(value)) return true;
  return ["failed", "failure", "rejected", "blocked", "error"].includes(value);
}

function indicatesDeliveryFailure(value: string): boolean {
  return [
    "2",
    "3",
    "failed",
    "failure",
    "bounced",
    "rejected",
    "blocked",
    "discarded",
    "dropped",
    "退信",
    "拒信",
    "丢弃",
  ].includes(value);
}

function failureMessage(value: string): boolean {
  return /mailbox unavailable|access denied|bounce|bounced|reject|rejected|blocked|discard|dropped|failed|failure|退信|拒信|丢弃|失败/i.test(
    value,
  );
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
  const providerStatus = `send=${send || "unknown"};deliver=${deliver || "pending"}`;

  // Tencent SES documents DeliverStatus=1 as the only numeric terminal
  // delivery-success state. DeliverStatus=0 is merely accepted/queued and 8 is
  // delayed, so neither may be promoted to delivered just because a timestamp
  // or explanatory message is present.
  const explicitDelivered = deliver === "1"
    || ["delivered", "success", "succeeded", "投递成功"].includes(deliver);
  if (explicitDelivered) {
    return {
      state: "delivered",
      providerStatus,
      deliveredAt: deliveredAt ?? new Date().toISOString(),
      error: null,
    };
  }

  const sendFailed = indicatesSendFailure(send);
  const deliveryFailed = indicatesDeliveryFailure(deliver);
  const messageFailedWithoutProviderState = !deliver && failureMessage(message);
  if (sendFailed || deliveryFailed || messageFailedWithoutProviderState) {
    return {
      state: "failed",
      providerStatus,
      deliveredAt: null,
      error: message || "腾讯云报告邮件发送或投递失败",
    };
  }

  // Older or partial provider records can omit DeliverStatus while still
  // returning DeliverTime. Keep this compatibility fallback, but never let it
  // override an explicit queued (0), failed (2/3), or delayed (8) status.
  if (!deliver && deliveredAt) {
    return {
      state: "delivered",
      providerStatus,
      deliveredAt,
      error: null,
    };
  }

  return {
    state: "submitted",
    providerStatus,
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
