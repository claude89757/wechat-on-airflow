import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { FALLBACK_DASHBOARD } from "../src/api";

const RECEIPTS_KEY = "zacks-tennis-verified-emails-v1";
const TODAY = "2026-11-02";
const TOMORROW = "2026-11-03";
const LATER = "2026-11-04";
const ALICE = { token: "pause-alice-token", email: "alice@example.invalid", maskedEmail: "a***@example.invalid", verifiedAt: "2026-11-02T00:00:00Z" };
const BOB = { token: "pause-bob-token", email: "bob@example.invalid", maskedEmail: "b***@example.invalid", verifiedAt: "2026-11-02T00:00:00Z" };

async function remember(page: Page, identities = [ALICE]) {
  await page.addInitScript(({ key, entries }) => {
    if (!localStorage.getItem(key)) localStorage.setItem(key, JSON.stringify(entries));
  }, { key: RECEIPTS_KEY, entries: identities });
}

async function mockService(context: BrowserContext) {
  const pauses = new Map([[ALICE.token, new Set<string>()], [BOB.token, new Set<string>()]]);
  const writes: Array<{ token: string; action: string; dates: string[] }> = [];
  const reads: string[] = [];
  const controls = { failNextWrite: false, failNextRead: false, expiredReceipt: false, verificationEmail: ALICE.email, codesRequested: 0 };
  const identities = [ALICE, BOB];
  await context.route("**/api/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const token = (request.headers().authorization ?? "").replace(/^Bearer /, "");
    const identity = identities.find(item => item.token === token);
    if (path === "/api/bootstrap") {
      const data = structuredClone(FALLBACK_DASHBOARD);
      data.generatedAt = "2026-11-02T09:00:00Z";
      data.identity = { ...data.identity, verified: Boolean(identity), maskedEmail: identity?.maskedEmail ?? null,
        activeSubscriptionCount: 1, remainingSubscriptions: 4 };
      data.subscriptions = identity ? [{ id: `subscription-${token}`, venueIds: ["szw"], weekdays: [1, 2, 3, 4, 5, 6, 7],
        startTime: "18:00", endTime: "22:00", durationDays: 14, termCode: "14d", autoRenew: false,
        eligible: true, active: true, activeUntil: "2026-11-16T12:00:00Z", createdAt: "2026-11-02T00:00:00Z" }] : [];
      return route.fulfill({ json: data });
    }
    if (path === "/api/notification-pauses") {
      if (!identity) return route.fulfill({ status: 401, json: { error: "请先验证邮箱" } });
      const values = pauses.get(token)!;
      if (request.method() === "GET") {
        reads.push(token);
        if (controls.expiredReceipt) {
          return route.fulfill({ status: 401, json: { error: "请重新验证邮箱" } });
        }
        if (controls.failNextRead) {
          controls.failNextRead = false;
          return route.fulfill({ status: 503, json: { error: "暂时无法读取日期" } });
        }
        return route.fulfill({ json: { pausedDates: [...values].sort(), today: TODAY, timezone: "Asia/Shanghai" } });
      }
      const { action, dates } = request.postDataJSON() as { action: string; dates: string[] };
      writes.push({ token, action, dates });
      if (controls.failNextWrite) {
        controls.failNextWrite = false;
        return route.fulfill({ status: 503, json: { error: "保存失败，请稍后重试" } });
      }
      const changedDates: string[] = [];
      for (const date of dates) {
        if ((action === "pause") !== values.has(date)) changedDates.push(date);
        if (action === "pause") values.add(date);
        else values.delete(date);
      }
      return route.fulfill({ json: { pausedDates: [...values].sort(), changedDates, today: TODAY, timezone: "Asia/Shanghai" } });
    }
    if (path === "/api/email/send-code") {
      controls.codesRequested += 1;
      controls.verificationEmail = request.postDataJSON().email;
      return route.fulfill({ json: { challengeId: "mock-pause-challenge", expiresInSeconds: 600 } });
    }
    if (path === "/api/email/verify") {
      controls.expiredReceipt = false;
      const verified = identities.find(item => item.email === controls.verificationEmail) ?? ALICE;
      return route.fulfill({ json: verified });
    }
    return route.abort("blockedbyclient");
  });
  return { pauses, writes, reads, controls };
}

async function openSubscriptions(page: Page) {
  await page.getByRole("button", { name: "更多功能", exact: true }).click();
  await page.getByRole("menuitem", { name: "我的订阅", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveAccessibleName("我的订阅");
  await expect(page.getByRole("button", { name: "选择暂停日期", exact: true })).toBeEnabled();
}

test("selects multiple booking dates, persists across reload, and resumes one date", async ({ page, context }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const service = await mockService(context);
  await remember(page);
  await page.goto("/");
  await openSubscriptions(page);
  await page.getByRole("button", { name: "选择暂停日期", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator(`[data-date="${TODAY}"]`).click();
  await dialog.locator(`[data-date="${TOMORROW}"]`).click();
  expect(service.writes).toHaveLength(0);
  await expect(dialog).toContainText("全部场馆、全部时段");
  await expect(dialog).toContainText(ALICE.maskedEmail);
  const save = dialog.getByRole("button", { name: "暂停这 2 天的提醒", exact: true });
  await save.scrollIntoViewIfNeeded();
  await expect(save).toBeInViewport({ ratio: 1 });
  await page.screenshot({ path: info.outputPath("date-pause-mobile.png") });
  await save.click();
  await expect(dialog).toHaveAccessibleName("我的订阅");
  await expect(dialog.locator("[data-pause-date]")).toHaveCount(2);
  expect(service.writes).toEqual([{ token: ALICE.token, action: "pause", dates: [TODAY, TOMORROW] }]);

  await page.reload();
  await expect(dialog).toHaveAccessibleName("我的订阅");
  await expect(dialog.locator("[data-pause-date]")).toHaveCount(2);
  await dialog.locator(`[data-pause-date="${TODAY}"]`).getByRole("button", { name: /恢复/ }).click();
  await expect(dialog.locator(`[data-pause-date="${TODAY}"]`)).toHaveCount(0);
  await expect(dialog.locator(`[data-pause-date="${TOMORROW}"]`)).toBeVisible();
  expect([...service.pauses.get(ALICE.token)!]).toEqual([TOMORROW]);
  await dialog.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(dialog.locator("[data-pause-date]")).toHaveCount(2);
  expect(service.writes.at(-1)).toEqual({ token: ALICE.token, action: "pause", dates: [TODAY] });
});

test("undo only changes dates actually mutated when another device pauses concurrently", async ({ page, context }) => {
  const service = await mockService(context);
  await remember(page);
  await page.goto("/");
  await openSubscriptions(page);
  await page.getByRole("button", { name: "选择暂停日期", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator(`[data-date="${TODAY}"]`).click();
  await dialog.locator(`[data-date="${TOMORROW}"]`).click();
  service.pauses.get(ALICE.token)!.add(TODAY); // An independent device finishes first.
  await dialog.getByRole("button", { name: "暂停这 2 天的提醒", exact: true }).click();
  await expect(dialog).toHaveAccessibleName("我的订阅");
  await expect(dialog.locator("[data-pause-date]")).toHaveCount(2);
  await dialog.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(dialog.locator(`[data-pause-date="${TODAY}"]`)).toBeVisible();
  await expect(dialog.locator(`[data-pause-date="${TOMORROW}"]`)).toHaveCount(0);
  expect(service.writes.at(-1)).toEqual({ token: ALICE.token, action: "resume", dates: [TOMORROW] });
});

test("keeps selection after a failed write and reads server changes each time management opens", async ({ page, context }) => {
  const service = await mockService(context);
  await remember(page);
  await page.goto("/");
  await openSubscriptions(page);
  await page.getByRole("button", { name: "选择暂停日期", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator(`[data-date="${TODAY}"]`).click();
  service.controls.failNextWrite = true;
  await dialog.getByRole("button", { name: "暂停这 1 天的提醒", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("保存失败");
  await expect(dialog.locator(`[data-date="${TODAY}"]`)).toHaveAttribute("aria-pressed", "true");
  await expect(dialog.locator(".date-pause-notice")).toHaveCount(0);
  expect(service.pauses.get(ALICE.token)!.size).toBe(0);
  await dialog.getByRole("button", { name: "重新读取日期", exact: true }).click();
  await dialog.getByRole("button", { name: "暂停这 1 天的提醒", exact: true }).click();
  await expect(dialog).toHaveAccessibleName("我的订阅");
  await dialog.getByRole("button", { name: "关闭订阅管理", exact: true }).click();
  await expect(dialog).toBeHidden();
  service.pauses.get(ALICE.token)!.add(LATER);
  await openSubscriptions(page);
  await expect(dialog.locator(`[data-pause-date="${LATER}"]`)).toBeVisible();
});

test("email link verifies an email then returns to the selected date without writing on GET", async ({ page, context }) => {
  const service = await mockService(context);
  await page.goto(`/?pauseDate=${TOMORROW}`);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toHaveAccessibleName("验证邮箱");
  await expect(dialog).toContainText("2026年11月3日");
  expect(service.writes).toHaveLength(0);
  await dialog.getByLabel("订阅邮箱", { exact: true }).fill(ALICE.email);
  await dialog.getByRole("button", { name: "发送验证码", exact: true }).click();
  await dialog.getByLabel("6 位验证码", { exact: true }).fill("123456");
  await dialog.getByRole("button", { name: "验证并继续", exact: true }).click();
  await expect(dialog).toHaveAccessibleName("暂停打球日期的提醒");
  await expect(dialog.locator(`[data-date="${TOMORROW}"]`)).toHaveAttribute("aria-pressed", "true");
  await expect(dialog.getByRole("button", { name: "暂停这 1 天的提醒", exact: true })).toBeEnabled();
  expect(service.writes).toHaveLength(0);
  expect(service.controls.codesRequested).toBe(1);
  await dialog.getByRole("button", { name: "暂停这 1 天的提醒", exact: true }).click();
  await expect(dialog).toHaveAccessibleName("我的订阅");
  await dialog.getByRole("button", { name: "关闭订阅管理", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page).not.toHaveURL(/pauseDate=/);
});

test("switching identities preserves the pending action but isolates saved pauses and write ownership", async ({ page, context }) => {
  const service = await mockService(context);
  service.pauses.get(ALICE.token)!.add(TODAY);
  service.pauses.get(BOB.token)!.add(TOMORROW);
  await remember(page, [ALICE, BOB]);
  await page.goto("/");
  await openSubscriptions(page);
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator(`[data-pause-date="${TODAY}"]`)).toBeVisible();
  await dialog.getByRole("button", { name: "选择暂停日期", exact: true }).click();
  await dialog.locator(`[data-date="${LATER}"]`).click();
  await dialog.locator(".date-pause-identity").getByRole("button", { name: "更换", exact: true }).click();
  await expect(dialog).toHaveAccessibleName("验证邮箱");
  await dialog.getByRole("button", { name: BOB.maskedEmail, exact: true }).click();
  await expect(dialog).toHaveAccessibleName("暂停打球日期的提醒");
  await expect(dialog.locator(".date-pause-identity")).toContainText(BOB.maskedEmail);
  await expect(dialog.locator(`[data-date="${TOMORROW}"]`)).toBeDisabled();
  await expect(dialog.locator(`[data-date="${TODAY}"]`)).toBeEnabled();
  await expect(dialog.locator(`[data-date="${LATER}"]`)).toHaveAttribute("aria-pressed", "true");
  await expect(dialog.getByRole("button", { name: "暂停这 1 天的提醒", exact: true })).toBeEnabled();
  expect(service.writes).toHaveLength(0);
  await dialog.getByRole("button", { name: "暂停这 1 天的提醒", exact: true }).click();
  await expect(dialog).toHaveAccessibleName("我的订阅");
  await expect(dialog.locator(`[data-pause-date="${TOMORROW}"]`)).toBeVisible();
  await expect(dialog.locator(`[data-pause-date="${TODAY}"]`)).toHaveCount(0);
  expect(service.writes).toEqual([{ token: BOB.token, action: "pause", dates: [LATER] }]);
  expect(service.reads.at(-1)).toBe(BOB.token);
});

test("an expired receipt returns to the pending mail date after verification", async ({ page, context }) => {
  const service = await mockService(context);
  service.controls.expiredReceipt = true;
  await remember(page);
  await page.goto(`/?pauseDate=${TOMORROW}`);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toHaveAccessibleName("验证邮箱");
  await expect(dialog.getByRole("alert")).toContainText("验证已过期");
  await dialog.getByRole("button", { name: "发送验证码", exact: true }).click();
  await dialog.getByLabel("6 位验证码", { exact: true }).fill("123456");
  await dialog.getByRole("button", { name: "验证并继续", exact: true }).click();
  await expect(dialog).toHaveAccessibleName("暂停打球日期的提醒");
  await expect(dialog.locator(`[data-date="${TOMORROW}"]`)).toHaveAttribute("aria-pressed", "true");
  await expect(dialog.getByRole("button", { name: "暂停这 1 天的提醒", exact: true })).toBeEnabled();
  expect(service.writes).toHaveLength(0);
});

test("browser back returns one view at a time without adding history for selected dates", async ({ page, context }) => {
  const service = await mockService(context);
  await remember(page);
  await page.goto("/");
  await openSubscriptions(page);
  await page.getByRole("button", { name: "选择暂停日期", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator(`[data-date="${TODAY}"]`).click();
  await dialog.locator(`[data-date="${TOMORROW}"]`).click();
  await page.goBack();
  await expect(dialog).toHaveAccessibleName("我的订阅");
  await page.goBack();
  await expect(dialog).toBeHidden();
  expect(service.writes).toHaveLength(0);
});

test("uses the server's Shanghai date, rejects a past mail date, and allows another future date", async ({ page, context }) => {
  const service = await mockService(context);
  await remember(page);
  await page.goto("/?pauseDate=2026-11-01");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toHaveAccessibleName("暂停打球日期的提醒");
  await expect(dialog.getByRole("alert")).toContainText("已过去");
  await expect(dialog.getByRole("button", { name: "请选择打球日期", exact: true })).toBeDisabled();
  const dateInput = dialog.getByLabel("其他打球日期", { exact: true });
  await expect(dateInput).toHaveAttribute("min", TODAY);
  await expect(dateInput).toHaveAttribute("max", "2027-11-02");
  await dateInput.fill("2026-12-25");
  await dialog.getByRole("button", { name: "添加日期", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "暂停这 1 天的提醒", exact: true })).toBeEnabled();
  expect(service.writes).toHaveLength(0);
  await dialog.getByRole("button", { name: "暂停这 1 天的提醒", exact: true }).click();
  await expect(dialog).toHaveAccessibleName("我的订阅");
  await expect(dialog.locator('[data-pause-date="2026-12-25"]')).toBeVisible();
});
