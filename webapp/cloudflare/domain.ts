export const VENUES = {
  szw: "深圳湾",
  gba: "大湾区网球场",
  dsh_free: "大沙河免费场",
  dsh: "大沙河国际网球中心",
  sysh: "上越沙河",
  tops: "TOPS 科技园",
  fsb: "泛思博特福中福",
  fsb_shenyun: "泛思博特深云",
  fsb_shekou: "泛思博特蛇口",
  fsb_xinan: "泛思博特新安",
  fsb_zhengzhong: "泛思博特正中",
  fsb_atuoshan: "泛思博特安托山",
  fsb_zonglvquan: "泛思博特棕榈泉",
  fsb_guanhu: "泛思博特观湖",
  fsb_bantian: "泛思博特坂田",
  fsb_shahe: "泛思博特沙河",
  fsb_baoshui: "泛思博特保税",
  fsb_nanyou: "泛思博特南油",
  fsb_xinqiao: "泛思博特新桥",
  fsb_yifangcheng: "泛思博特壹方城",
  fsb_qilin: "泛思博特麒麟",
  fsb_maozhouhe: "泛思博特茅洲河",
  fft_qianhai: "FFTENNIS前海国际网球中心",
  ppba: "PICKLE POP宝安",
  tyzx: "深圳市体育中心",
  jdwx: "金地威新",
} as const;

export type VenueId = keyof typeof VENUES;

export const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7] as const;
export type Weekday = (typeof WEEKDAYS)[number];
export const ALL_WEEKDAY_MASK = 127;

export type SubscriptionInput = {
  venueIds: VenueId[];
  weekdays: Weekday[];
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

export function normalizeWeekdays(value: unknown): Weekday[] {
  if (value === undefined) return [...WEEKDAYS];
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error("请至少选择一个星期");
  }
  const weekdays = Array.from(new Set(value.map(Number))).sort((left, right) => left - right);
  if (
    weekdays.length === 0
    || weekdays.some((weekday) => !Number.isInteger(weekday) || weekday < 1 || weekday > 7)
  ) {
    throw new Error("星期选择无效");
  }
  return weekdays as Weekday[];
}

export function weekdayMaskFromDays(weekdays: readonly Weekday[]): number {
  if (!weekdays.length) throw new Error("请至少选择一个星期");
  return weekdays.reduce((mask, weekday) => mask | (1 << (weekday - 1)), 0);
}

export function weekdaysFromMask(value: number | null | undefined): Weekday[] {
  const mask = Number.isInteger(value) && Number(value) >= 1 && Number(value) <= ALL_WEEKDAY_MASK
    ? Number(value)
    : ALL_WEEKDAY_MASK;
  return WEEKDAYS.filter((weekday) => Boolean(mask & (1 << (weekday - 1))));
}

export function bookingDateWeekday(date: string): Weekday {
  const [year, month, day] = date.split("-").map(Number);
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  return (weekday === 0 ? 7 : weekday) as Weekday;
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

  const legacyDurationDays = Number(candidate.durationDays);
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

  const weekdays = normalizeWeekdays(candidate.weekdays);

  return { venueIds, weekdays, startTime, endTime, durationDays };
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

export function slotMatchesWeekday(slot: SlotObservation, weekdayMask: number): boolean {
  const weekday = bookingDateWeekday(slot.date);
  return Boolean(weekdayMask & (1 << (weekday - 1)));
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

export function formatNotificationDigest(lines: string[]): { subject: string; body: string } {
  const uniqueLines = Array.from(new Set(lines.map((line) => line.trim()).filter(Boolean)));
  const intervalPattern = /^(.*) ((?:[01]\d|2[0-3]):[0-5]\d)-((?:[01]\d|2[0-3]):[0-5]\d)$/;
  const intervalGroups = new Map<string, Array<{ start: string; end: string }>>();
  const outputOrder: string[] = [];
  const unparsed = new Map<string, string>();
  for (const line of uniqueLines) {
    const match = line.match(intervalPattern);
    if (!match) {
      const key = `line:${line}`;
      outputOrder.push(key);
      unparsed.set(key, line);
      continue;
    }
    const prefix = match[1];
    const key = `interval:${prefix}`;
    if (!intervalGroups.has(key)) outputOrder.push(key);
    const intervals = intervalGroups.get(key) || [];
    intervals.push({ start: match[2], end: match[3] });
    intervalGroups.set(key, intervals);
  }
  const compactedLines = outputOrder.flatMap((key) => {
    const plainLine = unparsed.get(key);
    if (plainLine) return [plainLine];
    const prefix = key.slice("interval:".length);
    const intervals = (intervalGroups.get(key) || []).sort((left, right) =>
      left.start.localeCompare(right.start)
    );
    const merged: Array<{ start: string; end: string }> = [];
    for (const interval of intervals) {
      const previous = merged.at(-1);
      if (previous && interval.start <= previous.end) {
        if (interval.end > previous.end) previous.end = interval.end;
      } else {
        merged.push({ ...interval });
      }
    }
    return merged.map((interval) => `${prefix} ${interval.start}-${interval.end}`);
  });
  if (!compactedLines.length) throw new Error("通知内容为空");
  return {
    subject: compactedLines.length === 1
      ? compactedLines[0]
      : `${compactedLines[0]} 等 ${compactedLines.length} 个时段`,
    body: compactedLines.join("\n"),
  };
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
