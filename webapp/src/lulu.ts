export type LuluState =
  | "welcoming"
  | "idle"
  | "watching"
  | "happy"
  | "celebrating"
  | "concerned";

export type LuluSignals = {
  serviceOnline: boolean;
  healthyVenues: number;
  totalVenues: number;
  identityVerified: boolean;
  subscriptionCount: number;
  remindersToday: number;
  notificationBurst: boolean;
};

export const LULU_LABELS: Record<LuluState, string> = {
  welcoming: "噜噜在欢迎你",
  idle: "噜噜等待你创建订阅",
  watching: "噜噜正在帮你盯场",
  happy: "噜噜今天已送达提醒",
  celebrating: "噜噜发现了新的提醒",
  concerned: "噜噜发现巡检异常",
};

export function resolveLuluState(signals: LuluSignals): LuluState {
  const inspectionsDegraded =
    signals.totalVenues > 0 && signals.healthyVenues < signals.totalVenues;
  if (!signals.serviceOnline || inspectionsDegraded) return "concerned";
  if (signals.notificationBurst) return "celebrating";
  if (!signals.identityVerified) return "welcoming";
  if (!signals.subscriptionCount) return "idle";
  if (signals.remindersToday > 0) return "happy";
  return "watching";
}
