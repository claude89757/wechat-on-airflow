#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{relative}: expected one match, found {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_worker() -> None:
    path = "webapp/cloudflare/index.ts"
    replace_once(
        path,
        '} from "./domain";\nimport {\n  deliveryLimitForTier,',
        '} from "./domain";\nimport {\n  currentObservationSnapshotStatement,\n  enqueueCurrentSnapshotMatches,\n} from "./current-observation";\nimport {\n  deliveryLimitForTier,',
    )
    replace_once(path, "const INSPECTION_FRESHNESS_MS = 10 * 60_000;\n", "")
    replace_once(
        path,
        '    healthy:\n      Boolean(venue.healthy)\n      && Boolean(venue.last_inspection_at)\n      && Date.parse(venue.last_inspection_at || "") >= now.getTime() - INSPECTION_FRESHNESS_MS,',
        "    healthy: Boolean(venue.healthy),",
    )
    replace_once(
        path,
        "async function createSubscription(request: Request, env: WorkerEnv): Promise<Response> {",
        "async function createSubscription(\n  request: Request,\n  env: WorkerEnv,\n  context: ExecutionContext,\n): Promise<Response> {",
    )
    replace_once(
        path,
        """  ).run();
  return json({ subscription: { ...subscription, eligible: true } }, 201);
}

async function cancelSubscription(""",
        """  ).run();

  let matchedCurrentAvailability = 0;
  try {
    matchedCurrentAvailability = await enqueueCurrentSnapshotMatches(env.DB, {
      id: subscription.id,
      email: identity.email,
      venueIds: subscription.venueIds,
      weekdayMask,
      startTime: subscription.startTime,
      endTime: subscription.endTime,
    }, now);
    if (matchedCurrentAvailability > 0) {
      context.waitUntil(drainOutbox(env));
    }
  } catch (error) {
    console.warn(JSON.stringify({
      event: "current_snapshot_subscription_match_failed",
      subscriptionId: subscription.id,
      reason: error instanceof Error ? error.message.slice(0, 160) : "unknown",
    }));
  }

  return json({
    subscription: { ...subscription, eligible: true },
    matchedCurrentAvailability,
  }, 201);
}

async function cancelSubscription(""",
    )
    replace_once(
        path,
        "return await createSubscription(request, env);",
        "return await createSubscription(request, env, context);",
    )
    replace_once(
        path,
        """function parseObservationPayload(value: unknown): {
  venueId: VenueId;
  venueName: string;
  healthy: boolean;
  checkedAt: string;
  error: string | null;
  slots: SlotObservation[];
} {""",
        """function parseObservationPayload(value: unknown): {
  observationKey: string;
  observationScope: string;
  venueId: VenueId;
  venueName: string;
  healthy: boolean;
  checkedAt: string;
  error: string | null;
  slots: SlotObservation[];
} {""",
    )
    replace_once(
        path,
        """  const venueName = String(candidate.venue_name || candidate.venueName || VENUES[venueId]);
  if (venueName !== VENUES[venueId]) throw new Error("场地名称无效");
  const checkedAt = String(candidate.checked_at || candidate.checkedAt || "");""",
        """  const venueName = String(candidate.venue_name || candidate.venueName || VENUES[venueId]);
  if (venueName !== VENUES[venueId]) throw new Error("场地名称无效");
  const observationScope = String(
    candidate.observation_scope || candidate.observationScope || "default",
  ).trim();
  if (!observationScope || observationScope.length > 120) {
    throw new Error("巡检范围无效");
  }
  const checkedAt = String(candidate.checked_at || candidate.checkedAt || "");""",
    )
    replace_once(
        path,
        """  return {
    venueId,
    venueName,
    healthy: candidate.healthy === true,""",
        """  return {
    observationKey: `v3:${venueId}:${observationScope}`,
    observationScope,
    venueId,
    venueName,
    healthy: candidate.healthy === true,""",
    )
    replace_once(
        path,
        """  const now = new Date();
  const nowIso = now.toISOString();
  const statements: D1PreparedStatement[] = [
    env.DB.prepare(""",
        """  const now = new Date();
  const nowIso = now.toISOString();
  const statements: D1PreparedStatement[] = [
    currentObservationSnapshotStatement(env.DB, observation, nowIso),
    env.DB.prepare(""",
    )


def patch_ui() -> None:
    path = "webapp/src/Prototype.tsx"
    replace_once(
        path,
        """  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30_000);
    return () => window.clearInterval(timer);
  }, [refresh]);""",
        """  useEffect(() => {
    void refresh();
  }, [refresh]);""",
    )
    replace_once(path, 'if (force) setToast("已获取最新数据");', 'if (force) setToast("已读取最新记录");')
    replace_once(
        path,
        """  const statusLabel = availability === "loading" ? "正在读取状态数据"
    : availability === "unknown" ? "暂时无法读取状态"
    : availability === "stale" ? "刷新失败，显示上次数据" : "状态数据已更新";
  const statusDetail = hasSuccessfulDashboard
    ? `数据生成于 ${formatUpdatedAt(dashboard.generatedAt)}`
    : loading ? "正在获取最新数据" : "请稍后点击刷新";""",
        """  const statusLabel = availability === "loading" ? "正在读取最近状态"
    : availability === "unknown" ? "暂时无法读取状态"
    : availability === "stale" ? "刷新失败，显示上次记录" : "已显示最近状态";
  const statusDetail = hasSuccessfulDashboard
    ? `记录生成于 ${formatUpdatedAt(dashboard.generatedAt)}`
    : loading ? "正在读取最近记录" : "请点击刷新重试";""",
    )
    replace_once(path, 'aria-label="获取最新状态"\n              title="获取最新状态"', 'aria-label="手动刷新最新记录"\n              title="手动刷新最新记录"')
    replace_once(path, 'label="全站巡检正常"', 'label="最近记录正常"')
    replace_once(path, '<h2 id="venue-heading">场地运行状态</h2>', '<h2 id="venue-heading">场地最近状态</h2>')
    replace_once(
        path,
        '<p>点按卡片快速创建提醒 · 页面每 30 秒更新</p>',
        '<p>点按卡片快速创建提醒 · 点击刷新读取最新记录</p>',
    )
    replace_once(
        path,
        '<span><ArrowsClockwiseIcon size={17} />最长缓存 2 分钟</span>',
        '<span><ArrowsClockwiseIcon size={17} />仅在手动刷新时读取</span>',
    )
    replace_once(path, '<span><CheckCircleIcon size={15} weight="fill" />状态同步</span>', '<span><CheckCircleIcon size={15} weight="fill" />最近状态</span>')
    replace_once(path, '<span><ClockIcon size={15} weight="fill" />最近检查</span>', '<span><ClockIcon size={15} weight="fill" />状态时间</span>')
    replace_once(path, 'aria-label={`${venue.name}状态同步`}', 'aria-label={`${venue.name}状态记录`}')
    replace_once(path, 'healthyAt = "暂无检查记录";', 'healthyAt = "暂无状态记录";')


def patch_repository_contracts() -> None:
    replace_once(
        "config/active-components.yaml",
        """      - webapp_is_the_only_email_delivery_owner
      - no_secrets_or_email_addresses_are_logged""",
        """      - webapp_is_the_only_email_delivery_owner
      - no_secrets_or_email_addresses_are_logged
      - unchanged_observations_never_cross_worker_boundary
      - current_snapshots_match_new_subscriptions
      - dashboard_network_refresh_is_user_driven
      - dashboard_status_is_last_known_not_liveness""",
    )
    incident = ROOT / "docs/incidents/cloudflare-d1-read-limit-2026-09-02.md"
    text = incident.read_text(encoding="utf-8")
    marker = "# Cloudflare D1 Daily Read-Limit Incident — 2026-09-02\n"
    note = """

> Architecture update (2026-09-03): ADR 0015 supersedes the sparse-heartbeat
> portions of this incident response. Production now forwards only real
> observation changes, stores bounded current snapshots for new-subscription
> matching, and uses explicit user-driven dashboard refresh. Browser refresh is
> not an Airflow liveness signal.
"""
    if note.strip() not in text:
        if marker not in text:
            raise RuntimeError("incident title marker missing")
        incident.write_text(text.replace(marker, marker + note, 1), encoding="utf-8")


if __name__ == "__main__":
    patch_worker()
    patch_ui()
    patch_repository_contracts()
