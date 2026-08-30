import { readFileSync, writeFileSync } from "node:fs";

function read(path) {
  return readFileSync(path, "utf8");
}

function write(path, content) {
  writeFileSync(path, content, "utf8");
}

function replaceOnce(content, before, after, label) {
  const first = content.indexOf(before);
  if (first < 0) throw new Error(`Missing replacement target: ${label}`);
  if (content.indexOf(before, first + before.length) >= 0) {
    throw new Error(`Replacement target is not unique: ${label}`);
  }
  return content.slice(0, first) + after + content.slice(first + before.length);
}

function appendOnce(content, marker, addition) {
  return content.includes(marker) ? content : `${content.trimEnd()}\n\n${addition.trim()}\n`;
}

// 1) Make automatic refresh reuse the two-minute client cache, while explicit
// manual refreshes bypass both client and edge bootstrap caches.
{
  const path = "webapp/src/api.ts";
  let source = read(path);
  source = replaceOnce(
    source,
    'export const DASHBOARD_CLIENT_CACHE_MS = 120_000;\n',
    'export const DASHBOARD_CLIENT_CACHE_MS = 120_000;\n\nexport type DashboardFetchOptions = {\n  force?: boolean;\n};\n',
    "dashboard fetch options",
  );
  source = replaceOnce(
    source,
    '  metrics: { activeSubscriptions: 128, remindersToday: 6, healthyVenues: 15, totalVenues: 15 },',
    '  metrics: {\n    activeSubscriptions: 128,\n    remindersToday: 6,\n    healthyVenues: FALLBACK_VENUES.length,\n    totalVenues: FALLBACK_VENUES.length,\n  },',
    "fallback venue metric totals",
  );
  source = replaceOnce(
    source,
    '  metrics: { activeSubscriptions: 0, remindersToday: 0, healthyVenues: 0, totalVenues: 15 },',
    '  metrics: {\n    activeSubscriptions: 0,\n    remindersToday: 0,\n    healthyVenues: 0,\n    totalVenues: FALLBACK_VENUES.length,\n  },',
    "empty venue metric totals",
  );

  const oldDashboard = `export async function getDashboard(receipt?: VerificationReceipt | null): Promise<Dashboard> {
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
}`;
  const newDashboard = `export async function getDashboard(
  receipt?: VerificationReceipt | null,
  options: DashboardFetchOptions = {},
): Promise<Dashboard> {
  if (options.force) invalidateDashboardCache();

  const identityKey = dashboardIdentityKey(receipt);
  const now = Date.now();
  if (
    !options.force
    && dashboardCache
    && dashboardCache.identityKey === identityKey
    && (dashboardCache.expiresAt > now || pageIsHidden())
  ) {
    return dashboardCache.value;
  }
  if (
    !options.force
    && dashboardRequest
    && dashboardRequest.identityKey === identityKey
    && dashboardRequest.epoch === dashboardCacheEpoch
  ) {
    return dashboardRequest.promise;
  }

  const epoch = dashboardCacheEpoch;
  const requestPath = options.force ? "/api/bootstrap?refresh=1" : "/api/bootstrap";
  const requestInit: RequestInit = options.force
    ? { method: "GET", cache: "no-store" }
    : { method: "GET" };
  const promise = jsonRequest<Dashboard>(requestPath, requestInit, receipt)
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
}`;
  source = replaceOnce(source, oldDashboard, newDashboard, "dashboard cache implementation");
  write(path, source);
}

// 2) Let the Worker bypass its two-minute edge cache only for an explicit
// user-triggered refresh, then repopulate the canonical cache with the result.
{
  const path = "webapp/cloudflare/deployment-entry.ts";
  let source = read(path);
  const invalidationBlock = `export function invalidatesBootstrap(method: string, pathname: string): boolean {
  return (
    (method === "POST" && pathname === "/api/subscriptions")
    || (method === "POST" && pathname === "/api/priority/redeem")
    || (method === "DELETE" && /^\\/api\\/subscriptions\\/[0-9a-f-]{36}$/i.test(pathname))
  );
}`;
  source = replaceOnce(
    source,
    invalidationBlock,
    `${invalidationBlock}\n\nexport function bypassesBootstrapCache(request: Request): boolean {\n  const url = new URL(request.url);\n  return request.method === "GET"\n    && url.pathname === "/api/bootstrap"\n    && url.searchParams.get("refresh") === "1";\n}`,
    "manual bootstrap bypass helper",
  );
  source = replaceOnce(
    source,
    `    if (request.method === "GET" && url.pathname === "/api/bootstrap") {
      const cached = await cachedBootstrap(request, env);
      if (cached) return cached;
    }`,
    `    if (
      request.method === "GET"
      && url.pathname === "/api/bootstrap"
      && !bypassesBootstrapCache(request)
    ) {
      const cached = await cachedBootstrap(request, env);
      if (cached) return cached;
    }`,
    "bootstrap cache lookup",
  );
  write(path, source);
}

// 3) Update the product UI: personal metrics first for verified users, explicit
// global labels, a real manual refresh, support copy, and destructive-action confirmation.
{
  const path = "webapp/src/Prototype.tsx";
  let source = read(path);
  source = replaceOnce(
    source,
    `  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await getDashboard(receipt);
      setDashboard(next);
      setServiceOnline(true);
      setHasSuccessfulDashboard(true);
      setRefreshFailed(false);
      if (receipt && !next.identity.verified) {
        setReceipts(removeReceipt(receipt.token));
        setReceipt(null);
      }
    } catch {
      setServiceOnline(import.meta.env.DEV);
      setRefreshFailed(true);
    } finally {
      setLoading(false);
    }
  }, [receipt]);`,
    `  const refresh = useCallback(async (force = false) => {
    setLoading(true);
    try {
      const next = await getDashboard(receipt, { force });
      setDashboard(next);
      setServiceOnline(true);
      setHasSuccessfulDashboard(true);
      setRefreshFailed(false);
      if (receipt && !next.identity.verified) {
        setReceipts(removeReceipt(receipt.token));
        setReceipt(null);
      }
      if (force) setToast("已获取最新数据");
    } catch {
      setServiceOnline(import.meta.env.DEV);
      setRefreshFailed(true);
    } finally {
      setLoading(false);
    }
  }, [receipt]);`,
    "React refresh callback",
  );
  source = replaceOnce(
    source,
    `  const cancelExistingSubscription = async (subscriptionId: string) => {
    if (!receipt) return;
    setFormBusy(true);`,
    `  const cancelExistingSubscription = async (subscriptionId: string) => {
    if (!receipt) return;
    const confirmed = window.confirm(
      "确认取消这个订阅吗？取消后将不再收到该条件的场地提醒。",
    );
    if (!confirmed) return;
    setFormBusy(true);`,
    "subscription cancellation confirmation",
  );
  source = replaceOnce(
    source,
    '    if (panel === "coffee") return "请作者喝咖啡";',
    '    if (panel === "coffee") return "支持 Zacks";',
    "coffee panel title",
  );
  source = replaceOnce(
    source,
    '                aria-label="请作者喝咖啡，支持项目维护"\n                title="请作者喝咖啡"',
    '                aria-label="支持 Zacks，请作者喝咖啡"\n                title="支持 Zacks"',
    "support action accessible copy",
  );
  source = replaceOnce(
    source,
    '                <span>支持作者</span>',
    '                <span>支持 Zacks</span>',
    "support action visible copy",
  );
  source = replaceOnce(
    source,
    `  const statusLabel = availability === "loading" ? "正在读取服务状态"
    : availability === "unknown" ? "暂时无法读取状态"
    : availability === "stale" ? "刷新失败，显示上次数据" : "服务运行正常";
  const statusDetail = hasSuccessfulDashboard
    ? \`更新于 \${formatUpdatedAt(dashboard.generatedAt)}\`
    : loading ? "正在获取最新数据" : "请稍后点击刷新";`,
    `  const statusLabel = availability === "loading" ? "正在读取状态数据"
    : availability === "unknown" ? "暂时无法读取状态"
    : availability === "stale" ? "刷新失败，显示上次数据" : "状态数据已更新";
  const statusDetail = hasSuccessfulDashboard
    ? \`数据生成于 \${formatUpdatedAt(dashboard.generatedAt)}\`
    : loading ? "正在获取最新数据" : "请稍后点击刷新";`,
    "status semantics",
  );
  source = replaceOnce(
    source,
    `              aria-label="刷新状态"
              title="刷新状态"
              onClick={() => void refresh()}`,
    `              aria-label="获取最新状态"
              title="获取最新状态"
              onClick={() => void refresh(true)}`,
    "manual refresh button",
  );

  const oldMetrics = `          <section className="metric-band" aria-label="运行概况">
            <Metric
              icon={<UsersThreeIcon size={25} weight="fill" />}
              value={hasSuccessfulDashboard ? dashboard.metrics.activeSubscriptions : "—"}
              label="个有效订阅"
              tone="teal"
            />
            <Metric
              icon={<EnvelopeSimpleIcon size={25} weight="fill" />}
              value={hasSuccessfulDashboard ? dashboard.metrics.remindersToday : "—"}
              label="今日提醒"
              tone="blue"
            />
            <Metric
              icon={<ShieldCheckIcon size={27} weight="fill" />}
              value={hasSuccessfulDashboard
                ? \`\${dashboard.metrics.healthyVenues}/\${dashboard.metrics.totalVenues}\`
                : \`—/\${dashboard.metrics.totalVenues}\`}
              label="场地巡检正常"
              tone="green"
            />
          </section>`;
  const newMetrics = `          <section
            className="metric-band"
            aria-label={activeIdentity ? "我的提醒与全站运行概况" : "全站运行概况"}
          >
            <Metric
              icon={<UsersThreeIcon size={25} weight="fill" />}
              value={hasSuccessfulDashboard
                ? activeIdentity
                  ? dashboard.identity.activeSubscriptionCount
                  : dashboard.metrics.activeSubscriptions
                : "—"}
              label={activeIdentity ? "我的有效订阅" : "全站有效订阅"}
              tone="teal"
            />
            <Metric
              icon={<EnvelopeSimpleIcon size={25} weight="fill" />}
              value={hasSuccessfulDashboard
                ? activeIdentity
                  ? dashboard.identity.deliveredToday
                  : dashboard.metrics.remindersToday
                : "—"}
              label={activeIdentity ? "我的今日送达" : "全站今日提醒"}
              tone="blue"
            />
            <Metric
              icon={<ShieldCheckIcon size={27} weight="fill" />}
              value={hasSuccessfulDashboard
                ? \`\${dashboard.metrics.healthyVenues}/\${dashboard.metrics.totalVenues}\`
                : \`—/\${dashboard.metrics.totalVenues}\`}
              label="全站巡检正常"
              tone="green"
            />
          </section>`;
  source = replaceOnce(source, oldMetrics, newMetrics, "personal and global metrics");
  source = replaceOnce(
    source,
    `                <p>热门优先 · 时间为最近一次状态同步</p>
              </div>
              <span><ArrowsClockwiseIcon size={17} />30 秒刷新显示</span>`,
    `                <p>热门优先 · 每 30 秒刷新显示 · 数据最长缓存 2 分钟</p>
              </div>
              <span><ArrowsClockwiseIcon size={17} />可手动刷新</span>`,
    "refresh cadence copy",
  );
  source = replaceOnce(
    source,
    '                  title="取消订阅"',
    '                  title="取消订阅（需要确认）"',
    "cancel button title",
  );
  write(path, source);
}

// 4) Restore visible keyboard focus instead of globally suppressing it.
{
  const path = "webapp/src/styles.css";
  let source = read(path);
  source = replaceOnce(
    source,
    `.device-screen *:focus,
.device-screen *:focus-visible {
  outline: 0 !important;
  box-shadow: none !important;
}`,
    `.device-screen *:focus:not(:focus-visible) {
  outline: 0;
  box-shadow: none;
}`,
    "global focus suppression",
  );
  source = source.replace(
    `.device-screen .mobile-field input:focus,
.device-screen .mobile-field input:focus-visible {
  border-color: rgba(0, 0, 0, 0.12);
  outline: 0 !important;
  box-shadow: none !important;
}`,
    `.device-screen .mobile-field input:focus:not(:focus-visible) {
  border-color: rgba(0, 0, 0, 0.12);
  outline: 0;
  box-shadow: none;
}`,
  );
  write(path, source);
}

{
  const path = "webapp/src/prototype.css";
  let source = read(path);
  source = appendOnce(
    source,
    "Keyboard focus restoration for the production Web UI",
    `/* Keyboard focus restoration for the production Web UI. */
.device-screen .dashboard-screen button:focus-visible,
.device-screen .dashboard-screen a:focus-visible,
.device-screen .dashboard-screen input:focus-visible,
.device-screen .dashboard-screen select:focus-visible,
.device-screen .dashboard-screen textarea:focus-visible,
.device-screen .bottom-sheet button:focus-visible,
.device-screen .bottom-sheet a:focus-visible,
.device-screen .bottom-sheet input:focus-visible,
.device-screen .bottom-sheet select:focus-visible,
.device-screen .bottom-sheet textarea:focus-visible,
.device-screen .bottom-sheet [tabindex]:focus-visible {
  outline: 3px solid rgba(6, 155, 152, 0.55) !important;
  outline-offset: 3px;
  box-shadow: 0 0 0 4px rgba(6, 155, 152, 0.16) !important;
}

.device-screen .dashboard-screen input:focus-visible,
.device-screen .dashboard-screen select:focus-visible,
.device-screen .dashboard-screen textarea:focus-visible,
.device-screen .bottom-sheet input:focus-visible,
.device-screen .bottom-sheet select:focus-visible,
.device-screen .bottom-sheet textarea:focus-visible {
  border-color: var(--teal) !important;
}`,
  );
  write(path, source);
}

// 5) Eliminate nine-pixel key status copy on narrow screens.
{
  const path = "webapp/public/mobile-v2.css";
  let source = read(path);
  source = source.replace(
    /(html body \.venue-health span\s*\{[\s\S]*?font-size:\s*)9px;/g,
    (_match, prefix) => `${prefix}11px;`,
  );
  source = source.replace(
    /(html body \.venue-mail span\s*\{[\s\S]*?font-size:\s*)9px;/g,
    (_match, prefix) => `${prefix}11px;`,
  );
  source = source.replace(/font-size:\s*9px;/g, "font-size: 10px;");
  if (/font-size:\s*9px;/.test(source)) {
    throw new Error("Nine-pixel mobile text remains");
  }
  write(path, source);
}

// 6) Unit and interaction coverage for force refresh, venue totals, personal
// metrics, cancellation confirmation, focus visibility, and the removed footer link.
{
  const path = "webapp/src/api.test.ts";
  let source = read(path);
  source = replaceOnce(
    source,
    `  DASHBOARD_CLIENT_CACHE_MS,
  FALLBACK_DASHBOARD,`,
    `  DASHBOARD_CLIENT_CACHE_MS,
  EMPTY_DASHBOARD,
  FALLBACK_DASHBOARD,`,
    "api test imports",
  );
  source = replaceOnce(
    source,
    `  it("coalesces concurrent refreshes for the same identity", async () => {`,
    `  it("bypasses client and edge caches for an explicit manual refresh", async () => {
    const fetchMock = dashboardFetchMock();
    vi.stubGlobal("fetch", fetchMock);

    await getDashboard(null);
    await getDashboard(null, { force: true });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/bootstrap?refresh=1");
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      method: "GET",
      cache: "no-store",
    });
  });

  it("keeps fallback and empty venue totals aligned with the venue catalog", () => {
    expect(FALLBACK_DASHBOARD.metrics.totalVenues).toBe(FALLBACK_DASHBOARD.venues.length);
    expect(FALLBACK_DASHBOARD.metrics.healthyVenues).toBe(FALLBACK_DASHBOARD.venues.length);
    expect(EMPTY_DASHBOARD.metrics.totalVenues).toBe(EMPTY_DASHBOARD.venues.length);
  });

  it("coalesces concurrent refreshes for the same identity", async () => {`,
    "api cache tests",
  );
  write(path, source);
}

{
  const path = "webapp/cloudflare/deployment-entry.test.ts";
  let source = read(path);
  source = replaceOnce(
    source,
    `  applyGlobalSubmittedReminderMetric,
  deploymentHealth,`,
    `  applyGlobalSubmittedReminderMetric,
  bypassesBootstrapCache,
  deploymentHealth,`,
    "deployment test imports",
  );
  source = replaceOnce(
    source,
    `  it("invalidates dashboard cache only for state-changing subscription actions", () => {`,
    `  it("bypasses the edge cache only for an explicit manual bootstrap refresh", () => {
    expect(bypassesBootstrapCache(
      new Request("https://example.com/api/bootstrap?refresh=1"),
    )).toBe(true);
    expect(bypassesBootstrapCache(
      new Request("https://example.com/api/bootstrap"),
    )).toBe(false);
    expect(bypassesBootstrapCache(
      new Request("https://example.com/api/bootstrap?refresh=1", { method: "POST" }),
    )).toBe(false);
  });

  it("invalidates dashboard cache only for state-changing subscription actions", () => {`,
    "edge cache bypass test",
  );
  write(path, source);
}

{
  const path = "webapp/tests/mobile-v2.spec.ts";
  let source = read(path);
  source = replaceOnce(
    source,
    `        ".venue-section",
        ".subscriptions-link",`,
    `        ".venue-section",`,
    "removed subscriptions link selector",
  );
  source = source.replaceAll(
    'name: "请作者喝咖啡", exact: true',
    'name: "支持 Zacks，请作者喝咖啡", exact: true',
  );
  source = replaceOnce(
    source,
    `    await expect(coffeeButton).toBeVisible();
    const coffeeButtonBox`,
    `    await expect(coffeeButton).toBeVisible();
    await expect(coffeeButton).toContainText("支持 Zacks");
    const coffeeButtonBox`,
    "support button visible copy test",
  );
  const finalDescribe = "\n});\n";
  const insertionPoint = source.lastIndexOf(finalDescribe);
  if (insertionPoint < 0) throw new Error("Missing mobile test describe closing");
  const focusTest = `

  test("shows visible keyboard focus and keeps key status text readable", async ({ page }) => {
    await page.goto("/");

    const primaryButton = page.locator(".primary-button");
    await primaryButton.focus();
    const focusIsVisible = await primaryButton.evaluate((element) => {
      const style = getComputedStyle(element);
      return (style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0)
        || style.boxShadow !== "none";
    });
    expect(focusIsVisible).toBe(true);

    const keyTextSizes = await page.locator(
      ".metric span, .venue-health span, .venue-mail span",
    ).evaluateAll((elements) => elements.map((element) =>
      parseFloat(getComputedStyle(element).fontSize),
    ));
    expect(Math.min(...keyTextSizes)).toBeGreaterThanOrEqual(10);
  });`;
  source = source.slice(0, insertionPoint) + focusTest + source.slice(insertionPoint);
  write(path, source);
}

{
  const path = "webapp/tests/subscription-ux.spec.ts";
  let source = read(path).trimEnd();
  const extraTests = `

test("prioritizes personal metrics while marking the global health metric", async ({ page }) => {
  await page.goto("/");

  const metrics = page.locator(".metric");
  await expect(metrics.nth(0)).toContainText("我的有效订阅");
  await expect(metrics.nth(1)).toContainText("我的今日送达");
  await expect(metrics.nth(2)).toContainText("全站巡检正常");
  await expect(page.locator(".coffee-button")).toContainText("支持 Zacks");
});

test("manual refresh bypasses the normal bootstrap cache", async ({ page }) => {
  let forcedRefreshes = 0;
  await page.route("**/api/bootstrap?refresh=1", async (route) => {
    forcedRefreshes += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(dashboard),
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "获取最新状态", exact: true }).click();

  await expect.poll(() => forcedRefreshes).toBe(1);
  await expect(page.locator(".app-toast")).toContainText("已获取最新数据");
});

test("requires confirmation before cancelling a subscription", async ({ page }) => {
  const subscriptionId = "9d1aca70-e4de-4c91-b3eb-1f4b26ce9181";
  const dashboardWithSubscription = {
    ...dashboard,
    identity: {
      ...dashboard.identity,
      activeSubscriptionCount: 1,
      remainingSubscriptions: 4,
    },
    subscriptions: [{
      id: subscriptionId,
      venueIds: ["szw"],
      weekdays: [6, 7],
      startTime: "18:00",
      endTime: "22:00",
      durationDays: 7,
      termCode: "7d",
      autoRenew: false,
      eligible: true,
      activeUntil: "2026-09-05T12:00:00.000Z",
      active: true,
      createdAt: "2026-08-29T12:00:00.000Z",
    }],
  };
  await page.route("**/api/bootstrap", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(dashboardWithSubscription),
    });
  });

  let cancellationCalls = 0;
  await page.route(`**/api/subscriptions/${subscriptionId}`, async (route) => {
    cancellationCalls += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ success: true }),
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "更多功能" }).click();
  await page.getByRole("menuitem", { name: "我的订阅" }).click();
  const cancelButton = page.getByRole("button", { name: "取消订阅" });

  page.once("dialog", async (dialog) => {
    expect(dialog.message()).toContain("确认取消这个订阅吗");
    await dialog.dismiss();
  });
  await cancelButton.click();
  expect(cancellationCalls).toBe(0);

  page.once("dialog", async (dialog) => dialog.accept());
  await cancelButton.click();
  await expect.poll(() => cancellationCalls).toBe(1);
  await expect(page.locator(".app-toast")).toContainText("订阅已取消");
});`;
  if (source.includes('test("prioritizes personal metrics')) {
    throw new Error("Subscription UX tests already patched");
  }
  source += `${extraTests}\n`;
  write(path, source);
}

{
  const path = "tests/webapp_header_actions_test.py";
  let source = read(path);
  source = replaceOnce(
    source,
    '    assert "<span>支持作者</span>" in source',
    '    assert "<span>支持 Zacks</span>" in source\n    assert "<span>支持作者</span>" not in source',
    "support contract visible copy",
  );
  source = replaceOnce(
    source,
    '    assert \'aria-label="请作者喝咖啡，支持项目维护"\' in source',
    '    assert \'aria-label="支持 Zacks，请作者喝咖啡"\' in source',
    "support contract accessible copy",
  );
  write(path, source);
}

{
  const path = "webapp/AGENTS.md";
  let source = read(path);
  source = appendOnce(
    source,
    'visible header support action is labeled "支持 Zacks"',
    '- The visible header support action is labeled "支持 Zacks" and remains a first-level header action; do not move it into the More menu.',
  );
  write(path, source);
}

console.log("Applied Web UX refresh, metric, cancellation, focus, and test updates.");
