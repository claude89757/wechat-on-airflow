import { expect, test, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { FALLBACK_DASHBOARD } from "../src/api";

async function fixture(page: Page, verified = false) {
  const dashboard = structuredClone(FALLBACK_DASHBOARD);
  dashboard.generatedAt = new Date().toISOString();
  dashboard.identity.verified = verified;
  let writes = 0;
  await page.route("**/api/**", route => {
    if (route.request().method() !== "GET") { writes += 1; return route.abort("blockedbyclient"); }
    return route.fulfill({ json: dashboard });
  });
  await page.goto("/");
  await expect(page.locator(".venue-card")).toHaveCount(26);
  return () => writes;
}
async function openGroup(page: Page) {
  await page.getByRole("button", { name: "更多功能", exact: true }).click();
  await page.getByRole("menuitem", { name: "添加微信群", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "加入 Zacks 网球群", exact: true });
  await expect(dialog).toBeVisible();
  return dialog;
}

for (const width of [320, 390, 1440]) {
  for (const reducedMotion of ["reduce", "no-preference"] as const) {
    test(`WeChat entry, copy and QR download work at ${width}px/${reducedMotion}`, async ({ page, context }, info) => {
      await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
      await page.emulateMedia({ reducedMotion });
      await context.grantPermissions(["clipboard-read", "clipboard-write"]);
      const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
      const writes = await fixture(page);
      const dialog = await openGroup(page);
      await expect(dialog).toContainText("添加好友，备注「网球群」，获取场地推送与更多资讯。");
      await expect(dialog.getByTestId("wechat-id")).toHaveText("claude89757");
      const image = dialog.getByRole("img");
      await expect.poll(() => image.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth === 656)).toBe(true);
      await expect(image).toBeInViewport({ ratio: 1 });
      const copy = dialog.getByRole("button", { name: "复制微信号", exact: true });
      await copy.click();
      await expect(dialog.getByText("已复制微信号", { exact: true })).toBeVisible();
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("claude89757");
      const downloadPromise = page.waitForEvent("download");
      await dialog.getByRole("link", { name: "保存二维码", exact: true }).click();
      const download = await downloadPromise;
      expect(download.suggestedFilename()).toBe("Zacks-wechat.png");
      const path = await download.path(); expect(path).toBeTruthy();
      expect(createHash("sha256").update(await readFile(path!)).digest("hex")).toBe("45169f938faaa5722d7a560e129804d621f3415b95c0ab27e109ee82a72cd0bd");
      const close = dialog.getByRole("button", { name: "关闭入群说明", exact: true });
      await expect(close).toBeInViewport({ ratio: 1 });
      await page.screenshot({ path: info.outputPath(`wechat-group-${width}-${reducedMotion}.png`) });
      await close.click();
      await expect(dialog).toBeHidden();
      await expect(page.getByRole("button", { name: "更多功能", exact: true })).toBeFocused();
      await openGroup(page);
      await expect(dialog.getByText("已复制微信号", { exact: true })).toHaveCount(0);
      await page.keyboard.press("Escape"); await expect(dialog).toBeHidden();
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
      expect(writes()).toBe(0); expect(errors).toEqual([]);
    });
  }
}

test("clipboard denial has a selectable ID fallback; verified visitors also see the entry", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async () => { throw new Error("denied"); } } }));
  const writes = await fixture(page, true);
  const dialog = await openGroup(page);
  await dialog.getByRole("button", { name: "复制微信号", exact: true }).click();
  await expect(dialog.getByText("请长按微信号复制", { exact: true })).toBeVisible();
  await expect(dialog.getByTestId("wechat-id")).toHaveCSS("user-select", "all");
  expect(writes()).toBe(0);
});

test("QR failure preserves contact details and does not offer a broken download", async ({ page }) => {
  await page.route("**/assets/zacks-wechat-contact.png", route => route.abort());
  const writes = await fixture(page);
  const dialog = await openGroup(page);
  await expect(dialog.getByText("二维码暂未加载，请搜索微信号添加。", { exact: true })).toBeVisible();
  await expect(dialog.getByTestId("wechat-id")).toHaveText("claude89757");
  await expect(dialog.getByRole("link", { name: "保存二维码", exact: true })).toHaveCount(0);
  expect(writes()).toBe(0);
});

test("keyboard navigation opens the entry and backdrop closes the sheet", async ({ page }) => {
  const writes = await fixture(page);
  await page.getByRole("button", { name: "更多功能", exact: true }).focus();
  await page.keyboard.press("Enter");
  const entry = page.getByRole("menuitem", { name: "添加微信群", exact: true });
  await entry.focus(); await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "加入 Zacks 网球群", exact: true });
  await expect(dialog).toBeVisible();
  await page.getByTestId("sheet-overlay").click({ position: { x: 20, y: 20 } });
  await expect(dialog).toBeHidden(); expect(writes()).toBe(0);
});
