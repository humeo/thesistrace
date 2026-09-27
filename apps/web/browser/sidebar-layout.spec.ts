import { fontStylesheet, serveBrandAssets } from "./brand-assets";
import { buildProductFixture } from './build-product-fixture';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';
let script: string;
let styles: string;
test.beforeAll(async () => {
 ({ script, styles } = await buildProductFixture(new URL('./fixtures/sidebar.tsx', import.meta.url), 'SidebarFixture',
   [{ name: 'fixture-account', enforce: 'pre', resolveId(source) { if (source === '../auth/AccountMenu') return fileURLToPath(new URL('./fixtures/sidebar-account.tsx', import.meta.url)); } }]));
});
test.beforeEach(async ({page}) => { page.on('pageerror', error => { throw error; }); await page.setViewportSize({width:1200,height:850}); await page.emulateMedia({reducedMotion:'reduce'}); await page.route("http://shell.fixture/**", route => route.fulfill({contentType:"text/html",body:`${fontStylesheet}<style>${styles}</style><div id="root"></div>`})); await serveBrandAssets(page); await page.goto("http://shell.fixture/"); await page.addScriptTag({content:script}); await page.evaluate(() => document.fonts.ready); });
for (const [width, inset] of [[320, 16], [390, 16], [768, 16], [1280, 32], [1440, 32]] as const) {
 test(`Page content uses one workspace inset at ${width}px`, async ({page}) => {
  await page.setViewportSize({width,height:850});
  const main=await page.locator('.main-content').boundingBox();
  const content=await page.getByTestId('workspace-content').boundingBox();
  expect(main).not.toBeNull(); expect(content).not.toBeNull();
  expect(content!.x-main!.x).toBeCloseTo(inset,0);
  expect(main!.width-(content!.x-main!.x)-content!.width).toBeCloseTo(inset,0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
 });
}
test('account popup aligns with its trigger and keeps Discord in keyboard order', async ({page}, testInfo) => {
 const account=page.getByRole('button',{name:'Account menu'}); await account.click();
 await expect(account.locator('.account-avatar')).toBeVisible();
 await expect(account).toContainText('Researcher');
 await expect(account).toContainText('researcher@example.test');
 const trigger=(await account.boundingBox())!; const panel=(await page.locator('.account-menu-panel').boundingBox())!;
 expect(panel.x).toBeCloseTo(trigger.x,0); expect(panel.width).toBeGreaterThanOrEqual(trigger.width);
 expect(panel.y + panel.height).toBeLessThan(trigger.y);
 await page.screenshot({path:testInfo.outputPath('account-card.png'),clip:{x:0,y:panel.y-8,width:224,height:850-panel.y+8}});
 await page.screenshot({path:testInfo.outputPath('account-menu-desktop.png')});
 await account.press('Tab'); await expect(page.getByRole('link',{name:'Join Discord'})).toBeFocused();
 await page.keyboard.press('Tab'); await expect(page.getByRole('button',{name:'Log out'})).toBeFocused();
 await page.keyboard.press('Escape'); await expect(account).toBeFocused();
});
test('sidebar resizes by pointer and keyboard, clamps bounds and retains width across navigation and collapse', async ({page}, testInfo) => {
 const handle=page.getByRole('separator',{name:'Resize sidebar'}); await expect(handle).toBeVisible();
 const box=(await handle.boundingBox())!;
 const sidebarBox=(await page.locator('.application-sidebar').boundingBox())!;
 expect(Math.abs(box.x+box.width/2-(sidebarBox.x+sidebarBox.width))).toBeLessThanOrEqual(2);
 await page.mouse.move(box.x+box.width/2,200); await page.mouse.down(); await page.mouse.move(320,200); await page.mouse.up();
 await expect(page.locator('.application-sidebar')).toHaveCSS('width','320px');
 await expect(page.locator('.application-frame')).toHaveCSS('margin-left','0px');
 await page.getByRole('link',{name:'Data',exact:true}).click(); await expect(page.locator('.application-sidebar')).toHaveCSS('width','320px');
 await page.getByRole('button',{name:'Collapse sidebar',exact:true}).click(); await expect(handle).toBeHidden();
 await expect(page.locator('.application-sidebar')).toHaveCSS('width','56px');
 await page.getByRole('button',{name:'Account menu'}).click(); expect((await page.locator('.account-menu-panel').boundingBox())!.width).toBeGreaterThan(200);
 await expect(page.getByRole('button',{name:'Account menu'}).locator('.account-avatar')).toBeVisible();
 await expect(page.getByRole('button',{name:'Account menu'}).locator('.account-identity-copy')).toBeHidden();
 await page.screenshot({path:testInfo.outputPath('account-menu-collapsed.png')});
 await page.keyboard.press('Escape'); await page.getByRole('button',{name:'Expand sidebar',exact:true}).click(); await expect(page.locator('.application-sidebar')).toHaveCSS('width','320px');
 await handle.focus(); await handle.press('ArrowRight'); await expect(handle).toHaveAttribute('aria-valuenow','336');
 await handle.press('End'); await expect(page.locator('.application-sidebar')).toHaveCSS('width','400px');
 await handle.press('Home'); await expect(page.locator('.application-sidebar')).toHaveCSS('width','224px');
 await page.setViewportSize({width:390,height:844}); await expect(handle).toBeHidden();
 await page.getByRole('button',{name:'Open navigation'}).click(); await page.getByRole('button',{name:'Account menu'}).click();
 const trigger=(await page.getByRole('button',{name:'Account menu'}).boundingBox())!; const panel=(await page.locator('.account-menu-panel').boundingBox())!; expect(panel.width).toBeGreaterThanOrEqual(trigger.width); expect(panel.x+panel.width).toBeLessThanOrEqual(390);
 await expect(page.getByRole('button',{name:'Account menu'}).locator('.account-avatar')).toBeVisible();
 await expect(page.getByRole('button',{name:'Account menu'}).locator('.account-identity-copy')).toBeVisible();
 await page.screenshot({path:testInfo.outputPath('account-menu-mobile.png')});
});

for (const width of [320, 390, 768]) {
 test(`mobile Sheet restores focus after nested Popover closes at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 844 });
  const trigger = page.getByRole('button', { name: 'Open navigation' });
  const triggerBox = await trigger.boundingBox();
  expect(triggerBox?.width).toBeGreaterThanOrEqual(44);
  expect(triggerBox?.height).toBeGreaterThanOrEqual(44);
  await trigger.click();
  const sheet = page.getByRole('dialog', { name: 'Navigation' });
  await expect(sheet).toBeVisible();
  const close = sheet.getByRole('button', { name: 'Close navigation' });
  await expect(close).toBeFocused();
  const closeBox = await close.boundingBox();
  expect(closeBox?.width).toBeGreaterThanOrEqual(44);
  expect(closeBox?.height).toBeGreaterThanOrEqual(44);
  await sheet.getByRole('button', { name: 'Account menu' }).click();
  await expect(page.getByRole('dialog', { name: 'Account menu' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Account menu' })).toBeHidden();
  await expect(sheet).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(sheet).toBeHidden();
  await expect(trigger).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
 });
}

test('mobile Sheet keeps keyboard focus within its navigation', async ({ page }) => {
 await page.setViewportSize({ width: 390, height: 844 });
 await page.getByRole('button', { name: 'Open navigation' }).click();
 const sheet = page.getByRole('dialog', { name: 'Navigation' });
 const home = sheet.getByRole('link', { name: 'Quantgrove home' });
 const close = sheet.getByRole('button', { name: 'Close navigation' });
 const account = sheet.getByRole('button', { name: 'Account menu' });
 await expect(sheet.locator('[data-slot="sheet-close"]')).toHaveCount(0);
 await home.focus();
 await home.press('Shift+Tab');
 await expect(account).toBeFocused();
 await account.press('Tab');
 await expect(home).toBeFocused();
 await expect(close).toBeVisible();
});

test('mobile Sheet closes on Escape from the focused New Chat link', async ({ page }) => {
 await page.setViewportSize({ width: 390, height: 844 });
 const trigger = page.getByRole('button', { name: 'Open navigation' });
 await trigger.click();
 const sheet = page.getByRole('dialog', { name: 'Navigation' });
 const newChat = sheet.getByRole('link', { name: 'New Chat', exact: true });
 await newChat.focus();
 await expect(newChat).toBeFocused();
 await page.keyboard.press('Escape');
 await expect(sheet).toBeHidden();
 await expect(trigger).toBeFocused();
});

test('Escape closes a Chat actions menu while retaining the mobile Sheet', async ({ page }) => {
 await page.setViewportSize({ width: 390, height: 844 });
 await page.getByRole('button', { name: 'Open navigation' }).click();
 const sheet = page.getByRole('dialog', { name: 'Navigation' });
 const actions = sheet.getByRole('button', { name: 'Actions for Quality Alpha' });
 await actions.locator('..').hover();
 await actions.click();
 await expect(page.getByRole('menu', { name: 'Actions for Quality Alpha' })).toBeVisible();
 const backdrop = page.locator('[data-slot="sheet-overlay"]');
 const bounds = await backdrop.boundingBox();
 if (bounds === null) throw new Error('Mobile navigation exposed no backdrop');
 await backdrop.click({ position: { x: bounds.width - 8, y: bounds.height / 2 } });
 await expect(sheet).toBeHidden();
 await page.getByRole('button', { name: 'Open navigation' }).click();
 await actions.locator('..').hover();
 await actions.click();
 await expect(page.getByRole('menu', { name: 'Actions for Quality Alpha' })).toBeVisible();
 await page.keyboard.press('Escape');
 await expect(page.getByRole('menu', { name: 'Actions for Quality Alpha' })).toBeHidden();
 await expect(sheet).toBeVisible();
 await expect(actions).toBeFocused();
});

test('selecting the current interface language saves an entry query preference', async ({ page }) => {
 await page.evaluate(() => localStorage.removeItem('quantgrove.interface-language'));
 await page.goto('http://shell.fixture/?lang=zh');
 await page.addScriptTag({ content: script });
 await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
 await page.getByRole('button', { name: '账户菜单' }).click();
 await page.getByRole('button', { name: '简体中文', exact: true }).click();
 expect(await page.evaluate(() => localStorage.getItem('quantgrove.interface-language'))).toBe('zh-CN');
 await page.goto('http://shell.fixture/data');
 await page.addScriptTag({ content: script });
 await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
});

test('Chat actions remain usable while independent research content scrolls', async ({ page }) => {
 const actions = page.getByRole('button', { name: 'Actions for Quality Alpha' });
 await actions.locator('..').hover();
 await actions.click();
 const menu = page.getByRole('menu', { name: 'Actions for Quality Alpha' });
 await expect(menu).toBeVisible();
 await page.keyboard.press('Escape');
 await expect(menu).toBeHidden();
 await actions.press('ArrowDown');
 await expect(menu).toBeVisible();
 await expect(menu.getByRole('menuitem', { name: 'Rename', exact: true })).toBeFocused();
 await page.keyboard.press('Home');
 await expect(menu.getByRole('menuitem', { name: 'Rename', exact: true })).toBeFocused();
 await page.keyboard.press('ArrowDown');
 await expect(menu.getByRole('menuitem', { name: 'Delete Chat' })).toBeFocused();
 await page.getByLabel('Research content').evaluate(element => { element.scrollTop = 100; });
 await expect.poll(() => page.getByLabel('Research content').evaluate(element => element.scrollTop)).toBe(100);
 await expect(menu).toBeVisible();
 await menu.getByRole('menuitem', { name: 'Delete Chat' }).click();
 await expect(page.getByRole('alertdialog', { name: 'Delete Chat?' })).toBeVisible();
 await page.getByRole('button', { name: 'Cancel', exact: true }).click();
 await expect(actions).toBeFocused();
 await actions.click();
 await expect(menu).toBeVisible();
 await page.getByRole('region', { name: 'Chats', exact: true }).dispatchEvent('scroll');
 await expect(menu).toBeHidden();
 await expect(actions).toBeFocused();
});

test('an open rename dialog keeps its input while the viewport becomes mobile', async ({ page }) => {
 const actions = page.getByRole('button', { name: 'Actions for Quality Alpha' });
 await actions.locator('..').hover();
 await actions.click();
 await page.getByRole('menuitem', { name: 'Rename' }).click();
 const dialog = page.getByRole('dialog', { name: 'Rename Chat' });
 const title = dialog.getByRole('textbox', { name: 'Title' });
 await title.fill('A revised research question');
 await page.setViewportSize({ width: 390, height: 844 });
 await expect(dialog).toBeVisible();
 await expect(title).toHaveValue('A revised research question');
});

for (const width of [1200, 390, 320]) {
 test(`interface language changes in place and stays keyboard accessible at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 850 });
  if (width <= 768) await page.getByRole('button', { name: 'Open navigation' }).click();
  const initialUrl = page.url();
  const sidebarWidth = (await page.locator('.application-sidebar').boundingBox())!.width;
  await page.getByRole('button',{name:'Account menu'}).click();
  const chinese = page.getByRole('button', { name: '简体中文', exact: true });
  if (width <= 768) expect((await chinese.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await chinese.click();
  await expect(chinese).toBeFocused();
  await expect(chinese).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('link', { name: '数据', exact: true })).toBeVisible();
  await expect(page.getByRole('button',{name:'账户菜单'})).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
  expect(page.url()).toBe(initialUrl);
  expect((await page.locator('.application-sidebar').boundingBox())!.width).toBe(sidebarWidth);
  await chinese.press('Escape');
  await expect(page.getByRole('button',{name:'账户菜单'})).toBeFocused();
  await expect(page.getByRole('button',{name:'账户菜单'})).toHaveAttribute('aria-expanded', 'false');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath(`language-zh-${width}.png`) });
  await page.reload();
  await page.addScriptTag({ content: script });
  if (width <= 768) await page.getByRole('button', { name: '打开导航' }).click();
  await page.getByRole('button',{name:'账户菜单'}).click();
  await expect(page.getByRole('button', { name: '简体中文', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'English', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Data', exact: true })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
 });
}
