export type ActivityBucket = "今天活跃" | "7天内活跃" | "30天内活跃" | "较早活跃";
export type VolumeBucket = "暂无送达" | "1–5封" | "6–20封" | "20封以上";

export function maskCommunityEmail(email: string): string {
  const [localRaw, domainRaw] = email.toLowerCase().split("@");
  if (!localRaw || !domainRaw) return "***@***";
  const localVisible = localRaw.slice(0, Math.min(2, localRaw.length));
  const localMasked = `${localVisible}${"*".repeat(Math.max(3, localRaw.length - localVisible.length))}`;
  const parts = domainRaw.split(".");
  const host = parts.shift() || "";
  const suffix = parts.length ? `.${parts.join(".")}` : "";
  const hostVisible = host.slice(0, Math.min(1, host.length));
  const hostMasked = `${hostVisible}${"*".repeat(Math.max(3, host.length - hostVisible.length))}`;
  return `${localMasked}@${hostMasked}${suffix}`;
}

export function activityBucket(
  timestamp: number | null | undefined,
  now = Date.now(),
): ActivityBucket {
  if (!timestamp) return "较早活跃";
  const age = Math.max(0, now - timestamp);
  if (age < 86_400_000) return "今天活跃";
  if (age < 7 * 86_400_000) return "7天内活跃";
  if (age < 30 * 86_400_000) return "30天内活跃";
  return "较早活跃";
}

export function volumeBucket(count: number): VolumeBucket {
  if (count <= 0) return "暂无送达";
  if (count <= 5) return "1–5封";
  if (count <= 20) return "6–20封";
  return "20封以上";
}
