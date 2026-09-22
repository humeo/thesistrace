import { fontStylesheet, serveBrandAssets } from "./brand-assets";
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';
import { build } from 'vite';
let script: string;
const styles = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');
test.beforeAll(async () => {
 const result = await build({ configFile: false, logLevel: 'silent', esbuild: { jsx: 'automatic' },
 plugins: [{ name: 'fixture-account', enforce: 'pre', resolveId(source) { if (source === '../auth/AccountMenu') return fileURLToPath(new URL('./fixtures/sidebar-account.tsx', import.meta.url)); } }],
 define: { 'process.env.NODE_ENV': JSON.stringify('production') }, build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/sidebar.tsx', import.meta.url)), formats: ['iife'], name: 'SidebarFixture' } } });
 if ('on' in result) throw new Error('Expected one-off build');
 const chunk = (Array.isArray(result) ? result : [result]).flatMap(b => b.output).find(o => o.type === 'chunk' && o.isEntry);
 if (chunk?.type !== 'chunk') throw new Error('Missing entry'); script = chunk.code;
});
test.beforeEach(async ({page}) => { page.on('pageerror', error => { throw error; }); await page.setViewportSize({width:1200,height:850}); await page.emulateMedia({reducedMotion:'reduce'}); await page.route("http://shell.fixture/**", route => route.fulfill({contentType:"text/html",body:`${fontStylesheet}<style>${styles}</style><div id="root"></div>`})); await serveBrandAssets(page); await page.goto("http://shell.fixture/"); await page.addScriptTag({content:script}); await page.evaluate(() => document.fonts.ready); });
test('account popup aligns with its trigger and keeps Discord in keyboard order', async ({page}, testInfo) => {
 const account=page.getByLabel('Account menu'); await account.click();
 await expect(account.locator('.account-avatar')).toBeVisible();
 await expect(account).toContainText('Researcher');
 await expect(account).toContainText('researcher@example.test');
 const trigger=(await account.boundingBox())!; const panel=(await page.locator('.account-menu-panel').boundingBox())!;
 expect(panel.x).toBeCloseTo(trigger.x,0); expect(panel.width).toBeCloseTo(trigger.width,0);
 expect(panel.y + panel.height).toBeLessThan(trigger.y);
 await page.screenshot({path:testInfo.outputPath('account-card.png'),clip:{x:0,y:panel.y-8,width:224,height:850-panel.y+8}});
 await page.screenshot({path:testInfo.outputPath('account-menu-desktop.png')});
 await account.press('Tab'); await expect(page.getByRole('link',{name:'Join Discord'})).toBeFocused();
 await page.keyboard.press('Tab'); await expect(page.getByRole('button',{name:'Log out'})).toBeFocused();
 await page.keyboard.press('Escape'); await expect(account).toBeFocused();
});
test('sidebar resizes by pointer and keyboard, clamps bounds and retains width across navigation and collapse', async ({page}, testInfo) => {
 const handle=page.getByRole('separator',{name:'Resize sidebar'}); await expect(handle).toBeVisible();
 const box=(await handle.boundingBox())!; await page.mouse.move(box.x+box.width/2,200); await page.mouse.down(); await page.mouse.move(320,200); await page.mouse.up();
 await expect(page.locator('.application-sidebar')).toHaveCSS('width','320px');
 await expect(page.locator('.application-frame')).toHaveCSS('margin-left','320px');
 await page.getByRole('link',{name:'Data',exact:true}).click(); await expect(page.locator('.application-sidebar')).toHaveCSS('width','320px');
 await page.getByRole('button',{name:'Collapse sidebar',exact:true}).click(); await expect(handle).toBeHidden();
 await page.getByLabel('Account menu').click(); expect((await page.locator('.account-menu-panel').boundingBox())!.width).toBeGreaterThan(200);
 await expect(page.getByLabel('Account menu').locator('.account-avatar')).toBeVisible();
 await expect(page.getByLabel('Account menu').locator('.account-identity-copy')).toBeHidden();
 await page.screenshot({path:testInfo.outputPath('account-menu-collapsed.png')});
 await page.getByLabel('Account menu').press('Escape'); await page.getByRole('button',{name:'Expand sidebar',exact:true}).click(); await expect(page.locator('.application-sidebar')).toHaveCSS('width','320px');
 await handle.focus(); await handle.press('ArrowRight'); await expect(handle).toHaveAttribute('aria-valuenow','336');
 await handle.press('End'); await expect(page.locator('.application-sidebar')).toHaveCSS('width','400px');
 await handle.press('Home'); await expect(page.locator('.application-sidebar')).toHaveCSS('width','224px');
 await page.setViewportSize({width:390,height:844}); await expect(handle).toBeHidden();
 await page.getByRole('button',{name:'Open navigation'}).click(); await page.getByLabel('Account menu').click();
 const trigger=(await page.getByLabel('Account menu').boundingBox())!; const panel=(await page.locator('.account-menu-panel').boundingBox())!; expect(panel.width).toBeCloseTo(trigger.width,0); expect(panel.x+panel.width).toBeLessThan(390);
 await expect(page.getByLabel('Account menu').locator('.account-avatar')).toBeVisible();
 await expect(page.getByLabel('Account menu').locator('.account-identity-copy')).toBeVisible();
 await page.screenshot({path:testInfo.outputPath('account-menu-mobile.png')});
});

test('Chat actions remain usable while independent research content scrolls', async ({ page }) => {
 const actions = page.getByRole('button', { name: 'Actions for Quality Alpha' });
 await actions.locator('..').hover();
 await actions.click();
 const menu = page.getByRole('menu', { name: 'Actions for Quality Alpha' });
 await expect(menu).toBeVisible();
 await page.getByLabel('Research content').evaluate(element => { element.scrollTop = 100; });
 await expect.poll(() => page.getByLabel('Research content').evaluate(element => element.scrollTop)).toBe(100);
 await expect(menu).toBeVisible();
 await menu.getByRole('menuitem', { name: 'Delete Chat' }).click();
 await expect(page.getByRole('dialog', { name: 'Delete Chat?' })).toBeVisible();
 await page.getByRole('button', { name: 'Cancel', exact: true }).click();
 await actions.click();
 await page.getByRole('region', { name: 'Chats', exact: true }).dispatchEvent('scroll');
 await expect(menu).toBeHidden();
 await expect(actions).toBeFocused();
});

for (const width of [1200, 390, 320]) {
 test(`interface language changes in place and stays keyboard accessible at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 850 });
  if (width < 768) await page.getByRole('button', { name: 'Open navigation' }).click();
  const initialUrl = page.url();
  const sidebarWidth = (await page.locator('.application-sidebar').boundingBox())!.width;
  await page.getByLabel('Account menu').click();
  const chinese = page.getByRole('button', { name: '简体中文', exact: true });
  if (width < 768) expect((await chinese.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await chinese.click();
  await expect(chinese).toBeFocused();
  await expect(chinese).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('link', { name: '数据', exact: true })).toBeVisible();
  await expect(page.getByLabel('账户菜单')).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
  expect(page.url()).toBe(initialUrl);
  expect((await page.locator('.application-sidebar').boundingBox())!.width).toBe(sidebarWidth);
  await chinese.press('Tab');
  await expect(page.getByLabel('账户菜单')).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(chinese).toBeFocused();
  await chinese.press('Escape');
  await expect(page.getByLabel('账户菜单')).toBeFocused();
  await expect(page.getByLabel('账户菜单')).toHaveAttribute('aria-expanded', 'false');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath(`language-zh-${width}.png`) });
  await page.reload();
  await page.addScriptTag({ content: script });
  if (width < 768) await page.getByRole('button', { name: '打开导航' }).click();
  await page.getByLabel('账户菜单').click();
  await expect(page.getByRole('button', { name: '简体中文', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'English', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Data', exact: true })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
 });
}
