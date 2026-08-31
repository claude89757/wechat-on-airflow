import { expect, test } from "@playwright/test";

test("renders the supplied artwork as the shared header logo and favicon", async ({ page }) => {
  await page.goto("/");

  const brandMark = page.locator(".brand-mark");
  await expect(brandMark).toBeVisible();
  const visual = await brandMark.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      backgroundImage: style.backgroundImage,
      borderRadius: style.borderRadius,
    };
  });
  expect(visual.backgroundImage).toContain("/assets/zacks-logo.webp");
  expect(parseFloat(visual.borderRadius)).toBeGreaterThan(0);
  await expect(brandMark.locator("svg")).toHaveCSS("opacity", "0");

  const logoResponse = await page.request.get("/assets/zacks-logo.webp");
  expect(logoResponse.ok()).toBe(true);
  expect(logoResponse.headers()["content-type"]).toContain("image/webp");
  expect((await logoResponse.body()).length).toBeGreaterThan(3_000);

  const favicon = page.locator('link[rel="icon"]');
  await expect(favicon).toHaveAttribute("href", "/assets/zacks-logo.webp");
  await expect(favicon).toHaveAttribute("type", "image/webp");
});
