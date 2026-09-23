import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { build } from "vite";
import { fontStylesheet, serveBrandAssets } from "./brand-assets";

let script: string;
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
test.beforeAll(async () => {
  const result = await build({ configFile: false, logLevel: "silent", esbuild: { jsx: "automatic" },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL("./fixtures/chart-language.tsx", import.meta.url)), formats: ["iife"], name: "ChartLanguageFixture" } },
  });
  if ("on" in result) throw new Error("Expected one-off build");
  const chunk = (Array.isArray(result) ? result : [result]).flatMap(bundle => bundle.output).find(output => output.type === "chunk" && output.isEntry);
  if (chunk?.type !== "chunk") throw new Error("Missing fixture");
  script = chunk.code;
});

test("chart language updates keep manually zoomed and panned observations", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1050, height: 800 });
  await serveBrandAssets(page);
  await page.route("https://chart.test/", route => route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` }));
  await page.goto("https://chart.test/");
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
  await page.getByRole("button", { name: "About Net Strategy", exact: true }).click();
  const panel = page.getByRole("dialog");
  await expect(panel).toContainText("after trading costs");
  const close = panel.getByRole("button", { name: "Close explanation", exact: true });
  await close.focus();
  // Invoke the same fixture control without pointer light-dismiss of the native popover.
  await page.getByRole("button", { name: "简体中文", exact: true }).evaluate(element => (element as HTMLButtonElement).click());
  await expect(panel).toContainText("已扣除交易费用");
  await expect(panel.getByRole("button", { name: "关闭说明", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(panel).not.toBeVisible();
});
