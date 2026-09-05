import { expect, test, type Page } from "@playwright/test";
import { FALLBACK_DASHBOARD, type Dashboard } from "../src/api";

const receipt = { token: "studio-offline-test-only", email: "studio@example.com", maskedEmail: "s***@example.com", verifiedAt: "2026-09-05T00:00:00Z" };
async function fixture(page: Page, verified = false) {
  const dashboard: Dashboard = structuredClone(FALLBACK_DASHBOARD);
  dashboard.generatedAt = new Date().toISOString();
  dashboard.venues.forEach(v => { v.lastInspectionAt = new Date().toISOString(); });
  dashboard.identity.verified = verified;
  dashboard.identity.maskedEmail = verified ? receipt.maskedEmail : null;
  const requests: Array<{ path: string; method: string; data: unknown }> = [];
  if (verified) await page.addInitScript(value => localStorage.setItem("zacks-tennis-verified-emails-v1", JSON.stringify([value])), receipt);
  // Every API request is intercepted. Tests cannot send real mail or messages.
  await page.route("**/api/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const body = request.postData() ? request.postDataJSON() : null;
    requests.push({ path, method: request.method(), data: body });
    if (path === "/api/bootstrap") return route.fulfill({ json: dashboard });
    if (path === "/api/email/send-code") return route.fulfill({ json: { challengeId: "offline-challenge", expiresAt: "2099-01-01T00:00:00Z" } });
    if (path === "/api/email/verify") {
      if (body.code !== "123456") return route.fulfill({ status: 400, json: { error: "验证码不正确，请重试" } });
      dashboard.identity.verified = true; dashboard.identity.maskedEmail = receipt.maskedEmail;
      return route.fulfill({ json: receipt });
    }
    if (path === "/api/subscriptions" && request.method() === "POST") {
      const subscription = { id: "offline-subscription", ...body, durationDays: 7, autoRenew: false, eligible: true, active: true, activeUntil: "2099-01-01T00:00:00Z", createdAt: new Date().toISOString() };
      dashboard.subscriptions = [subscription]; dashboard.identity.activeSubscriptionCount = 1; dashboard.identity.remainingSubscriptions = 4;
      return route.fulfill({ status: 201, json: { subscription } });
    }
    if (path === "/api/subscriptions/offline-subscription" && request.method() === "DELETE") {
      dashboard.subscriptions = []; dashboard.identity.activeSubscriptionCount = 0; dashboard.identity.remainingSubscriptions = 5;
      return route.fulfill({ json: { success: true } });
    }
    return route.fulfill({ status: 404, json: { error: "unmocked endpoint blocked by test" } });
  });
  return { dashboard, requests };
}

for (const width of [320, 390, 768, 900, 1440]) {
  test(`Court Studio fits ${width}px with reachable navigation`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
    await fixture(page);
    await page.goto("/");
    await expect(page.locator("main")).toHaveAttribute("data-ui-version", "0.8.0");
    await expect(page.getByRole("heading", { name: "把时间，留给打球。" })).toBeVisible();
    await expect(page.locator(".venue-card")).toHaveCount(26);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    if (width < 900) {
      await expect(page.getByRole("navigation", { name: "快捷导航" })).toBeInViewport();
      await page.getByRole("navigation", { name: "快捷导航" }).getByRole("button", { name: "创建提醒" }).click();
    } else {
      await expect(page.getByRole("button", { name: "设置我的提醒" })).toBeInViewport();
      await page.getByRole("button", { name: "设置我的提醒" }).click();
    }
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(page.getByLabel("订阅邮箱")).not.toBeFocused();
    const box = await dialog.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(-1);
    expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    expect(errors).toEqual([]);
    await page.screenshot({ path: info.outputPath(`home-${width}.png`) });
    await info.attach(`home-${width}`, { path: info.outputPath(`home-${width}.png`), contentType: "image/png" });
  });
}

test("search and filters stay local and have recoverable empty states", async ({ page }) => {
  const { requests } = await fixture(page);
  await page.goto("/");
  await expect(page.locator(".venue-card")).toHaveCount(26);
  const initial = requests.length;
  await page.getByLabel("搜索场地").fill("前海");
  await expect(page.locator(".venue-card")).toHaveCount(1);
  await expect(page.locator(".venue-card-name")).toHaveText("FFTENNIS前海国际网球中心");
  await page.getByLabel("搜索场地").fill("没有这个球场");
  await expect(page.getByText("没有找到这个场地", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "查看全部场地", exact: true }).click();
  await expect(page.locator(".venue-card")).toHaveCount(26);
  await page.getByRole("button", { name: "我已订阅", exact: true }).click();
  await expect(page.getByText("还没有订阅场地", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "需要关注", exact: true }).click();
  await expect(page.getByText("当前没有需要关注的场地", { exact: true })).toBeVisible();
  expect(requests.length).toBe(initial);
  await page.getByRole("button", { name: "获取最新状态", exact: true }).click();
  await expect.poll(() => requests.length).toBe(initial + 1);
});

test("new visitor can verify, keep venue, create a weekend alert and cancel safely", async ({ page }) => {
  const { requests } = await fixture(page);
  await page.goto("/");
  await page.getByTestId("venue-card-tops").click();
  const dialog = page.getByRole("dialog");
  await page.getByLabel("订阅邮箱").fill(receipt.email);
  await page.getByRole("button", { name: "发送验证码", exact: true }).click();
  await page.getByLabel("6 位验证码").fill("999999");
  await page.getByRole("button", { name: "验证并继续", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("验证码不正确");
  await page.getByLabel("6 位验证码").fill("123456");
  await page.getByRole("button", { name: "验证并继续", exact: true }).click();
  await expect(dialog.locator(".subscription-form")).toBeVisible();
  await expect(dialog.locator(".quick-venue-selection")).toContainText("TOPS 科技园");
  await dialog.getByRole("button", { name: "周末", exact: true }).click();
  await dialog.getByRole("button", { name: /^午后/ }).click();
  await expect(dialog.locator(".subscription-summary")).toContainText("周末 · 12:00–18:00");
  await dialog.getByRole("button", { name: "创建TOPS 科技园提醒", exact: true }).click();
  await expect(page.locator(".app-toast")).toContainText("提醒已创建");
  const posts = requests.filter(r => r.path === "/api/subscriptions" && r.method === "POST");
  expect(posts).toHaveLength(1);
  expect(posts[0].data).toMatchObject({ venueIds: ["tops"], weekdays: [6, 7], startTime: "12:00", endTime: "18:00", termCode: "7d" });
  await page.locator(".more-button").click(); await page.getByRole("menuitem", { name: "我的订阅", exact: true }).click();
  const cancel = page.getByRole("button", { name: "取消订阅", exact: true });
  page.once("dialog", d => d.dismiss()); await cancel.click();
  expect(requests.filter(r => r.method === "DELETE")).toHaveLength(0);
  page.once("dialog", d => d.accept()); await cancel.click();
  await expect(page.getByText("还没有订阅", { exact: true })).toBeVisible();
  expect(requests.filter(r => r.method === "DELETE")).toHaveLength(1);
});

test("changing the email resets its old verification challenge", async ({ page }) => {
  const { requests } = await fixture(page);
  await page.goto("/"); await page.getByRole("button", { name: "创建订阅", exact: true }).click();
  await page.getByLabel("订阅邮箱").fill(receipt.email);
  await page.getByRole("button", { name: "发送验证码", exact: true }).click();
  await expect(page.getByLabel("6 位验证码")).toBeVisible();
  await page.getByLabel("订阅邮箱").fill("different@example.com");
  await expect(page.getByLabel("6 位验证码")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "发送验证码", exact: true })).toBeEnabled();
  expect(requests.filter(r => r.path === "/api/email/verify")).toHaveLength(0);
});

test("unknown and stale data never becomes a healthy court signal", async ({ page }) => {
  const { dashboard } = await fixture(page);
  dashboard.dataStatus = { stale: true, source: "browser-cache", reason: "data_store_unavailable", retryAt: null };
  await page.goto("/");
  await expect(page.locator(".service-stale")).toBeVisible();
  await expect(page.locator(".venue-card-healthy")).toHaveCount(0);
  await expect(page.locator(".venue-card-unknown")).toHaveCount(26);
  await expect(page.getByText(/D1 免费额度每天/)).toHaveCount(0);
});

test("priority identity is not presented as weather-paused", async ({ page }) => {
  const { dashboard } = await fixture(page, true);
  dashboard.identity.tier = "priority";
  dashboard.weatherEmailGate = { suppressed: true, precipitationMm: 40, thresholdMm: 25 };
  await page.goto("/");
  await expect(page.locator(".tier-priority")).toBeVisible();
  await expect(page.locator(".weather-notice")).toHaveCount(0);
  await expect(page.getByText("邮件暂停", { exact: true })).toHaveCount(0);
});

test("non-admin menu hides admin and keyboard dismissal keeps focus", async ({ page }) => {
  await fixture(page, true); await page.goto("/");
  const more = page.getByRole("button", { name: "更多功能", exact: true });
  await more.focus(); await page.keyboard.press("Enter");
  await expect(page.getByRole("menuitem", { name: "用户社区" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "管理后台" })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(more).toBeFocused();
});
