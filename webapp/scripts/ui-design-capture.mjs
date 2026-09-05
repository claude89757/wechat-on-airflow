import { chromium } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';

// This is a read-only public-browser baseline, with no identity or credentials.
// Writes, email challenges and subscription mutations are blocked at the browser.
const origin = 'https://zacks.claude89757.cc';
const output = '.ui-review';
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const reports = [];
try {
  for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
    const context = await browser.newContext({ viewport: { width, height }, reducedMotion: 'reduce', locale: 'zh-CN', timezoneId: 'Asia/Shanghai' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await context.route('**/*', route => ['GET', 'HEAD', 'OPTIONS'].includes(route.request().method()) ? route.continue() : route.abort('blockedbyclient'));
    const response = await page.goto(origin, { waitUntil: 'networkidle', timeout: 60000 });
    await page.waitForTimeout(2000);
    await page.screenshot({ path: `${output}/${name}.png`, fullPage: true });
    // A compact review copy can be retrieved through text-only GitHub connectors.
    const compact = await page.screenshot({ type: 'jpeg', quality: 18, fullPage: false, scale: 'css' });
    await writeFile(`${output}/${name}.b64`, compact.toString('base64').match(/.{1,120}/g).join('\n'));
    reports.push({ name, source: origin, capturedAt: new Date().toISOString(), status: response.status(), title: await page.title(), errors,
      geometry: await page.evaluate(() => ({ viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth })),
      text: (await page.locator('body').innerText()).replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '[masked email]'),
      buttons: await page.getByRole('button').allTextContents(),
      screenshotBytes: compact.length,
    });
    await context.close();
  }
  await writeFile(`${output}/baseline.json`, JSON.stringify(reports, null, 2));
  console.log(JSON.stringify(reports));
} finally {
  await browser.close();
}
