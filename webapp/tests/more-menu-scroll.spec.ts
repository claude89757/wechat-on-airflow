import { expect, test } from "@playwright/test";

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
