import { expect, test, type Page } from "@playwright/test";
import { FALLBACK_DASHBOARD } from "../src/api";

const PROMO_KEY = "zacks:gear-promo:2026-11:seen-v2";
type PromoEvent = { mode: string | null; at: number };

async function fixture(page: Page) {
  const dashboard = structuredClone(FALLBACK_DASHBOARD);
  dashboard.generatedAt = new Date().toISOString();
  dashboard.venues.forEach(venue => { venue.lastInspectionAt = dashboard.generatedAt; });
  let writes = 0;
  // No acceptance test may create a subscription or send email/WeChat.
  await page.route("**/api/**", route => {
    const request = route.request();
    if (request.method() !== "GET") {
      writes += 1;
      return route.abort("blockedbyclient");
    }
    if (new URL(request.url()).pathname === "/api/bootstrap") {
      return route.fulfill({ json: dashboard });
    }
    return route.fulfill({ status: 404, json: { error: "Unmocked request blocked by acceptance test" } });
  });
  await page.goto("/");
  await expect(page.locator(".venue-card")).toHaveCount(26);
  return () => writes;
}

async function openManually(page: Page, keyboard = false) {
  const more = page.getByRole("button", { name: "更多功能", exact: true });
  if (keyboard) {
    await more.focus();
    await page.keyboard.press("Enter");
    await page.getByRole("menuitem", { name: "球友好物", exact: true }).focus();
    await page.keyboard.press("Enter");
  } else {
    await more.click();
    await page.getByRole("menuitem", { name: "球友好物", exact: true }).click();
  }
  const promo = page.getByTestId("gear-promo");
  await expect(promo).toBeVisible();
  await expect(promo).toHaveAttribute("data-mode", "manual");
  return promo;
}

test("automatic recommendation closes after ten seconds and respects the 24-hour limit", async ({ page }) => {
  test.setTimeout(40_000);
  // Observe actual DOM lifetime, rather than inferring timing from a countdown label.
  await page.addInitScript(() => {
    const events: Array<{ mode: string | null; at: number }> = [];
    (window as Window & { gearPromoEvents?: typeof events }).gearPromoEvents = events;
    let previous: string | null = null;
    new MutationObserver(() => {
      const mode = document.querySelector('[data-testid="gear-promo"]')?.getAttribute("data-mode") ?? null;
      if (mode !== previous) events.push({ mode, at: performance.now() });
      previous = mode;
    }).observe(document, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-mode"] });
  });
  const writes = await fixture(page);
  const more = page.getByRole("button", { name: "更多功能", exact: true });
  await more.focus();
  const promo = page.getByTestId("gear-promo");
  await expect(promo).toBeVisible({ timeout: 7_000 });
  await expect(promo).toHaveAttribute("data-mode", "auto");
  await expect(more).toBeFocused();
  expect(await page.evaluate(key => localStorage.getItem(key), PROMO_KEY)).toBeNull();
  await promo.hover();
  await expect(promo).toBeHidden({ timeout: 12_000 });
  const events = await page.evaluate(() => (window as Window & { gearPromoEvents?: PromoEvent[] }).gearPromoEvents ?? []);
  const appeared = events.find(event => event.mode === "auto");
  const dismissed = events.find(event => event.mode === null && event.at > (appeared?.at ?? Infinity));
  expect(appeared).toBeTruthy();
  expect(dismissed).toBeTruthy();
  expect(dismissed!.at - appeared!.at).toBeGreaterThanOrEqual(9_800);
  expect(dismissed!.at - appeared!.at).toBeLessThan(11_500);
  const recordedAt = Number(await page.evaluate(key => localStorage.getItem(key), PROMO_KEY));
  expect(Date.now() - recordedAt).toBeLessThan(1_000);

  await page.reload();
  await page.waitForTimeout(4_500);
  await expect(promo).toBeHidden();
  // A genuinely expired cooldown becomes eligible again, without changing campaign code.
  await page.evaluate(key => {
    localStorage.setItem(key, String(Date.now() - 25 * 60 * 60 * 1_000));
    sessionStorage.removeItem(key);
  }, PROMO_KEY);
  await page.reload();
  await expect(promo).toBeVisible({ timeout: 7_000 });
  await promo.getByRole("button", { name: "关闭商品推荐", exact: true }).click();
  await expect(promo).toBeHidden();
  expect(writes()).toBe(0);
});

test("search and subscription work take precedence over an automatic recommendation", async ({ page }) => {
  test.setTimeout(30_000);
  const writes = await fixture(page);
  const promo = page.getByTestId("gear-promo");
  await page.getByLabel("搜索场地", { exact: true }).focus();
  await page.waitForTimeout(4_500);
  await expect(promo).toBeHidden();
  await page.getByRole("button", { name: "设置我的提醒", exact: true }).click();
  const subscription = page.getByRole("dialog", { name: "验证邮箱", exact: true });
  await expect(subscription).toBeVisible();
  await page.waitForTimeout(3_500);
  await expect(promo).toBeHidden();
  await page.keyboard.press("Escape");
  await expect(subscription).toBeHidden();
  await expect(promo).toBeVisible({ timeout: 7_000 });
  expect(await page.evaluate(key => localStorage.getItem(key), PROMO_KEY)).toBeNull();
  await page.getByRole("button", { name: "设置我的提醒", exact: true }).click();
  await expect(subscription).toBeVisible();
  await expect(promo).toBeHidden();
  expect(await page.evaluate(key => localStorage.getItem(key), PROMO_KEY)).toBeNull();
  await page.keyboard.press("Escape");
  await expect(subscription).toBeHidden();
  // A business interruption must not consume the visitor’s first impression.
  await expect(promo).toBeVisible({ timeout: 7_000 });
  await expect(promo).toHaveAttribute("data-mode", "auto");
  await promo.getByRole("button", { name: "关闭商品推荐", exact: true }).click();
  expect(Number(await page.evaluate(key => localStorage.getItem(key), PROMO_KEY))).toBeGreaterThan(0);
  expect(writes()).toBe(0);
});

test("manual viewing stays open, copies the exact contact and restores keyboard focus", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const writes = await fixture(page);
  const promo = await openManually(page, true);
  await expect(promo).toContainText("网球包");
  await expect(promo).toContainText("网球帽");
  await expect(promo).toContainText(/¥\s*860/);
  await expect(promo).toContainText(/¥\s*300/);
  await expect(promo).toContainText("深圳南山自提");
  await expect(promo).toContainText("thanks0");
  const copy = promo.getByRole("button", { name: "复制微信号", exact: true });
  await copy.focus();
  await page.keyboard.press("Enter");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("thanks0");
  await page.waitForTimeout(10_500);
  await expect(promo).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(promo).toBeHidden();
  await expect(page.getByRole("button", { name: "更多功能", exact: true })).toBeFocused();
  expect(writes()).toBe(0);
});

for (const width of [320, 393, 1440]) {
  test(`product images and controls fit ${width}px without covering mobile navigation`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: width === 320 ? 568 : 852 });
    await page.emulateMedia({ reducedMotion: width === 320 ? "reduce" : "no-preference" });
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    const writes = await fixture(page);
    const promo = await openManually(page);
    const images = promo.getByRole("img");
    await expect(images).toHaveCount(2);
    await expect.poll(() => images.evaluateAll(elements => elements.every(element => {
      const image = element as HTMLImageElement;
      return image.complete && image.naturalWidth > 0;
    }))).toBe(true);
    await expect(promo).toBeInViewport({ ratio: 1 });
    const copy = promo.getByRole("button", { name: "复制微信号", exact: true });
    const close = promo.getByRole("button", { name: "关闭商品推荐", exact: true });
    await expect(copy).toBeInViewport({ ratio: 1 });
    await expect(close).toBeInViewport({ ratio: 1 });
    if (width < 900) {
      const nav = page.getByRole("navigation", { name: "快捷导航", exact: true });
      await expect(nav).toBeInViewport({ ratio: 1 });
      const promoBox = await promo.boundingBox();
      const navBox = await nav.boundingBox();
      expect(promoBox!.y + promoBox!.height).toBeLessThanOrEqual(navBox!.y + 1);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await page.screenshot({ path: info.outputPath(`gear-promo-${width}.png`) });
    await close.click();
    await expect(promo).toBeHidden();
    expect(errors).toEqual([]);
    expect(writes()).toBe(0);
  });
}

test("unavailable browser storage still permits one automatic view and manual contact access", async ({ page }) => {
  test.setTimeout(30_000);
  await page.addInitScript(key => {
    const read = Storage.prototype.getItem;
    const write = Storage.prototype.setItem;
    Storage.prototype.getItem = function (name: string) {
      if (name === key) throw new DOMException("Storage blocked", "SecurityError");
      return read.call(this, name);
    };
    Storage.prototype.setItem = function (name: string, value: string) {
      if (name === key) throw new DOMException("Storage blocked", "SecurityError");
      write.call(this, name, value);
    };
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: async () => { throw new DOMException("Clipboard blocked", "NotAllowedError"); } },
    });
  }, PROMO_KEY);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const writes = await fixture(page);
  const automatic = page.getByTestId("gear-promo");
  await expect(automatic).toBeVisible({ timeout: 7_000 });
  await expect(automatic).toHaveAttribute("data-mode", "auto");
  await expect(automatic).toBeHidden({ timeout: 12_000 });
  await page.waitForTimeout(3_500);
  await expect(automatic).toBeHidden();
  const promo = await openManually(page);
  await promo.getByRole("button", { name: "复制微信号", exact: true }).click();
  await expect(promo).toContainText("thanks0");
  await expect(promo).toContainText(/长按|手动复制/);
  await promo.getByRole("button", { name: "关闭商品推荐", exact: true }).click();
  await expect(promo).toBeHidden();
  expect(errors).toEqual([]);
  expect(writes()).toBe(0);
});
