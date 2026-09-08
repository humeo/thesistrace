import { expect, test } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { fileURLToPath } from 'node:url';
let server: ViteDevServer;
let origin: string;
test.beforeAll(async () => {
  server = await createServer({ root: fileURLToPath(new URL('..', import.meta.url)), server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' });
  await server.listen();
  origin = server.resolvedUrls!.local[0];
});
test.afterAll(async () => { await server?.close(); });
for (const width of [1220, 390]) {
  test(`public landing language, research preview and login at ${width}px`, async ({ page }) => {
    const authRequests: string[] = [];
    await page.route('**/api/**', async route => {
      authRequests.push(route.request().url());
      await route.fulfill({ contentType: 'application/json', body: 'null' });
    });
    await page.setViewportSize({ width, height: 964 });
    await page.goto(origin);
    await expect(page.getByRole('heading', { name: 'Put every hypothesis to the test.' })).toBeVisible();
    expect(authRequests).toEqual([]);
    await page.getByRole('button', { name: 'Keep observing: View example' }).click();
    await expect(page.getByRole('tab', { name: 'Keep observing' })).toHaveAttribute('aria-selected', 'true');
    await page.getByRole('button', { name: '中文', exact: true }).click();
    await expect(page.getByRole('tab', { name: '持续观察' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
    await page.reload();
    await expect(page.getByRole('button', { name: '中文', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await page.getByRole('button', { name: 'English', exact: true }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path: test.info().outputPath(`landing-${width}.png`)});
    await page.getByRole('link', { name: 'Log in', exact: true }).first().click();
    await expect(page.getByRole('heading', { name: 'Get started with QuantTrace' })).toBeVisible();
    await expect(page.getByLabel('Email', { exact: true })).toBeVisible();
  });
}
