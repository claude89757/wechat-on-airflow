export const VENUE_IDS = ["szw", "gba", "dsh_free", "sysh", "tops", "tyzx", "jdwx"] as const;

export type VenueId = (typeof VENUE_IDS)[number];

export type VenueStatus = {
  id: VenueId;
  name: string;
  healthy: boolean;
  subscriberCount: number;
  lastInspectionAt: string | null;
  lastNotificationAt: string | null;
};

export type Subscription = {
  id: string;
  venueIds: VenueId[];
  startTime: string;
  endTime: string;
  durationDays: number;
  activeUntil: string;
  active: boolean;
  createdAt: string;
};

export type Dashboard = {
  generatedAt: string;
  metrics: {
    activeSubscriptions: number;
    remindersToday: number;
    healthyVenues: number;
    totalVenues: number;
  };
  venues: VenueStatus[];
  identity: {
    verified: boolean;
    maskedEmail: string | null;
    remindersToday: number;
  };
  subscriptions: Subscription[];
};

export type VerificationReceipt = {
  token: string;
  email: string;
  maskedEmail: string;
  verifiedAt: string;
};

const RECEIPTS_KEY = "zacks-tennis-verified-emails-v1";

export const FALLBACK_DASHBOARD: Dashboard = {
  generatedAt: "2026-07-29T10:42:00+08:00",
  metrics: {
    activeSubscriptions: 128,
    remindersToday: 6,
    healthyVenues: 7,
    totalVenues: 7,
  },
  venues: [
    {
      id: "szw",
      name: "深圳湾",
      healthy: true,
      subscriberCount: 28,
      lastInspectionAt: "2026-07-29T10:41:40+08:00",
      lastNotificationAt: "2026-07-29T10:26:00+08:00",
    },
    {
      id: "gba",
      name: "大湾区网球场",
      healthy: true,
      subscriberCount: 0,
      lastInspectionAt: "2026-07-29T10:41:34+08:00",
      lastNotificationAt: null,
    },
    {
      id: "dsh_free",
      name: "大沙河免费场",
      healthy: true,
      subscriberCount: 0,
      lastInspectionAt: "2026-07-29T10:41:31+08:00",
      lastNotificationAt: null,
    },
    {
      id: "sysh",
      name: "上越沙河",
      healthy: true,
      subscriberCount: 24,
      lastInspectionAt: "2026-07-29T10:41:28+08:00",
      lastNotificationAt: "2026-07-29T09:41:00+08:00",
    },
    {
      id: "tops",
      name: "TOPS 科技园",
      healthy: true,
      subscriberCount: 22,
      lastInspectionAt: "2026-07-29T10:41:12+08:00",
      lastNotificationAt: "2026-07-29T08:58:00+08:00",
    },
    {
      id: "tyzx",
      name: "深圳市体育中心",
      healthy: true,
      subscriberCount: 30,
      lastInspectionAt: "2026-07-29T10:40:55+08:00",
      lastNotificationAt: "2026-07-29T07:32:00+08:00",
    },
    {
      id: "jdwx",
      name: "金地威新",
      healthy: true,
      subscriberCount: 24,
      lastInspectionAt: "2026-07-29T10:40:42+08:00",
      lastNotificationAt: null,
    },
  ],
  identity: { verified: false, maskedEmail: null, remindersToday: 0 },
  subscriptions: [],
};

export const EMPTY_DASHBOARD: Dashboard = {
  generatedAt: new Date().toISOString(),
  metrics: {
    activeSubscriptions: 0,
    remindersToday: 0,
    healthyVenues: 0,
    totalVenues: 7,
  },
  venues: FALLBACK_DASHBOARD.venues.map((venue) => ({
    ...venue,
    healthy: false,
    subscriberCount: 0,
    lastInspectionAt: null,
    lastNotificationAt: null,
  })),
  identity: { verified: false, maskedEmail: null, remindersToday: 0 },
  subscriptions: [],
};

function requestHeaders(receipt?: VerificationReceipt | null): HeadersInit {
  return receipt
    ? {
        Authorization: `Bearer ${receipt.token}`,
        "Content-Type": "application/json",
      }
    : { "Content-Type": "application/json" };
}

async function jsonRequest<T>(
  path: string,
  init: RequestInit = {},
  receipt?: VerificationReceipt | null,
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...requestHeaders(receipt),
      ...(init.headers ?? {}),
    },
  });

  const payload = (await response.json().catch(() => null)) as
    | (T & { error?: string })
    | null;
  if (!response.ok || !payload) {
    throw new Error(payload?.error || `请求失败 (${response.status})`);
  }
  return payload;
}

export function loadReceipts(): VerificationReceipt[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(RECEIPTS_KEY) || "[]") as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (item): item is VerificationReceipt =>
          Boolean(
            item &&
              typeof item === "object" &&
              typeof (item as VerificationReceipt).token === "string" &&
              typeof (item as VerificationReceipt).email === "string" &&
              typeof (item as VerificationReceipt).maskedEmail === "string" &&
              typeof (item as VerificationReceipt).verifiedAt === "string",
          ),
      )
      .slice(0, 3);
  } catch {
    return [];
  }
}

export function saveReceipt(receipt: VerificationReceipt): VerificationReceipt[] {
  const next = [
    receipt,
    ...loadReceipts().filter((item) => item.email.toLowerCase() !== receipt.email.toLowerCase()),
  ].slice(0, 3);
  localStorage.setItem(RECEIPTS_KEY, JSON.stringify(next));
  return next;
}

export function removeReceipt(token: string): VerificationReceipt[] {
  const next = loadReceipts().filter((item) => item.token !== token);
  localStorage.setItem(RECEIPTS_KEY, JSON.stringify(next));
  return next;
}

export async function getDashboard(
  receipt?: VerificationReceipt | null,
): Promise<Dashboard> {
  return jsonRequest<Dashboard>("/api/bootstrap", { method: "GET" }, receipt);
}

export async function requestVerificationCode(email: string): Promise<{
  challengeId: string;
  expiresInSeconds: number;
}> {
  return jsonRequest("/api/email/send-code", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export async function verifyEmail(
  challengeId: string,
  code: string,
): Promise<VerificationReceipt> {
  return jsonRequest("/api/email/verify", {
    method: "POST",
    body: JSON.stringify({ challengeId, code }),
  });
}

export async function createSubscription(
  receipt: VerificationReceipt,
  payload: {
    venueIds: VenueId[];
    startTime: string;
    endTime: string;
    durationDays: number;
  },
): Promise<{ subscription: Subscription }> {
  return jsonRequest(
    "/api/subscriptions",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    receipt,
  );
}

export async function cancelSubscription(
  receipt: VerificationReceipt,
  subscriptionId: string,
): Promise<{ success: boolean }> {
  return jsonRequest(
    `/api/subscriptions/${encodeURIComponent(subscriptionId)}`,
    { method: "DELETE" },
    receipt,
  );
}
