import { expect, test } from "@playwright/test";

const DESKTOP_VIEWPORT = { width: 1440, height: 960 };
const RECEIPTS_KEY = "zacks-tennis-verified-emails-v1";

test("moving from More into its menu does not drag or rubber-band the page", async ({ page }) => {
  await page.goto("/");

  const scroll = page.getByTestId("mobile-scroll");
  const trigger = page.locator(".more-button");
  await expect(trigger).toHaveAttribute("aria-label", "更多功能");
  const triggerBox = await trigger.boundingBox();
  if (!triggerBox) throw new Error("More trigger has no bounding box");

  await page.mouse.move(
    triggerBox.x + triggerBox.width / 2,
    triggerBox.y + triggerBox.height / 2,
  );
  await page.mouse.down();

  const firstItem = page.getByRole("menuitem", { name: "我的订阅", exact: true });
  await expect(firstItem).toBeVisible();
  const repositoryItem = page.getByRole("menuitem", { name: "项目开源地址", exact: true });
  await expect(repositoryItem).toHaveAttribute(
    "href",
    "https://github.com/claude89757/wechat-on-airflow",
  );
  await expect(repositoryItem).toHaveAttribute("rel", "noopener noreferrer");
  await expect(trigger).toHaveAttribute("data-scroll-drag", "ignore");

  const itemBox = await firstItem.boundingBox();
  if (!itemBox) throw new Error("More menu item has no bounding box");

  await page.mouse.move(
    itemBox.x + itemBox.width / 2,
    itemBox.y + itemBox.height / 2,
    { steps: 8 },
  );

  await expect(scroll).toHaveAttribute("data-dragging", "false");
  expect(Math.abs(Number(await scroll.getAttribute("data-overscroll")))).toBeLessThan(0.01);
  expect(await scroll.evaluate((element) => element.scrollTop)).toBe(0);

  await page.mouse.up();
});

test.describe("desktop workspace presentation", () => {
  test.use({ viewport: DESKTOP_VIEWPORT });

  test("uses the full browser canvas with a supporting task pane", async ({ page }) => {
    await page.goto("/");

    await expect(page.locator("main.dashboard-screen")).toBeVisible();
    await expect(page.locator('link[href="/src/desktop.css"]')).toHaveAttribute("media", "(min-width: 900px)");

    const scaleBox = await page.locator(".phone-scale-box").boundingBox();
    expect(scaleBox?.width ?? 0).toBeGreaterThan(1300);

    const dashboardLayout = await page.locator(".dashboard-screen").evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        display: style.display,
        columns: style.gridTemplateColumns,
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      };
    });
    expect(dashboardLayout.display).toBe("grid");
    expect(dashboardLayout.columns.split(" ").length).toBeGreaterThanOrEqual(2);
    expect(dashboardLayout.overflow).toBeLessThanOrEqual(1);

    const header = page.locator(".product-header");
    await expect(header).toHaveCSS("position", "sticky");

    const metrics = page.locator(".metric");
    await expect(metrics).toHaveCount(3);
    const metricBoxes = await Promise.all([0, 1, 2].map((index) => metrics.nth(index).boundingBox()));
    expect(metricBoxes.every((box) => (box?.width ?? 0) > 260)).toBe(true);
    expect(Math.max(...metricBoxes.map((box) => box?.y ?? 0)) - Math.min(...metricBoxes.map((box) => box?.y ?? 0))).toBeLessThan(2);

    const venueSection = await page.locator(".venue-section").boundingBox();
    const createCard = await page.locator(".create-card").boundingBox();
    expect(venueSection).not.toBeNull();
    expect(createCard).not.toBeNull();
    expect((venueSection?.x ?? 0) + (venueSection?.width ?? 0)).toBeLessThan(createCard?.x ?? 0);
    expect(Math.abs((venueSection?.y ?? 0) - (createCard?.y ?? 0))).toBeLessThan(4);
    await expect(page.locator(".create-card")).toHaveCSS("position", "sticky");

    const venueCards = page.locator(".venue-card");
    expect(await venueCards.count()).toBeGreaterThan(4);
    const firstRow = await Promise.all([0, 1, 2, 3].map((index) => venueCards.nth(index).boundingBox()));
    expect(firstRow.every((box) => (box?.width ?? 0) > 205)).toBe(true);
    expect(Math.max(...firstRow.map((box) => box?.y ?? 0)) - Math.min(...firstRow.map((box) => box?.y ?? 0))).toBeLessThan(2);

    await page.locator(".mobile-scroll").evaluate((element) => {
      element.scrollTop = 520;
      element.dispatchEvent(new Event("scroll"));
    });
    await expect.poll(async () => (await header.boundingBox())?.y ?? 999).toBeLessThan(2);
  });

  test("presents the shared subscription flow as a centered desktop dialog", async ({ page }) => {
    await page.addInitScript(
      ({ key }) => {
        localStorage.setItem(
          key,
          JSON.stringify([
            {
              token: "desktop-ux-test-token",
              email: "desktop@example.com",
              maskedEmail: "d***@example.com",
              verifiedAt: new Date().toISOString(),
            },
          ]),
        );
      },
      { key: RECEIPTS_KEY },
    );

    await page.goto("/");
    await page.locator(".venue-card").first().click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.locator(".subscription-form")).toBeVisible();
    await expect(dialog.locator(".sheet-handle")).toHaveCSS("display", "none");

    await expect.poll(async () => (await dialog.boundingBox())?.width ?? 0).toBeGreaterThanOrEqual(1020);
    await expect.poll(async () => (await dialog.boundingBox())?.y ?? 999).toBeLessThan(120);
    const dialogBox = await dialog.boundingBox();
    expect(dialogBox?.x ?? 0).toBeGreaterThanOrEqual(30);
    expect(dialogBox?.y ?? 0).toBeGreaterThanOrEqual(30);
    expect((dialogBox?.x ?? 0) + (dialogBox?.width ?? 0)).toBeLessThanOrEqual(DESKTOP_VIEWPORT.width - 30);
    expect((dialogBox?.y ?? 0) + (dialogBox?.height ?? 0)).toBeLessThanOrEqual(DESKTOP_VIEWPORT.height - 20);

    const overlayPosition = await page.locator(".sheet-overlay").evaluate((element) => getComputedStyle(element).position);
    expect(overlayPosition).toBe("fixed");

    const formLayout = await dialog.locator(".subscription-form").evaluate((element) => {
      const style = getComputedStyle(element);
      return { display: style.display, columns: style.gridTemplateColumns };
    });
    expect(formLayout.display).toBe("grid");
    expect(formLayout.columns.split(" ").length).toBe(2);

    await dialog.getByRole("button", { name: "添加其他场地", exact: true }).click();
    await expect(dialog.locator(".venue-choices")).toBeVisible();
    const venueChoiceColumns = await dialog.locator(".venue-choices").evaluate((element) =>
      getComputedStyle(element).gridTemplateColumns.split(" ").length,
    );
    expect(venueChoiceColumns).toBe(3);

    const firstChoice = dialog.locator(".venue-choices button").first();
    await firstChoice.focus();
    const focusVisible = await firstChoice.evaluate((element) => {
      const style = getComputedStyle(element);
      return (style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0)
        || style.boxShadow !== "none";
    });
    expect(focusVisible).toBe(true);

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });

  test("activates the desktop layer only at the desktop breakpoint", async ({ page }) => {
    await page.setViewportSize({ width: 899, height: 800 });
    await page.goto("/");
    const compactWidth = (await page.locator(".phone-scale-box").boundingBox())?.width ?? 0;
    expect(compactWidth).toBeLessThanOrEqual(521);

    await page.setViewportSize({ width: 900, height: 800 });
    await expect.poll(async () => (await page.locator(".phone-scale-box").boundingBox())?.width ?? 0).toBeGreaterThan(850);

    const desktopStylesActive = await page.locator(".dashboard-screen").evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        width: parseFloat(style.width),
        paddingTop: parseFloat(style.paddingTop),
      };
    });
    expect(desktopStylesActive.width).toBeGreaterThan(800);
    expect(desktopStylesActive.paddingTop).toBe(0);
  });
});
