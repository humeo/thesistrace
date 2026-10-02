import { expect, test } from "@playwright/test";
import { fontStylesheet, serveBrandAssets } from "./brand-assets";
import { buildProductFixture } from "./build-product-fixture";

let script: string;
let styles: string;
test.beforeAll(async () => {
  ({ script, styles } = await buildProductFixture(new URL("./fixtures/chart-language.tsx", import.meta.url), "ChartLanguageFixture"));
});

for (const variant of ["default", "result"]) test(`${variant} chart language updates keep manually zoomed and panned observations`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1050, height: 800 });
  await serveBrandAssets(page);
  await page.route("https://chart.test/?**", route => route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` }));
  await page.goto(`https://chart.test/?${variant === "result" ? "result" : "default"}`);
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.evaluate(() => document.fonts.ready);
  const chart = page.locator(".strategy-chart-canvas");
  const box = (await chart.boundingBox())!;
  async function observation(x: number) {
    await page.mouse.move(box.x + x, box.y + 100);
    await expect(page.locator(".strategy-chart-readout time")).toBeVisible();
    return { date: await page.locator(".strategy-chart-readout time").getAttribute("datetime"), values: (await page.locator(".strategy-chart-readout").innerText()).match(/[+-]?\d+\.\d{2}%/g) };
  }
  const initial = await observation(200);
  await observation(300);
  await page.mouse.wheel(0, -600);
  await expect.poll(async () => (await observation(200)).date).not.toBe(initial.date);
  await page.mouse.move(box.x + 450, box.y + 150);
  await page.mouse.down();
  await page.mouse.move(box.x + 600, box.y + 150, { steps: 15 });
  await page.mouse.up();
  const before = [await observation(200), await observation(400), await observation(600)];
  await page.getByRole("tab", { name: "Configuration", exact: true }).click();
  await expect(chart).not.toBeVisible();
  await page.getByRole("tab", { name: "Performance", exact: true }).click();
  await expect(chart).toBeVisible();
  expect([await observation(200), await observation(400), await observation(600)]).toEqual(before);
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(page.getByRole("figure", { name: "净策略与沪深300表现图" })).toBeVisible();
  expect([await observation(200), await observation(400), await observation(600)]).toEqual(before);
  await expect(page.locator(".strategy-chart-readout")).toContainText("净策略");
  await page.screenshot({ path: testInfo.outputPath("chart-zh-zoomed.png") });
  await page.getByRole("button", { name: "English", exact: true }).click();
  await expect(page.getByRole("figure", { name: "Net Strategy and CSI 300 performance chart" })).toBeVisible();
  expect([await observation(200), await observation(400), await observation(600)]).toEqual(before);
});

test("an open metric explanation updates without losing its panel or keyboard focus", async ({ page }) => {
  await serveBrandAssets(page);
  await page.route("https://chart.test/", route => route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` }));
  await page.goto("https://chart.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  const help = page.getByRole("button", { name: "About Net Strategy", exact: true });
  await expect(help.locator("svg")).toHaveCSS("width", "12px");
  await help.hover();
  const panel = page.getByRole("dialog");
  await expect(panel).toContainText("after trading costs");
  await help.press("Escape");
  await expect(panel).not.toBeVisible();
  await help.press("Enter");
  await expect(panel).toBeVisible();
  const close = panel.getByRole("button", { name: "Close explanation", exact: true });
  await close.focus();
  // Change the shared locale owner without an outside click that dismisses Base UI Popover.
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("fixture-language", { detail: "zh-CN" })));
  await expect(panel).toContainText("已扣除交易费用");
  await expect(panel.getByRole("button", { name: "关闭说明", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(panel).not.toBeVisible();
});
