export const VENUES = {
  szw: "深圳湾",
  gba: "大湾区网球场",
  sysh: "上越沙河",
  tops: "TOPS 科技园",
  tyzx: "深圳市体育中心",
  jdwx: "金地威新",
} as const;

export type VenueId = keyof typeof VENUES;

export type SubscriptionInput = {
  venueIds: VenueId[];
  startTime: string;
  endTime: string;
  durationDays: number;
};

export type SlotObservation = {
  date: string;
  courtName: string;
  startTime: string;
  endTime: string;
};

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const TIME_PATTERN = /^(?:[01]\d|2[0-3]):[0-5]\d$/;

export function normalizeEmail(value: unknown): string {
  const email = String(value ?? "").trim().toLowerCase();
  if (!EMAIL_PATTERN.test(email) || email.length > 254) {
    throw new Error("请输入有效的邮箱地址");
  }
  return email;
}

export function maskEmail(email: string): string {
  const [local, domain] = email.split("@");
  const visible = local.length <= 1 ? local : local.slice(0, Math.min(2, local.length));
  return `${visible}${"*".repeat(Math.max(3, local.length - visible.length))}@${domain}`;
}

export function parseTime(value: string): number {
  if (!TIME_PATTERN.test(value)) {
    throw new Error("时间格式无效");
  }
  const [hours, minutes] = value.split(":").map(Number);
  return hours * 60 + minutes;
}

export function validateSubscriptionInput(value: unknown): SubscriptionInput {
  if (!value || typeof value !== "object") {
    throw new Error("订阅参数无效");
  }
  const candidate = value as Record<string, unknown>;
  if (!Array.isArray(candidate.venueIds)) {
    throw new Error("请至少选择一个场地");
  }
  const venueIds = Array.from(new Set(candidate.venueIds.map(String))).filter(
    (item): item is VenueId => item in VENUES,
  );
  if (!venueIds.length || venueIds.length !== candidate.venueIds.length) {
    throw new Error("场地选择无效");
  }

  const startTime = String(candidate.startTime ?? "");
  const endTime = String(candidate.endTime ?? "");
  if (parseTime(startTime) >= parseTime(endTime)) {
    throw new Error("结束时间必须晚于开始时间");
  }

  const durationDays = Number(candidate.durationDays);
  if (!Number.isInteger(durationDays) || durationDays < 7 || durationDays > 14) {
    throw new Error("订阅有效期必须为 7–14 天");
  }

  return { venueIds, startTime, endTime, durationDays };
}

export function validateSlotObservation(value: unknown): SlotObservation {
  if (!value || typeof value !== "object") {
    throw new Error("场地数据无效");
  }
  const candidate = value as Record<string, unknown>;
  const date = String(candidate.date ?? "");
  const courtName = String(candidate.court_name ?? candidate.courtName ?? "").trim();
  const startTime = String(candidate.start_time ?? candidate.startTime ?? "");
  const endTime = String(candidate.end_time ?? candidate.endTime ?? "");
  const [year, month, day] = date.split("-").map(Number);
  const parsedDate = new Date(Date.UTC(year, month - 1, day));
  const validDate = /^\d{4}-\d{2}-\d{2}$/.test(date)
    && parsedDate.getUTCFullYear() === year
    && parsedDate.getUTCMonth() === month - 1
    && parsedDate.getUTCDate() === day;
  if (!validDate || !courtName || courtName.length > 100) {
    throw new Error("场地数据无效");
  }
  if (parseTime(startTime) >= parseTime(endTime)) {
    throw new Error("场地时段无效");
  }
  return { date, courtName, startTime, endTime };
}

export function slotMatchesTimeRange(
  slot: SlotObservation,
  startTime: string,
  endTime: string,
): boolean {
  return parseTime(slot.startTime) < parseTime(endTime)
    && parseTime(slot.endTime) > parseTime(startTime);
}

export function activeUntilIso(durationDays: number, now = new Date()): string {
  return new Date(now.getTime() + durationDays * 86_400_000).toISOString();
}

export function formatSlotLine(venueName: string, slot: SlotObservation): string {
  const date = new Date(`${slot.date}T12:00:00+08:00`);
  const weekday = new Intl.DateTimeFormat("zh-CN", {
    weekday: "long",
    timeZone: "Asia/Shanghai",
  }).format(date);
  const location = slot.courtName.startsWith(venueName)
    ? slot.courtName
    : `${venueName}${slot.courtName}`;
  return `${location} ${slot.date.slice(5)} ${weekday} ${slot.startTime}-${slot.endTime}`;
}

export async function sha256Hex(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function randomToken(byteLength = 32): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

export function randomVerificationCode(): string {
  const bytes = new Uint32Array(1);
  crypto.getRandomValues(bytes);
  return String(bytes[0] % 1_000_000).padStart(6, "0");
}
