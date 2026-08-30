export const VENUE_IDS = [
  "szw",
  "gba",
  "dsh_free",
  "dsh",
  "sysh",
  "tops",
  "fsb",
  "fsb_shenyun",
  "fsb_shekou",
  "fsb_xinan",
  "fsb_zhengzhong",
  "fsb_atuoshan",
  "fft_qianhai",
  "ppba",
  "tyzx",
  "jdwx",
] as const;

export type VenueId = (typeof VENUE_IDS)[number];
export const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7] as const;
export type Weekday = (typeof WEEKDAYS)[number];
export type DeliveryTier = "standard" | "priority";
export type SubscriptionTerm =
  | "7d" | "8d" | "9d" | "10d" | "11d" | "12d" | "13d" | "14d"
  | "30d" | "90d" | "180d" | "long_term";

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
  weekdays: Weekday[];
  startTime: string;
  endTime: string;
  durationDays: number;
  termCode: SubscriptionTerm;
  autoRenew: boolean;
  eligible: boolean;
  activeUntil: string;
  active: boolean;
  createdAt: string;
};

export type CommunityUser = {
  email: string;
  tier: DeliveryTier;
  activity: string;
  activeSubscriptions: number;
  deliveredVolume: string;
};

export type AdminUser = {
  email: string;
  maskedEmail: string;
  tier: DeliveryTier;
  isAdmin: boolean;
  firstVerifiedAt: string | null;
  lastVerifiedAt: string | null;
  lastLoginAt: string | null;
  lastActiveAt: string | null;
  activeSubscriptions: number;
  submittedToday: number;
  deliveredToday: number;
  failedToday: number;
  deliveredAllTime: number;
};

export type AdminInvite = {
  id: string;
  code: string | null;
  codeHint: string | null;
  recoverable: boolean;
  active: boolean;
  status: "available" | "redeemed" | "expired" | "disabled" | "deleted";
  note: string | null;
  createdAt: string;
  expiresAt: string;
  redeemedBy: string | null;
  redeemedAt: string | null;
};

export type Dashboard = {
  generatedAt: string;
  weatherEmailGate?: {
    suppressed: boolean;
    precipitationMm: number | null;
    thresholdMm: number;
  };
  metrics: {
    activeSubscriptions: number;
    remindersToday: number;
    healthyVenues: number;
    totalVenues: number;
  };
  deliveryTiers: { standard: number; priority: number };
  subscriptionTerms: { standard: SubscriptionTerm[]; priority: SubscriptionTerm[] };
  subscriptionLimits: { standard: number; priority: number };
  venues: VenueStatus[];
  identity: {
    verified: boolean;
    maskedEmail: string | null;
    remindersToday: number;
    submittedToday: number;
    deliveredToday: number;
    failedToday: number;
    tier: DeliveryTier;
    isAdmin: boolean;
    dailyLimit: number;
    remainingToday: number;
    activeSubscriptionLimit: number;
    activeSubscriptionCount: number;
    remainingSubscriptions: number;
  };
  subscriptions: Subscription[];
};

export type VerificationReceipt = {
  token: string;
  email: string;
  maskedEmail: string;
  verifiedAt: string;
};

export type CoffeeInviteSession = {
  claimToken: string;
  availableAt: string;
  expiresAt: string;
  alreadyClaimed: boolean;
};

export type CoffeeInvite = {
  code: string;
  expiresAt: string;
  claimedAt: string;
  reused: boolean;
  status: "available" | "redeemed" | "expired" | "disabled" | "deleted";
};

const RECEIPTS_KEY = "zacks-tennis-verified-emails-v1";
export const DASHBOARD_CLIENT_CACHE_MS = 120_000;

type DashboardClientCache = {
  identityKey: string;
  expiresAt: number;
  value: Dashboard;
};

type DashboardClientRequest = {
  identityKey: string;
  epoch: number;
  promise: Promise<Dashboard>;
};

let dashboardCache: DashboardClientCache | null = null;
let dashboardRequest: DashboardClientRequest | null = null;
let dashboardCacheEpoch = 0;

const FALLBACK_VENUES: VenueStatus[] = [
  { id: "szw", name: "深圳湾", healthy: true, subscriberCount: 28, lastInspectionAt: "2026-07-29T10:41:40+08:00", lastNotificationAt: null },
  { id: "gba", name: "大湾区网球场", healthy: true, subscriberCount: 0, lastInspectionAt: "2026-07-29T10:41:34+08:00", lastNotificationAt: null },
  { id: "dsh_free", name: "大沙河免费场", healthy: true, subscriberCount: 0, lastInspectionAt: "2026-07-29T10:41:31+08:00", lastNotificationAt: null },
  { id: "dsh", name: "大沙河国际网球中心", healthy: true, subscriberCount: 0, lastInspectionAt: "2026-07-29T10:41:31+08:00", lastNotificationAt: null },
  { id: "sysh", name: "上越沙河", healthy: true, subscriberCount: 24, lastInspectionAt: "2026-07-29T10:41:28+08:00", lastNotificationAt: null },
  { id: "tops", name: "TOPS 科技园", healthy: true, subscriberCount: 22, lastInspectionAt: "2026-07-29T10:41:12+08:00", lastNotificationAt: null },
  { id: "fsb", name: "泛思博特福中福", healthy: true, subscriberCount: 0, lastInspectionAt: "2026-07-29T10:41:08+08:00", lastNotificationAt: null },
  { id: "fsb_shenyun", name: "泛思博特深云", healthy: true, subscriberCount: 0, lastInspectionAt: "2026-07-29T10:41:08+08:00", lastNotificationAt: null },
  { id: "fsb_shekou", name: "泛思博特蛇口", healthy: true, subscriberCount: 0, lastInspectionAt: "2026-07-29T10:41:08+08:00", lastNotificationAt: null },
  { id: "fsb_xinan", name: "泛思博特新安", healthy: true, subscriberCount: 0, lastInspectionAt: "2026-07-29T10:41:08+08:00", lastNotificationAt: null },
  { id: "fsb_zhengzhong", name: "泛思博特正中", healthy: true, subscriberCount: 0, lastInspectionAt: "2026-07-29T10:41:08+08:00", lastNotificationAt: null },
  { id: "fsb_atuoshan", name: "泛思博特安托山", healthy: true, subscriberCount: 0, lastInspectionAt: "2026-07-29T10:41:08+08:00", lastNotificationAt: null },
  { id: "fft_qianhai", name: "FFTENNIS前海国际网球中心", healthy: true, subscriberCount: 0, lastInspectionAt: "2026-08-30T10:30:08+08:00", lastNotificationAt: null },
  { id: "ppba", name: "PICKLE POP宝安", healthy: true, subscriberCount: 0, lastInspectionAt: "2026-07-29T10:41:08+08:00", lastNotificationAt: null },
  { id: "tyzx", name: "深圳市体育中心", healthy: true, subscriberCount: 30, lastInspectionAt: "2026-07-29T10:40:55+08:00", lastNotificationAt: null },
  { id: "jdwx", name: "金地威新", healthy: true, subscriberCount: 24, lastInspectionAt: "2026-07-29T10:40:42+08:00", lastNotificationAt: null },
];

const DEFAULT_TERMS: Dashboard["subscriptionTerms"] = {
  standard: ["7d", "8d", "9d", "10d", "11d", "12d", "13d", "14d"],
  priority: ["7d", "8d", "9d", "10d", "11d", "12d", "13d", "14d", "30d", "90d", "180d", "long_term"],
};

export const FALLBACK_DASHBOARD: Dashboard = {
  generatedAt: "2026-07-29T10:42:00+08:00",
  weatherEmailGate: { suppressed: false, precipitationMm: null, thresholdMm: 25 },
  metrics: { activeSubscriptions: 128, remindersToday: 6, healthyVenues: 16, totalVenues: 16 },
  deliveryTiers: { standard: 10, priority: 100 },
  subscriptionTerms: DEFAULT_TERMS,
  subscriptionLimits: { standard: 5, priority: 20 },
  venues: FALLBACK_VENUES,
  identity: {
    verified: false,
    maskedEmail: null,
    remindersToday: 0,
    submittedToday: 0,
    deliveredToday: 0,
    failedToday: 0,
    tier: "standard",
    isAdmin: false,
    dailyLimit: 10,
    remainingToday: 10,
    activeSubscriptionLimit: 5,
    activeSubscriptionCount: 0,
    remainingSubscriptions: 5,
  },
  subscriptions: [],
};

export const EMPTY_DASHBOARD: Dashboard = {
  ...FALLBACK_DASHBOARD,
  generatedAt: new Date().toISOString(),
  metrics: { activeSubscriptions: 0, remindersToday: 0, healthyVenues: 0, totalVenues: 16 },
  venues: FALLBACK_VENUES.map((venue) => ({
    ...venue,
    healthy: false,
    subscriberCount: 0,
    lastInspectionAt: null,
    lastNotificationAt: null,
  })),
};

function requestHeaders(receipt?: VerificationReceipt | null): HeadersInit {
  return receipt
    ? { Authorization: `Bearer ${receipt.token}`, "Content-Type": "application/json" }
    : { "Content-Type": "application/json" };
}

async function jsonRequest<T>(
  path: string,
  init: RequestInit = {},
  receipt?: VerificationReceipt | null,
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { ...requestHeaders(receipt), ...(init.headers ?? {}) },
  });
  const payload = (await response.json().catch(() => null)) as (T & { error?: string }) | null;
  if (!response.ok || !payload) {
    throw new Error(payload?.error || `请求失败 (${response.status})`);
  }
  return payload;
}

function dashboardIdentityKey(receipt?: VerificationReceipt | null): string {
  return receipt?.token || "anonymous";
}

function pageIsHidden(): boolean {
  return typeof document !== "undefined" && document.visibilityState === "hidden";
}

export function invalidateDashboardCache(): void {
  dashboardCacheEpoch += 1;
  dashboardCache = null;
  dashboardRequest = null;
}

export function loadReceipts(): VerificationReceipt[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(RECEIPTS_KEY) || "[]") as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is VerificationReceipt => Boolean(
      item && typeof item === "object"
      && typeof (item as VerificationReceipt).token === "string"
      && typeof (item as VerificationReceipt).email === "string"
      && typeof (item as VerificationReceipt).maskedEmail === "string"
      && typeof (item as VerificationReceipt).verifiedAt === "string",
    )).slice(0, 3);
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
  invalidateDashboardCache();
  return next;
}

export function removeReceipt(token: string): VerificationReceipt[] {
  const next = loadReceipts().filter((item) => item.token !== token);
  localStorage.setItem(RECEIPTS_KEY, JSON.stringify(next));
  invalidateDashboardCache();
  return next;
}

export async function getDashboard(receipt?: VerificationReceipt | null): Promise<Dashboard> {
  const identityKey = dashboardIdentityKey(receipt);
  const now = Date.now();
  if (
    dashboardCache
    && dashboardCache.identityKey === identityKey
    && (dashboardCache.expiresAt > now || pageIsHidden())
  ) {
    return dashboardCache.value;
  }
  if (
    dashboardRequest
    && dashboardRequest.identityKey === identityKey
    && dashboardRequest.epoch === dashboardCacheEpoch
  ) {
    return dashboardRequest.promise;
  }

  const epoch = dashboardCacheEpoch;
  const promise = jsonRequest<Dashboard>("/api/bootstrap", { method: "GET" }, receipt)
    .then((value) => {
      if (dashboardCacheEpoch === epoch) {
        dashboardCache = {
          identityKey,
          expiresAt: Date.now() + DASHBOARD_CLIENT_CACHE_MS,
          value,
        };
      }
      return value;
    })
    .finally(() => {
      if (dashboardRequest?.promise === promise) dashboardRequest = null;
    });
  dashboardRequest = { identityKey, epoch, promise };
  return promise;
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

export async function verifyEmail(challengeId: string, code: string): Promise<VerificationReceipt> {
  const receipt = await jsonRequest<VerificationReceipt>("/api/email/verify", {
    method: "POST",
    body: JSON.stringify({ challengeId, code }),
  });
  invalidateDashboardCache();
  return receipt;
}

export async function createSubscription(
  receipt: VerificationReceipt,
  payload: {
    venueIds: VenueId[];
    weekdays: Weekday[];
    startTime: string;
    endTime: string;
    termCode: SubscriptionTerm;
  },
): Promise<{ subscription: Subscription }> {
  const result = await jsonRequest<{ subscription: Subscription }>("/api/subscriptions", {
    method: "POST",
    body: JSON.stringify(payload),
  }, receipt);
  invalidateDashboardCache();
  return result;
}

export async function cancelSubscription(
  receipt: VerificationReceipt,
  subscriptionId: string,
): Promise<{ success: boolean }> {
  const result = await jsonRequest<{ success: boolean }>(
    `/api/subscriptions/${encodeURIComponent(subscriptionId)}`,
    { method: "DELETE" },
    receipt,
  );
  invalidateDashboardCache();
  return result;
}

export async function startCoffeeInviteSession(
  receipt: VerificationReceipt,
): Promise<CoffeeInviteSession> {
  return jsonRequest("/api/coffee/session", { method: "POST" }, receipt);
}

export async function claimCoffeeInvite(
  receipt: VerificationReceipt,
  claimToken: string,
): Promise<CoffeeInvite> {
  return jsonRequest("/api/coffee/invite", {
    method: "POST",
    body: JSON.stringify({ claimToken }),
  }, receipt);
}

export async function redeemPriorityInvite(
  receipt: VerificationReceipt,
  code: string,
): Promise<{
  success: boolean;
  alreadyPriority?: boolean;
  tier: DeliveryTier;
  dailyLimit: number;
  remindersToday: number;
  remainingToday: number;
}> {
  const result = await jsonRequest<{
    success: boolean;
    alreadyPriority?: boolean;
    tier: DeliveryTier;
    dailyLimit: number;
    remindersToday: number;
    remainingToday: number;
  }>("/api/priority/redeem", {
    method: "POST",
    body: JSON.stringify({ code }),
  }, receipt);
  invalidateDashboardCache();
  return result;
}

export async function getCommunityUsers(
  receipt: VerificationReceipt,
): Promise<{ users: CommunityUser[]; generatedAt: string }> {
  return jsonRequest("/api/community/users", { method: "GET" }, receipt);
}

export async function getAdminUsers(
  receipt: VerificationReceipt,
): Promise<{ users: AdminUser[]; generatedAt: string }> {
  return jsonRequest("/api/admin/users", { method: "GET" }, receipt);
}

export async function getAdminInvites(
  receipt: VerificationReceipt,
): Promise<{ invites: AdminInvite[]; generatedAt: string }> {
  return jsonRequest("/api/admin/invites", { method: "GET" }, receipt);
}

export async function createAdminInvites(
  receipt: VerificationReceipt,
  payload: { count: number; expiresInDays: number; note?: string },
): Promise<{ invites: AdminInvite[] }> {
  return jsonRequest("/api/admin/invites", {
    method: "POST",
    body: JSON.stringify(payload),
  }, receipt);
}

export async function updateAdminInvite(
  receipt: VerificationReceipt,
  inviteId: string,
  payload: { active?: boolean; note?: string; expiresInDays?: number },
): Promise<{ success: boolean }> {
  return jsonRequest(`/api/admin/invites/${encodeURIComponent(inviteId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  }, receipt);
}

export async function deleteAdminInvite(
  receipt: VerificationReceipt,
  inviteId: string,
): Promise<{ success: boolean }> {
  return jsonRequest(`/api/admin/invites/${encodeURIComponent(inviteId)}`, {
    method: "DELETE",
  }, receipt);
}
