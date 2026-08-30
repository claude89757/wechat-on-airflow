import { expect, test } from "@playwright/test";

const MOBILE_VIEWPORT = { width: 393, height: 852 };
const RECEIPTS_KEY = "zacks-tennis-verified-emails-v1";

test.describe("mobile v2 presentation", () => {
  test.use({ viewport: MOBILE_VIEWPORT });

  test("keeps the primary mobile surfaces readable and inside the viewport", async ({ page }) => {
    await page.goto("/");

    await expect(page.locator("main.dashboard-screen")).toBeVisible();
    await expect(page.locator(".primary-button")).toBeVisible();

    const stylesheetLoaded = await page.evaluate(() =>
      Array.from(document.styleSheets).some((sheet) => sheet.href?.includes("/mobile-v2.css")),
    );
    expect(stylesheetLoaded).toBe(true);

    const primaryButton = await page.locator(".primary-button").boundingBox();
    expect(primaryButton?.height ?? 0).toBeGreaterThanOrEqual(52);

    const moreButton = page.getByRole("button", { name: "更多功能", exact: true });
    const moreButtonBox = await moreButton.boundingBox();
    expect(moreButtonBox?.width ?? 0).toBeGreaterThanOrEqual(44);
    expect(moreButtonBox?.height ?? 0).toBeGreaterThanOrEqual(44);

    const coffeeButton = page.getByRole("button", { name: "请作者喝咖啡", exact: true });
    await expect(coffeeButton).toBeVisible();
    const coffeeButtonBox = await coffeeButton.boundingBox();
    expect(coffeeButtonBox?.height ?? 0).toBeGreaterThanOrEqual(44);

    const metrics = page.locator(".metric");
    await expect(metrics).toHaveCount(3);
    for (let index = 0; index < 3; index += 1) {
      const metricBox = await metrics.nth(index).boundingBox();
      expect(metricBox?.height ?? 0).toBeGreaterThanOrEqual(90);
    }

    const firstVenue = page.locator(".venue-row").first();
    await expect(firstVenue).toBeVisible();
    const venueBox = await firstVenue.boundingBox();
    expect(venueBox?.height ?? 0).toBeGreaterThanOrEqual(78);
    await expect(firstVenue.locator(".venue-mail")).toHaveCSS("display", "flex");

    const surfaceOverflow = await page.evaluate(() => {
      const viewportWidth = document.documentElement.clientWidth;
      const selectors = [
        ".product-header",
        ".service-line",
        ".metric-band",
        ".create-card",
        ".venue-section",
        ".subscriptions-link",
      ];

      return selectors.some((selector) => {
        const element = document.querySelector<HTMLElement>(selector);
        if (!element) return true;
        const rect = element.getBoundingClientRect();
        return rect.left < -0.5 || rect.right > viewportWidth + 0.5;
      });
    });
    expect(surfaceOverflow).toBe(false);
  });

  test("turns the verified subscription sheet into touch-friendly mobile controls", async ({ page }) => {
    await page.addInitScript(
      ({ key }) => {
        localStorage.setItem(
          key,
          JSON.stringify([
            {
              token: "mobile-v2-test-token",
              email: "mobile@example.com",
              maskedEmail: "m***@example.com",
              verifiedAt: new Date().toISOString(),
            },
          ]),
        );
      },
      { key: RECEIPTS_KEY },
    );

    await page.goto("/");
    await page.locator(".primary-button").click();

    await expect(page.locator(".bottom-sheet")).toBeVisible();
    await expect(page.locator(".subscription-form")).toBeVisible();
    await expect(page.locator(".venue-choices")).toHaveCSS("display", "grid");
    await expect(page.locator(".weekday-choices")).toHaveCSS("display", "grid");
    await expect(page.locator(".day-choices")).toHaveCSS("display", "grid");

    const venueButtons = page.locator(".venue-choices button");
    expect(await venueButtons.count()).toBeGreaterThan(1);
    for (let index = 0; index < Math.min(await venueButtons.count(), 4); index += 1) {
      const buttonBox = await venueButtons.nth(index).boundingBox();
      expect(buttonBox?.height ?? 0).toBeGreaterThanOrEqual(46);
    }

    const dayButtons = page.locator(".day-choices button");
    await expect(dayButtons).toHaveCount(8);
    const dayButtonBox = await dayButtons.first().boundingBox();
    expect(dayButtonBox?.height ?? 0).toBeGreaterThanOrEqual(44);

    const weekdayButtons = page.locator(".weekday-choices button");
    await expect(weekdayButtons).toHaveCount(7);
    const weekdayButtonBox = await weekdayButtons.first().boundingBox();
    expect(weekdayButtonBox?.height ?? 0).toBeGreaterThanOrEqual(44);
    await page.getByRole("button", { name: "周末", exact: true }).click();
    await expect(page.getByRole("button", { name: "星期六" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".subscription-summary")).toContainText("周末");

    const submitButton = page.locator(".subscription-form .sheet-primary");
    await expect(submitButton).toHaveCSS("position", "sticky");
    const submitBox = await submitButton.boundingBox();
    expect(submitBox?.height ?? 0).toBeGreaterThanOrEqual(52);
  });

  test("reveals the coffee invite only five seconds after the QR image loads", async ({ page }) => {
    const fixedNow = new Date("2026-08-23T08:00:00.000Z");
    await page.clock.install({ time: fixedNow });
    await page.addInitScript(
      ({ key }) => {
        localStorage.setItem(
          key,
          JSON.stringify([
            {
              token: "coffee-test-token",
              email: "coffee@example.com",
              maskedEmail: "c***@example.com",
              verifiedAt: new Date().toISOString(),
            },
          ]),
        );
      },
      { key: RECEIPTS_KEY },
    );

    let sessionCalls = 0;
    let claimCalls = 0;
    await page.route("**/api/coffee/session", async (route) => {
      sessionCalls += 1;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          claimToken: "coffee-claim-token",
          availableAt: fixedNow.toISOString(),
          expiresAt: "2026-08-23T08:10:00.000Z",
          alreadyClaimed: false,
        }),
      });
    });
    await page.route("**/api/coffee/invite", async (route) => {
      claimCalls += 1;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          code: "ACE-LATTE-OTTER-7K9P2Q",
          expiresAt: "2026-09-22T08:00:00.000Z",
          claimedAt: fixedNow.toISOString(),
          reused: false,
          status: "available",
        }),
      });
    });

    await page.goto("/");
    await page.getByRole("button", { name: "请作者喝咖啡", exact: true }).click();

    const qrImage = page.getByRole("img", { name: "微信支付收款二维码，收款人 Tt（**添）" });
    await expect(qrImage).toBeVisible();
    await expect.poll(() => qrImage.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true);
    await page.clock.fastForward(32);
    await expect.poll(() => sessionCalls).toBe(1);
    await expect(page.getByText("收款码已显示，请完成支付，稍候片刻。")).toBeVisible();

    const claimButton = page.getByRole("button", { name: "已请咖啡", exact: true });
    await expect(claimButton).toHaveCount(0);
    await page.clock.fastForward(4_999);
    await expect(claimButton).toHaveCount(0);
    await page.clock.fastForward(1);
    await expect(claimButton).toBeVisible();

    await claimButton.click();
    await expect.poll(() => claimCalls).toBe(1);
    await expect(page.getByText("彩蛋已解锁")).toBeVisible();
    await expect(page.getByText("ACE-LATTE-OTTER-7K9P2Q", { exact: true })).toBeVisible();
    await expect(page.getByText(/邀请码有效期 30 天/)).toBeVisible();
    await expect(page.getByRole("button", { name: "复制邀请码", exact: true })).toBeVisible();
  });

  test("waits locally and sends an unverified visitor to email verification", async ({ page }) => {
    await page.clock.install({ time: new Date("2026-08-23T08:00:00.000Z") });
    let sessionCalls = 0;
    await page.route("**/api/coffee/session", async (route) => {
      sessionCalls += 1;
      await route.abort();
    });

    await page.goto("/");
    await page.getByRole("button", { name: "请作者喝咖啡", exact: true }).click();
    const qrImage = page.getByRole("img", { name: "微信支付收款二维码，收款人 Tt（**添）" });
    await expect.poll(() => qrImage.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true);
    await page.clock.fastForward(32);

    const claimButton = page.getByRole("button", { name: "已请咖啡", exact: true });
    await page.clock.fastForward(4_999);
    await expect(claimButton).toHaveCount(0);
    await page.clock.fastForward(1);
    await expect(claimButton).toBeVisible();
    expect(sessionCalls).toBe(0);

    await claimButton.click();
    await expect(page.getByRole("dialog").getByText("验证邮箱", { exact: true })).toBeVisible();
    expect(sessionCalls).toBe(0);
  });

  test("keeps the merged header actions inside a 320px viewport", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 720 });
    await page.goto("/");

    await expect(page.getByRole("button", { name: "请作者喝咖啡", exact: true })).toBeVisible();
    const moreButton = page.getByRole("button", { name: "更多功能", exact: true });
    await expect(moreButton).toBeVisible();
    await expect(page.getByRole("button", { name: "查看帮助", exact: true })).toHaveCount(0);
    const headerFits = await page.locator(".product-header").evaluate((header) => {
      const viewportWidth = document.documentElement.clientWidth;
      const bounds = [header, ...Array.from(header.children)].map((element) => element.getBoundingClientRect());
      return document.documentElement.scrollWidth <= viewportWidth
        && bounds.every((rect) => rect.left >= -0.5 && rect.right <= viewportWidth + 0.5);
    });
    expect(headerFits).toBe(true);

    await moreButton.click();
    const helpItem = page.getByRole("menuitem", { name: "查看帮助", exact: true });
    await expect(helpItem).toBeVisible();
    await helpItem.click();
    const helpDialog = page.getByRole("dialog");
    await expect(helpDialog.getByText("提醒如何工作", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(helpDialog).toBeHidden();

    await page.getByRole("button", { name: "请作者喝咖啡", exact: true }).click();
    const qrImage = page.getByRole("img", { name: "微信支付收款二维码，收款人 Tt（**添）" });
    await expect(qrImage).toBeVisible();
    const coffeePanelFits = await page.locator(".coffee-panel").evaluate((panel) => {
      const viewportWidth = document.documentElement.clientWidth;
      const selectors = [".coffee-panel", ".coffee-qr-frame", ".coffee-qr-image", ".coffee-waiting"];
      return document.documentElement.scrollWidth <= viewportWidth
        && selectors.every((selector) => {
          const element = panel.closest(".bottom-sheet")?.querySelector(selector);
          if (!element) return false;
          const rect = element.getBoundingClientRect();
          return rect.left >= -0.5 && rect.right <= viewportWidth + 0.5;
        });
    });
    expect(coffeePanelFits).toBe(true);
  });
});
