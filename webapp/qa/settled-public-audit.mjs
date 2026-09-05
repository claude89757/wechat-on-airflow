import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium, expect } from '@playwright/test';

// Supplement the release's public acceptance. Early screenshots can capture
// an offscreen sheet during its spring entry even when Radix calls it visible.
// Playwright trial clicks prove stable, in-viewport, unobstructed controls
// without submitting a verification request. This is NOT an inbox test.
const expected = '26511a3c56f40f79cf416d8098248ecf4a173eb8';
const origin = 'https://zacks.claude89757.cc';
const output = 'settled-qa-output';
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const report = { expectedWebCommit: expected, source: origin, publicWriteAttempts: 0,
  syntheticNotifications: 0, realEmailVerification: false, views: [], passed: false };
const cases = [
  ['desktop',1440,1000,'reduce'], ['tablet',768,1024,'reduce'],
  ['compact-desktop',900,1000,'reduce'], ['mobile',390,844,'reduce'],
  ['small',320,740,'reduce'], ['mobile-motion',390,844,'no-preference'],
];
try {
  for (const [name,width,height,reducedMotion] of cases) {
    const context = await browser.newContext({ viewport:{width,height}, reducedMotion,
      locale:'zh-CN', timezoneId:'Asia/Shanghai' });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await context.route('**/*', route => {
      if (['GET','HEAD','OPTIONS'].includes(route.request().method())) return route.continue();
      report.publicWriteAttempts += 1;
      return route.abort('blockedbyclient');
    });
    const view = { name,width,height,reducedMotion,passed:false };
    report.views.push(view);
    try {
      const response = await page.goto(origin,{waitUntil:'networkidle',timeout:60000});
      assert.equal(response.status(),200);
      await expect(page.locator('main[data-ui-version="0.8.0"]')).toBeVisible();
      await expect(page.locator('.service-ready')).toBeVisible();
      const identity = await page.evaluate(async () => {
        const read = async path => { const r=await fetch(path); if(!r.ok) throw new Error('Health HTTP '+r.status); return r.json(); };
        return { edge:await read('/api/edge-healthz'),host:await read('/api/healthz') };
      });
      assert.equal(identity.edge.deploymentCommit,expected);
      assert.equal(identity.edge.durableBusinessState,'none');
      assert.equal(identity.edge.legacyRuntime,false);
      assert.equal(identity.host.ok,true);
      assert.equal(identity.host.runtime,'airflow-host');
      await expect(page.locator('.venue-card')).toHaveCount(26);
      const overflow = await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth);
      assert.ok(overflow<=1);
      await page.screenshot({path:`${output}/${name}-home.png`});
      await page.getByTestId('venue-card-tops').click();
      const dialog=page.getByRole('dialog');
      const email=page.getByLabel('订阅邮箱');
      const send=page.getByRole('button',{name:'发送验证码',exact:true});
      await expect(dialog).toBeVisible();
      view.initialSheetTop=(await dialog.boundingBox())?.y;
      assert.equal(await email.evaluate(el=>document.activeElement===el),false);
      await email.click({trial:true});
      await expect(email).toBeInViewport({ratio:1});
      await email.fill('qa-layout@example.invalid');
      await expect(send).toBeEnabled();
      await send.click({trial:true});
      await expect(send).toBeInViewport({ratio:1});
      await expect(dialog).toBeInViewport({ratio:0.99});
      view.sheet=await dialog.boundingBox();
      view.email=await email.boundingBox();
      view.action=await send.boundingBox();
      view.actionHitTest=await send.evaluate(el=>{
        const r=el.getBoundingClientRect();
        return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));
      });
      assert.equal(view.actionHitTest,true);
      await email.fill('');
      await expect(send).toBeDisabled();
      await page.keyboard.press('Tab');
      await page.screenshot({path:`${output}/${name}-verification-settled.png`});
      await page.keyboard.press('Escape');
      await expect(dialog).toBeHidden();
      if(width<900) {
        const nav=page.getByRole('navigation',{name:'快捷导航'});
        await expect(nav).toBeInViewport({ratio:1});
      }
      await page.locator('.more-button').click();
      await page.getByRole('menuitem',{name:'查看帮助',exact:true}).click();
      await expect(page.getByRole('dialog')).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(page.getByRole('dialog')).toBeHidden();
      assert.deepEqual(errors,[]);
      Object.assign(view,{overflow,edgeCommit:identity.edge.deploymentCommit,
        hostCommit:identity.host.deploymentCommit,errors,passed:true});
    } catch(error) {
      view.error=String(error);
      await page.screenshot({path:`${output}/${name}-failure.png`}).catch(()=>{});
      throw error;
    } finally { await context.close(); }
  }
  assert.equal(report.publicWriteAttempts,0);
  report.passed=true;
} finally {
  report.checkedAt=new Date().toISOString();
  await writeFile(`${output}/settled-public-audit.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
  await browser.close();
}
