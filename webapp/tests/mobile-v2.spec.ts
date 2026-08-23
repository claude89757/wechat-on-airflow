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

    const helpButton = await page.locator(".icon-button").boundingBox();
    expect(helpButton?.width ?? 0).toBeGreaterThanOrEqual(44);
    expect(helpButton?.height ?? 0).toBeGreaterThanOrEqual(44);

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

    const submitButton = page.locator(".subscription-form .sheet-primary");
    await expect(submitButton).toHaveCSS("position", "sticky");
    const submitBox = await submitButton.boundingBox();
    expect(submitBox?.height ?? 0).toBeGreaterThanOrEqual(52);
  });
});
