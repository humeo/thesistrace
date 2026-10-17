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
for (const [width, inset] of [[1280, 32], [1440, 32]] as const) {
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
 await expect(account.locator('.account-trigger-name')).toHaveText('Researcher');
 await expect(account.locator('.account-avatar')).toBeVisible();
 await expect(account).not.toContainText('researcher@example.test');
 await expect(page.locator('.account-menu-panel .account-avatar')).toBeVisible();
 await expect(page.locator('.account-menu-panel')).toContainText('researcher@example.test');
 const trigger=(await account.boundingBox())!; const panel=(await page.locator('.account-menu-panel').boundingBox())!;
 expect(Math.abs(panel.x - trigger.x)).toBeLessThanOrEqual(1); expect(panel.width).toBeGreaterThanOrEqual(trigger.width);
 expect(panel.height).toBeLessThanOrEqual(260);
 expect(panel.y + panel.height).toBeLessThan(trigger.y);
 await page.screenshot({path:testInfo.outputPath('account-card.png'),clip:{x:0,y:panel.y-8,width:240,height:850-panel.y+8}});
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
 await expect(page.getByRole('button',{name:'Account menu'}).locator('.account-trigger-avatar')).toBeVisible();
 await expect(page.getByRole('button',{name:'Account menu'}).locator('.account-trigger-name')).toBeHidden();
 await page.screenshot({path:testInfo.outputPath('account-menu-collapsed.png')});
 await page.keyboard.press('Escape'); await page.getByRole('button',{name:'Expand sidebar',exact:true}).click(); await expect(page.locator('.application-sidebar')).toHaveCSS('width','320px');
 await handle.focus(); await handle.press('ArrowRight'); await expect(handle).toHaveAttribute('aria-valuenow','336');
 await handle.press('End'); await expect(page.locator('.application-sidebar')).toHaveCSS('width','400px');
 await handle.press('Home'); await expect(page.locator('.application-sidebar')).toHaveCSS('width','240px');

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

for (const width of [1200]) {
 test(`interface language changes in place and stays keyboard accessible at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 850 });

  const initialUrl = page.url();
  const sidebarWidth = (await page.locator('.application-sidebar').boundingBox())!.width;
  await page.getByRole('button',{name:'Account menu'}).click();
  const chinese = page.getByRole('button', { name: '简体中文', exact: true });

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

  await page.getByRole('button',{name:'账户菜单'}).click();
  await expect(page.getByRole('button', { name: '简体中文', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'English', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Data', exact: true })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
 });
}

test('shared sidebar keeps its presentation across workspace routes and collapse', async ({ page }) => {
 const presentation = () => page.locator('.application-sidebar').evaluate(sidebar =>
  ['.sidebar-brand-row', '.sidebar-new-chat', '.resource-nav', '.chat-session-region', '.account-trigger'].map(selector => {
   const element = sidebar.querySelector(selector)!;
   const style = getComputedStyle(element);
   return { selector, height: element.getBoundingClientRect().height, padding: style.padding, background: style.backgroundColor, radius: style.borderRadius, font: style.fontFamily };
  }));
 await page.getByRole('link', { name: 'Research', exact: true }).click();
 const reference = await presentation();
 for (const name of ['Data', 'MCP', 'New Chat', 'Research']) {
  await page.getByRole('link', { name, exact: true }).and(page.locator('.sidebar-new-chat, .resource-nav a')).click();
  await page.getByTestId('workspace-content').hover();
  expect(await presentation()).toEqual(reference);
  await expect(page.getByRole('link', { name: 'Quality Alpha', exact: true })).toBeVisible();
 }
 await page.getByRole('button', { name: 'Collapse sidebar', exact: true }).click();
 await expect(page.locator('.application-sidebar')).toHaveCSS('width', '56px');
 await page.getByRole('button', { name: 'Expand sidebar', exact: true }).click();
 await expect(page.locator('.application-sidebar')).toHaveCSS('width', '240px');
 expect(await presentation()).toEqual(reference);
});

test('expanded sidebar aligns brand, navigation, history and compact account identity', async ({ page }) => {
 const positions = await page.locator('.application-sidebar').evaluate(sidebar => {
  const rect = (selector: string) => sidebar.querySelector(selector)!.getBoundingClientRect();
  const historyLink = sidebar.querySelector('.chat-session-row > a')!;
  const navigationLinks = Array.from(sidebar.querySelectorAll('.sidebar-new-chat, .resource-nav:not(.operator-nav) a'));
  return {
   brand: rect('.brand-mark').x,
   navigation: rect('.resource-nav a svg').x,
   historyHeading: rect('.chat-session-heading h3').x,
   historyText: historyLink.getBoundingClientRect().x + parseFloat(getComputedStyle(historyLink).paddingLeft),
   avatar: rect('.account-trigger-avatar').x,
   avatarWidth: rect('.account-trigger-avatar').width,
   accountText: rect('.account-trigger-name').x,
   accountHeight: rect('.account-trigger').height,
   accountNameSize: getComputedStyle(sidebar.querySelector('.account-trigger-name')!).fontSize,
   historyHeadingGap: getComputedStyle(sidebar.querySelector('.chat-session-heading')!).marginBottom,
   navigationGaps: navigationLinks.slice(1).map((link, index) =>
    link.getBoundingClientRect().top - navigationLinks[index]!.getBoundingClientRect().bottom),
  };
 });
 expect(positions.brand).toBe(positions.navigation);
 expect(positions.historyHeading).toBe(positions.navigation);
 expect(positions.historyText).toBe(positions.navigation);
 expect(positions.avatar).toBe(positions.navigation);
 expect(positions.avatarWidth).toBe(24);
 expect(positions.accountText - positions.avatar).toBe(32);
 expect(positions.accountHeight).toBe(40);
 expect(positions.accountNameSize).toBe('14px');
 expect(positions.historyHeadingGap).toBe('4px');
 expect(positions.navigationGaps).toEqual([4, 4, 4, 4, 4]);
});

test('sidebar panel trigger and collapsed navigation share their visual center', async ({ page }, testInfo) => {
 const collapse = page.getByRole('button', { name: 'Collapse sidebar', exact: true });
 const header = (await page.locator('.sidebar-brand-row').boundingBox())!;
 const expandedIcon = (await collapse.locator('svg').boundingBox())!;
 expect(Math.abs(expandedIcon.y + expandedIcon.height / 2 - (header.y + header.height / 2))).toBeLessThanOrEqual(1);
 await collapse.click();
 await expect(page.locator('.application-sidebar')).toHaveCSS('width', '56px');
 const sidebar = (await page.locator('.application-sidebar').boundingBox())!;
 const center = sidebar.x + (sidebar.width - 1) / 2;
 const icons = page.locator('.sidebar-toggle svg, .sidebar-new-chat svg, .resource-nav a svg');
 for (const icon of await icons.all()) {
  const bounds = (await icon.boundingBox())!;
  expect(Math.abs(bounds.x + bounds.width / 2 - center)).toBeLessThanOrEqual(1);
 }
 await page.screenshot({ path: testInfo.outputPath('sidebar-panel-centered.png') });
 await page.getByRole('button', { name: 'Expand sidebar', exact: true }).press('Enter');
 await expect(page.locator('.application-sidebar')).toHaveCSS('width', '240px');
 await expect(collapse).toBeFocused();
});

test('history reveals its new Chat action on hover and focus', async ({ page }) => {
 const heading = page.locator('.chat-session-heading h3');
 const shortcut = page.locator('.chat-session-heading').getByRole('link', { name: 'New Chat', exact: true });
 await expect(heading).toHaveText('Recent');
 await expect(page.locator('.chat-session-row')).toHaveCount(1);
 await expect(page.locator('.chat-session-list')).toHaveCount(1);
 await expect(page.locator('.chat-session-region h3')).toHaveCount(1);
 const headingBox = await heading.boundingBox();
 const shortcutBox = await shortcut.boundingBox();
 expect(shortcutBox!.x).toBeGreaterThan(headingBox!.x + headingBox!.width);
 await page.getByTestId('workspace-content').hover();
 await expect(shortcut).toHaveCSS('opacity', '0');
 await heading.hover();
 await expect(shortcut).toHaveCSS('opacity', '1');
 await shortcut.hover();
 await expect(page.locator('[data-slot="tooltip-content"]')).toHaveText('New Chat');
 await page.getByTestId('workspace-content').hover();
 await expect(page.locator('[data-slot="tooltip-content"]')).toHaveCount(0);
 await shortcut.focus();
 await expect(shortcut).toHaveCSS('opacity', '1');
 await expect(page.locator('[data-slot="tooltip-content"]')).toHaveText('New Chat');
 await shortcut.click();
 await expect(page.getByTestId('workspace-content')).toContainText('/chat');
});

test('sidebar avoids redundant expanded hints and retains one collapsed hint', async ({ page }) => {
 const research = page.getByRole('link', { name: 'Research', exact: true });
 await expect(research).not.toHaveAttribute('title');
 await research.hover();
 await expect(page.locator('[data-slot=tooltip-content]')).toHaveCount(0);
 await expect(research).not.toHaveCSS('background-color', 'rgb(255, 255, 255)');
 const newChat = page.getByRole('link', { name: 'New Chat', exact: true }).filter({ hasText: 'New Chat' });
 await expect(newChat).not.toHaveAttribute('title');
 await expect(newChat).toHaveCSS('box-shadow', 'none');
 await page.getByRole('button', { name: 'Collapse sidebar', exact: true }).click();
 await research.hover();
 await expect(page.locator('[data-slot=tooltip-content]')).toHaveText('Research');
 await expect(page.locator('[data-slot=tooltip-content]')).toHaveCount(1);
});
