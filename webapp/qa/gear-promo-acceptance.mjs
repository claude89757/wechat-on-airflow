import assert from 'node:assert/strict';
import { expect } from '@playwright/test';
import { acceptanceRequestPolicy } from './public-request-policy.mjs';

const storageKey = 'zacks:gear-promo:2026-11:seen-v2';

// Install before the first navigation so slow page loads cannot hide a premature
// dismissal. These observations never modify application state or send requests.
export async function observeGearPromo(page) {
  await page.addInitScript(() => {
    const observation = { events: [], automaticFocused: false };
    window.__gearPromoAcceptance = observation;
    let previous = null;
    const record = () => {
      const card = document.querySelector('[data-testid="gear-promo"]');
      const mode = card?.getAttribute('data-mode') ?? null;
      if (mode !== previous) observation.events.push({ mode, at: performance.now(), epoch: Date.now() });
      if (mode === 'auto' && card.contains(document.activeElement)) observation.automaticFocused = true;
      previous = mode;
    };
    new MutationObserver(record).observe(document, {
      childList: true, subtree: true, attributes: true, attributeFilter: ['data-mode'],
    });
    document.addEventListener('focusin', record);
  });
}

export async function verifyAutomaticGearPromo(page, { output, name }) {
  const read = () => page.evaluate(() => window.__gearPromoAcceptance);
  await expect.poll(async () => (await read()).events.some(event => event.mode === 'auto'), {
    timeout: 12_000, message: 'An idle new visitor should see one product recommendation',
  }).toBe(true);
  const promo = page.getByTestId('gear-promo');
  if (await promo.isVisible()) await page.screenshot({ path: `${output}/${name}-gear-auto.png` });
  await expect.poll(async () => {
    const events = (await read()).events;
    const appeared = events.find(event => event.mode === 'auto');
    return events.some(event => event.mode === null && event.at > appeared.at);
  }, { timeout: 8_000, message: 'Automatic recommendation must close without user interaction' }).toBe(true);
  const observation = await read();
  const appeared = observation.events.find(event => event.mode === 'auto');
  const dismissed = observation.events.find(event => event.mode === null && event.at > appeared.at);
  const visibleMs = dismissed.at - appeared.at;
  assert.ok(visibleMs >= 4_800 && visibleMs < 6_500, `automatic DOM lifetime should be 5s, observed ${visibleMs}ms`);
  assert.equal(observation.automaticFocused, false, 'automatic advertising must not move keyboard focus');
  await expect(promo).toBeHidden();
  const recordedAt = Number(await page.evaluate(key => localStorage.getItem(key), storageKey));
  assert.ok(Number.isFinite(recordedAt) && Math.abs(recordedAt - dismissed.epoch) < 1_000, 'persist only after a complete five-second display');

  await page.reload({ waitUntil: 'networkidle' });
  await page.locator('.service-ready').waitFor({ timeout: 30_000 });
  // Existing business-flow checks run during this cooldown observation window.
  return { visibleMs: Math.round(visibleMs), automaticFocused: false, recordedAt, reloadedAt: Date.now() };
}

// Exercise the deployed production bundle, where a first visit has no dashboard
// yet. The development server starts with fallback data and cannot expose this
// dependency. Only this isolated browser's bootstrap response is held/failed.
export async function verifyMobileFirstVisitGearPromo(browser, { origin, output }) {
  const name = `${new URL(origin).hostname}-mobile-first-visit`;
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
    reducedMotion: 'no-preference', locale: 'zh-CN', timezoneId: 'Asia/Shanghai',
  });
  let releaseBootstrap;
  const bootstrapGate = new Promise(resolve => { releaseBootstrap = resolve; });
  let bootstrapRequested = false;
  let bootstrapReleased = false;
  let publicWriteRequests = 0;
  let blockedTelemetryRequests = 0;
  await context.route('**/*', async route => {
    const request = route.request();
    const policy = acceptanceRequestPolicy(request.method(), request.url(), origin);
    if (policy !== 'read') {
      if (policy === 'blocked-cloudflare-telemetry') blockedTelemetryRequests += 1;
      else publicWriteRequests += 1;
      return route.abort('blockedbyclient');
    }
    if (new URL(request.url()).origin === origin && new URL(request.url()).pathname === '/api/bootstrap') {
      bootstrapRequested = true;
      await bootstrapGate;
      // A simulated read failure must not create a subscription or notification.
      return route.fulfill({ status: 503, json: { error: 'Isolated acceptance: dashboard unavailable' } });
    }
    return route.continue();
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await observeGearPromo(page);
  try {
    await page.goto(origin, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await page.locator('main[data-ui-version="0.8.0"]').waitFor();
    const startedAt = Date.now();
    const promo = page.getByTestId('gear-promo');
    const scroller = page.getByTestId('mobile-scroll');
    const touch = await context.newCDPSession(page);
    let captured = false;
    let swipes = 0;
    let maxScrollTop = 0;
    let appeared;
    let dismissed;
    // Real touch input keeps browsing active before and during the promotion.
    // The gesture stays above the fixed promotion and never activates a CTA.
    while (Date.now() - startedAt < 12_000) {
      const from = swipes % 2 === 0 ? 320 : 180;
      const to = swipes % 2 === 0 ? 180 : 320;
      await touch.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: 30, y: from }] });
      for (let step = 1; step <= 6; step += 1) {
        await touch.send('Input.dispatchTouchEvent', {
          type: 'touchMove', touchPoints: [{ x: 30, y: from + (to - from) * step / 6 }],
        });
        await page.waitForTimeout(24);
      }
      await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
      swipes += 1;
      maxScrollTop = Math.max(maxScrollTop, await scroller.evaluate(element => element.scrollTop));
      const observation = await page.evaluate(() => window.__gearPromoAcceptance);
      appeared = observation.events.find(event => event.mode === 'auto');
      dismissed = appeared && observation.events.find(event => event.mode === null && event.at > appeared.at);
      if (appeared && !captured) {
        await expect(promo).toBeVisible();
        await expect(promo).toBeInViewport({ ratio: 1 });
        await expect(promo).toHaveCSS('opacity', '1');
        assert.equal(await page.evaluate(key => localStorage.getItem(key), storageKey), null,
          'a first appearance must not consume the cooldown before five seconds of viewing');
        await page.screenshot({ path: `${output}/${name}-gear-auto.png` });
        captured = true;
      }
      if (dismissed) break;
      await page.waitForTimeout(150);
    }
    assert.equal(bootstrapRequested, true, 'the production first visit must request its dashboard');
    assert.equal(bootstrapReleased, false);
    assert.ok(appeared && dismissed, 'an active first-time mobile visitor must see the ad while dashboard loading is pending');
    assert.ok(maxScrollTop > 0 && swipes > 3, 'touch gestures must actually scroll the page');
    const visibleMs = dismissed.at - appeared.at;
    assert.ok(visibleMs >= 4_800 && visibleMs < 6_500, `touch scrolling must preserve the full five seconds, observed ${visibleMs}ms`);
    const recordedAt = Number(await page.evaluate(key => localStorage.getItem(key), storageKey));
    assert.ok(Math.abs(recordedAt - dismissed.epoch) < 1_000, 'only the completed impression starts the cooldown');
    const observation = await page.evaluate(() => window.__gearPromoAcceptance);
    assert.equal(observation.automaticFocused, false);
    await expect(promo).toBeHidden();
    const failedBootstrap = page.waitForResponse(response =>
      new URL(response.url()).pathname === '/api/bootstrap' && response.status() === 503);
    bootstrapReleased = true;
    releaseBootstrap();
    await failedBootstrap;
    await expect(page.getByRole('button', { name: '更多功能', exact: true })).toBeVisible();
    assert.equal(publicWriteRequests, 0);
    assert.deepEqual(errors, []);
    return {
      origin, width: 390, height: 844, touchContext: true, swipes, maxScrollTop,
      appearedBeforeDashboardResponse: true, cooldownAfterCompleteView: true,
      automaticVisibleMs: Math.round(visibleMs), automaticFocused: false,
      dashboardFailureHandled: true, publicWriteRequests, blockedTelemetryRequests, passed: true,
    };
  } finally {
    releaseBootstrap();
    await context.close();
  }
}

export async function verifyManualGearPromo(page, { output, name, width, height, automatic, prolonged = false }) {
  const remainingObservation = 4_500 - (Date.now() - automatic.reloadedAt);
  if (remainingObservation > 0) await page.waitForTimeout(remainingObservation);
  const automaticRepeats = await page.evaluate(() => window.__gearPromoAcceptance.events.filter(event => event.mode === 'auto').length);
  assert.equal(automaticRepeats, 0, 'refreshing within 24h must not repeat automatic advertising');
  assert.equal(Number(await page.evaluate(key => localStorage.getItem(key), storageKey)), automatic.recordedAt);
  const more = page.getByRole('button', { name: '更多功能', exact: true });
  const open = async () => {
    await more.focus();
    await page.keyboard.press('Enter');
    await page.getByRole('menuitem', { name: '球友好物', exact: true }).focus();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('gear-promo')).toHaveAttribute('data-mode', 'manual');
  };
  await open();
  const promo = page.getByTestId('gear-promo');
  await expect(promo).toBeVisible();
  await expect(promo).toHaveAttribute('aria-modal', 'false');
  await expect(promo).toContainText('Wilson 网球包');
  await expect(promo).toContainText('Wilson 网球帽');
  await expect(promo).toContainText(/¥\s*860/);
  await expect(promo).toContainText(/¥\s*300/);
  await expect(promo).toContainText('深圳南山自提');
  await expect(promo.getByTestId('gear-promo-wechat')).toHaveText('thanks0');
  const images = promo.getByRole('img');
  await expect(images).toHaveCount(2);
  assert.deepEqual(await images.evaluateAll(elements => elements.map(element => element.getAttribute('src'))), [
    '/assets/promos/wilson-tennis-bag.webp', '/assets/promos/wilson-tennis-cap.webp',
  ]);
  await expect.poll(() => images.evaluateAll(elements => elements.every(image => image.complete && image.naturalWidth > 0))).toBe(true);
  await expect(promo).toBeInViewport({ ratio: 1 });
  const box = await promo.boundingBox();
  assert.ok(box && box.x >= -1 && box.y >= -1 && box.x + box.width <= width + 1 && box.y + box.height <= height + 1);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth) <= 1);
  if (width < 900) {
    const nav = page.getByRole('navigation', { name: '快捷导航', exact: true });
    await expect(nav).toBeInViewport({ ratio: 1 });
    const navBox = await nav.boundingBox();
    assert.ok(navBox && box.y + box.height <= navBox.y + 1, 'advertising must leave mobile navigation clear');
  }
  const close = promo.getByRole('button', { name: '关闭商品推荐', exact: true });
  const copy = promo.getByRole('button', { name: '复制微信号', exact: true });
  await expect(close).toBeInViewport({ ratio: 1 });
  await expect(copy).toBeInViewport({ ratio: 1 });
  await copy.click();
  await expect(promo.getByRole('status')).toContainText('已复制');
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), 'thanks0');
  // One representative view verifies the separate manual lifetime; all six views
  // verify opening, exact content, images, layout, copying and keyboard dismissal.
  if (prolonged) {
    await page.waitForTimeout(5_200);
    await expect(promo).toBeVisible();
  }
  await page.screenshot({ path: `${output}/${name}-gear-manual.png` });
  await page.keyboard.press('Escape');
  await expect(promo).toBeHidden();
  await expect(more).toBeFocused();
  if (prolonged) {
    await open();
    await page.getByRole('button', { name: '设置我的提醒', exact: true }).click();
    const verification = page.getByRole('dialog', { name: '验证邮箱', exact: true });
    await expect(verification).toBeVisible();
    await expect(promo).toBeHidden();
    await page.keyboard.press('Escape');
    await expect(verification).toBeHidden();
  }
  return {
    automaticVisibleMs: automatic.visibleMs, automaticFocused: false,
    cooldownTimestamp: new Date(automatic.recordedAt).toISOString(), noRepeatAfterReload: true,
    productsAndPrices: true, imagesLoaded: true, copyWechat: 'thanks0',
    controlsInViewport: true, mobileNavigationClear: width < 900 ? true : null,
    manualBeyondFiveSeconds: prolonged ? true : null, businessPanelPrecedence: prolonged ? true : null,
    keyboardDismissal: true,
  };
}
