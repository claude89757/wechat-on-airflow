import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from '@playwright/test';

const expected = process.argv[2];
assert.match(expected ?? '', /^[0-9a-f]{40}$/, 'exact Web deployment SHA is required');
const origin = 'https://zacks.claude89757.cc';
const output = 'qa-output';
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const report = { expectedCommit: expected, uiVersion: '0.8.0', publicWriteRequests: 0, syntheticNotifications: 0, views: [], passed: false };
try {
  for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844], ['small', 320, 740]]) {
    const context = await browser.newContext({ viewport: { width, height }, reducedMotion: 'reduce', locale: 'zh-CN', timezoneId: 'Asia/Shanghai' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await context.route('**/*', route => {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(route.request().method())) {
        report.publicWriteRequests += 1;
        return route.abort('blockedbyclient');
      }
      return route.continue();
    });
    const response = await page.goto(origin, { waitUntil: 'networkidle', timeout: 60000 });
    assert.equal(response.status(), 200);
    await page.locator('main[data-ui-version="0.8.0"]').waitFor();
    await page.locator('.service-ready').waitFor({timeout:30000});
    const health = await page.evaluate(async () => {
      const read = async path => { const response = await fetch(path); if (!response.ok) throw new Error('read-only health failed: ' + response.status); return response.json(); };
      return { host: await read('/api/healthz'), edge: await read('/api/edge-healthz') };
    });
    assert.equal(health.edge.deploymentCommit, expected);
    assert.equal(health.edge.durableBusinessState, 'none');
    assert.equal(health.edge.legacyRuntime, false);
    assert.equal(health.host.ok, true);
    assert.equal(health.host.runtime, 'airflow-host');
    assert.equal(await page.locator('.venue-card').count(), 26);
    assert.equal(await page.locator('.phone-device-picker:visible').count(), 0);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    assert.ok(overflow <= 1);
    await page.screenshot({ path: `${output}/${name}-home.png` });
    if (width < 900) {
      const nav = page.getByRole('navigation', { name: '快捷导航' });
      const box = await nav.boundingBox(); assert.ok(box && box.y >= 0 && box.y + box.height <= height + 1);
    }
    await page.getByLabel('搜索场地').fill('前海');
    await page.waitForTimeout(100);
    assert.equal(await page.locator('.venue-card').count(), 1);
    await page.getByLabel('搜索场地').fill('no-such-court-studio-acceptance');
    await page.getByText('没有找到这个场地', { exact: true }).waitFor();
    await page.getByRole('button', { name: '查看全部场地', exact: true }).click();
    assert.equal(await page.locator('.venue-card').count(), 26);
    await page.getByTestId('venue-card-tops').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${output}/${name}-directory.png` });
    await page.getByTestId('venue-card-tops').click();
    const dialog = page.getByRole('dialog'); await dialog.waitFor();
    assert.ok(await dialog.innerText().then(text => text.includes('TOPS 科技园')));
    assert.equal(await page.getByLabel('订阅邮箱').evaluate(el => document.activeElement === el), false);
    assert.equal(await page.getByRole('button', { name: '发送验证码', exact: true }).isDisabled(), true);
    await page.screenshot({ path: `${output}/${name}-verification.png` });
    await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'hidden' });
    await page.locator('.more-button').click();
    const repository = page.getByRole('menuitem', { name: '项目开源地址', exact: true });
    assert.equal(await repository.getAttribute('rel'), 'noopener noreferrer');
    assert.equal(await page.getByRole('menuitem', { name: '管理后台', exact: true }).count(), 0);
    await page.getByRole('menuitem', { name: '查看帮助', exact: true }).click();
    await page.getByRole('dialog').getByText('提醒如何工作', { exact: true }).waitFor();
    await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
    assert.deepEqual(errors, []);
    report.views.push({ name, width, height, overflow, cards: 26, hostCommit: health.host.deploymentCommit, edgeCommit: health.edge.deploymentCommit, errors, passed: true });
    await context.close();
  }
  assert.equal(report.publicWriteRequests, 0, 'public acceptance must never attempt a write');
  report.passed = true;
} finally {
  report.checkedAt = new Date().toISOString();
  await writeFile(`${output}/public-acceptance.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
  await browser.close();
}
