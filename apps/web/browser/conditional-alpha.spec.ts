import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { build } from "vite";

const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
let timelineScript: string;

test.beforeAll(async () => {
  // Bundle the actual component, not a copy of its markup or resizing logic.
  // This browser test needs no server, Auth, Agent, or database.
  const result = await build({
    configFile: false,
    logLevel: "silent",
    esbuild: { jsx: "automatic" },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: {
      write: false,
      minify: false,
      lib: {
        entry: fileURLToPath(new URL("./fixtures/conditional-alpha.tsx", import.meta.url)),
        formats: ["iife"],
        name: "ChatTimelineFixture",
      },
    },
  });
  if ("on" in result) throw new Error("Timeline fixture must be a one-off build");
  const chunk = (Array.isArray(result) ? result : [result])
    .flatMap((bundle) => bundle.output)
    .find((output) => output.type === "chunk" && output.isEntry);
  if (chunk?.type !== "chunk") throw new Error("Timeline fixture entry is missing");
  timelineScript = chunk.code;
});


test("conditional Alpha editing preserves source and recognizes Boolean grammar", async ({ page }) => {
  await page.setContent('<div id="root"></div>');
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: timelineScript });
  const editor = page.locator('.cm-content');
  const formula = 'if_else(close > open and not (open == 0), close / open, 0)';
  await editor.fill(formula);
  await expect(page.getByLabel('Saved formula')).toHaveText(formula);
  await expect(page.getByLabel('Syntax errors')).toHaveText('0');
  await expect(page.locator('.cm-alpha-operator').filter({ hasText: 'and' })).toBeVisible();
  await editor.fill('if_else(close >= open or close != 0, close, open)');
  await expect(page.getByLabel('Syntax errors')).toHaveText('0');
});


test("common industry parameters are discoverable in the actual editor", async ({ page }) => {
  await page.setContent('<div id="root"></div>');
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: timelineScript });
  const editor = page.locator('.cm-content');
  await editor.fill('close * industry_return(801');
  await editor.press('Control+Space');
  const choice = page.getByRole('option').filter({ hasText: '801010' });
  await expect(choice).toBeVisible();
  await expect(choice).toContainText('农林牧渔');
  await choice.click();
  await editor.press('End');
  await editor.press(')');
  await expect(page.getByLabel('Saved formula')).toHaveText('close * industry_return(801010)');
  await expect(page.getByLabel('Syntax errors')).toHaveText('0');
});
