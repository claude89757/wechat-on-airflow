import { expect, test } from "@playwright/test";

const RECEIPTS_KEY = "zacks-tennis-verified-emails-v1";
const REPOSITORY_URL = "https://github.com/claude89757/wechat-on-airflow";

const dashboard = {
  generatedAt: "2026-08-29T12:00:00.000Z",
  weatherEmailGate: { suppressed: false, precipitationMm: 0, thresholdMm: 25 },
  metrics: { activeSubscriptions: 16, remindersToday: 2, healthyVenues: 3, totalVenues: 3 },
  deliveryTiers: { standard: 10, priority: 100 },
  subscriptionTerms: {
    standard: ["7d", "8d", "9d", "10d", "11d", "12d", "13d", "14d"],
    priority: ["7d", "8d", "9d", "10d", "11d", "12d", "13d", "14d", "30d", "90d", "180d", "long_term"],
  },
  subscriptionLimits: { standard: 5, priority: 20 },
  venues: [
    { id: "szw", name: "深圳湾", healthy: true, subscriberCount: 2, lastInspectionAt: "2026-08-29T11:59:50.000Z", lastNotificationAt: null },
    { id: "tops", name: "TOPS 科技园", healthy: true, subscriberCount: 9, lastInspectionAt: "2026-08-29T11:59:48.000Z", lastNotificationAt: null },
    { id: "jdwx", name: "金地威新", healthy: true, subscriberCount: 5, lastInspectionAt: "2026-08-29T11:59:45.000Z", lastNotificationAt: null },
  ],
  identity: {
    verified: true,
    maskedEmail: "m***@example.com",
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

test.beforeEach(async ({ page }) => {
  await page.addInitScript(
    ({ key }) => {
      localStorage.setItem(key, JSON.stringify([{
        token: "subscription-ux-token",
        email: "mobile@example.com",
        maskedEmail: "m***@example.com",
        verifiedAt: "2026-08-29T12:00:00.000Z",
      }]));
    },
    { key: RECEIPTS_KEY },
  );
  await page.route("**/api/bootstrap", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(dashboard),
    });
  });
});

test("exposes the repository and orders venues by unique follower count", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("button", { name: "更多功能" }).click();
  const repositoryLink = page.getByRole("menuitem", { name: "项目开源地址" });
  await expect(repositoryLink).toHaveAttribute("href", REPOSITORY_URL);
  await expect(repositoryLink).toHaveAttribute("target", "_blank");
  await expect(repositoryLink).toHaveAttribute("rel", "noopener noreferrer");
  await page.keyboard.press("Escape");

  const venueNames = await page.locator(".venue-list .venue-name h3").allTextContents();
  expect(venueNames).toEqual(["TOPS 科技园", "金地威新", "深圳湾"]);
  await expect(page.locator(".venue-list .venue-name p").first()).toHaveText("9 人关注");
});

test("creates a weekend subscription with a summary and one-shot celebration", async ({ page }) => {
  let submittedPayload: Record<string, unknown> | null = null;
  await page.route("**/api/subscriptions", async (route) => {
    submittedPayload = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        subscription: {
          id: "weekend-subscription",
          venueIds: ["szw", "tops"],
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
        },
      }),
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "创建订阅", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("指定巡检星期")).toBeVisible();

  await dialog.getByRole("button", { name: "周末", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "星期六" })).toHaveAttribute("aria-pressed", "true");
  await expect(dialog.getByRole("button", { name: "星期日" })).toHaveAttribute("aria-pressed", "true");
  await expect(dialog.getByRole("button", { name: "星期一" })).toHaveAttribute("aria-pressed", "false");
  await expect(dialog.locator(".subscription-summary")).toContainText("周末");

  await dialog.getByRole("button", { name: "清空", exact: true }).click();
  await expect(dialog.getByRole("alert")).toHaveText("请至少选择一个场地");
  await expect(dialog.getByRole("button", { name: "确认创建订阅" })).toBeDisabled();
  await dialog.getByRole("button", { name: "全选", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "确认创建订阅" })).toBeEnabled();

  await dialog.getByRole("button", { name: "确认创建订阅" }).click();
  await expect.poll(() => submittedPayload).not.toBeNull();
  expect(submittedPayload).toMatchObject({ weekdays: [6, 7] });
  await expect(page.getByTestId("subscription-celebration")).toBeVisible();
  await expect(page.locator(".app-toast")).toContainText("订阅已创建");
  await expect(page.locator(".app-toast")).toContainText("周末");
});

test("keeps the success message but suppresses fireworks for reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.route("**/api/subscriptions", async (route) => {
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        subscription: {
          id: "reduced-motion-subscription",
          venueIds: ["szw", "tops"],
          weekdays: [1, 2, 3, 4, 5, 6, 7],
          startTime: "18:00",
          endTime: "22:00",
          durationDays: 7,
          termCode: "7d",
          autoRenew: false,
          eligible: true,
          activeUntil: "2026-09-05T12:00:00.000Z",
          active: true,
          createdAt: "2026-08-29T12:00:00.000Z",
        },
      }),
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "创建订阅", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "确认创建订阅" }).click();

  await expect(page.locator(".app-toast")).toContainText("订阅已创建");
  await expect(page.getByTestId("subscription-celebration")).toBeHidden();
});
