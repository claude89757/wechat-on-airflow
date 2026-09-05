import { expect, test } from "@playwright/test";
import { FALLBACK_DASHBOARD } from "../src/api";

for (const width of [320, 390, 1440]) {
  for (const reducedMotion of ["reduce", "no-preference"] as const) {
    test(`verification controls are visible and actionable at ${width}px with ${reducedMotion}`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: width === 320 ? 740 : 844 });
      await page.emulateMedia({ reducedMotion });
      let writes = 0;
      const dashboard = structuredClone(FALLBACK_DASHBOARD);
      dashboard.generatedAt = new Date().toISOString();
      await page.route("**/api/**", async route => {
        if (route.request().method() !== "GET") {
          writes += 1;
          return route.abort("blockedbyclient");
        }
        return route.fulfill({ json: dashboard });
      });
      await page.goto("/");
      await page.getByTestId("venue-card-tops").click();
      const dialog = page.getByRole("dialog");
      const email = dialog.getByLabel("订阅邮箱");
      const send = dialog.getByRole("button", { name: "发送验证码", exact: true });
      await expect(email).toBeInViewport({ ratio: 1 });
      await email.click({ trial: true });
      await expect(email).not.toBeFocused();
      await send.scrollIntoViewIfNeeded();
      await expect(send).toBeInViewport({ ratio: 1 });
      await expect(send).toBeDisabled();
      await email.fill("ui-acceptance@example.invalid");
      await expect(send).toBeEnabled();
      await send.click({ trial: true });
      await email.fill("");
      await email.blur();
      await expect(send).toBeDisabled();
      await expect(email).toBeInViewport({ ratio: 1 });
      await expect(send).toBeInViewport({ ratio: 1 });
      await page.screenshot({ path: info.outputPath("stable-verification.png") });
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      expect(writes).toBe(0);
    });
  }
}
