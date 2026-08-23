import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";

const baseUrl = process.env.MOBILE_UI_BASE_URL ?? "http://127.0.0.1:4174";
const outputDirectory = "qa/mobile-v2-ci";
const receipt = {
  token: "mobile-v2-visual-test-token",
  email: "mobile@example.com",
  maskedEmail: "m***@example.com",
  verifiedAt: new Date().toISOString(),
};

await mkdir(outputDirectory, { recursive: true });

const browser = await chromium.launch({ headless: true });

async function settle(page) {
  await page.waitForSelector("main.dashboard-screen", { state: "visible" });
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  await page.waitForTimeout(700);
}

async function captureHome({ width, height, name }) {
  const context = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await settle(page);
  await page.screenshot({ path: `${outputDirectory}/${name}.png` });
  await context.close();
}

await captureHome({ width: 393, height: 852, name: "01-home-393x852" });
await captureHome({ width: 320, height: 700, name: "02-home-320x700" });

const verifiedContext = await browser.newContext({
  viewport: { width: 393, height: 852 },
  deviceScaleFactor: 1,
  reducedMotion: "reduce",
});
await verifiedContext.addInitScript((savedReceipt) => {
  localStorage.setItem("zacks-tennis-verified-emails-v1", JSON.stringify([savedReceipt]));
}, receipt);

const verifiedPage = await verifiedContext.newPage();
await verifiedPage.goto(baseUrl, { waitUntil: "domcontentloaded" });
await settle(verifiedPage);
await verifiedPage.screenshot({ path: `${outputDirectory}/03-verified-home-393x852.png` });

await verifiedPage.locator(".primary-button").click();
await verifiedPage.locator(".subscription-form").waitFor({ state: "visible" });
await verifiedPage.waitForTimeout(350);
await verifiedPage.screenshot({ path: `${outputDirectory}/04-create-sheet-top-393x852.png` });

await verifiedPage.locator(".sheet-content").evaluate((element) => {
  element.scrollTop = element.scrollHeight;
});
await verifiedPage.waitForTimeout(250);
await verifiedPage.screenshot({ path: `${outputDirectory}/05-create-sheet-bottom-393x852.png` });

await verifiedContext.close();
await browser.close();
