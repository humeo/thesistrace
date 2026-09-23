import { fontStylesheet, serveBrandAssets } from "./brand-assets";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { build } from "vite";

test.beforeEach(async ({ page }) => { await serveBrandAssets(page); });

let script: string;
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8")
  + readFileSync(new URL("../src/analysis/common-input-observations.css", import.meta.url), "utf8");

test.beforeAll(async () => {
  const result = await build({
    configFile: false, logLevel: "silent", esbuild: { jsx: "automatic" },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, lib: {
      entry: fileURLToPath(new URL("./fixtures/common-inputs.tsx", import.meta.url)),
      formats: ["iife"], name: "CommonInputsFixture",
    } },
  });
  if ("on" in result) throw new Error("Expected a one-off build");
  const chunk = (Array.isArray(result) ? result : [result]).flatMap(bundle => bundle.output)
    .find(output => output.type === "chunk" && output.isEntry);
  if (chunk?.type !== "chunk") throw new Error("Missing component bundle");
  script = chunk.code;
});

const first = { session: "2026-08-03", identifier: "universe_return", industry_code: null,
  value: 0, member_count: 2, valid_count: 1, exclusions: { invalid_previous_close: 1 } };

test("common inputs load on demand and page through zero and missing values", async ({ page }) => {
  let reads = 0;
  await page.route("https://common.test/**", async route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
    reads++;
    const next = url.searchParams.has("cursor");
    await route.fulfill({ json: { items: [next ? { ...first, identifier: "industry_return",
      industry_code: "801010", value: null, member_count: 0, valid_count: 0, exclusions: {} } : first],
      next_cursor: next ? null : "next-page" } });
  });
  await page.goto("https://common.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await expect(page.getByText("Common market inputs", { exact: true })).toBeVisible();
  expect(reads).toBe(0);
  await page.getByText("Common market inputs", { exact: true }).click();
  await expect(page.getByRole("cell", { name: "0.00%", exact: true })).toBeVisible();
  await expect(page.getByText("Invalid previous Close: 1")).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("cell", { name: "Universe · SW2021 L1 801010" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "—", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
  await page.screenshot({ path: "../../.local/browser-tests/common-inputs.png", fullPage: true });
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(page.getByRole("cell", { name: "0.00%", exact: true })).toBeVisible();
  expect(reads).toBe(3);
});

test("failed requests can retry without looking like an empty sample", async ({ page }) => {
  let reads = 0;
  await page.route("https://common.test/**", async route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
    reads++;
    await route.fulfill(reads === 1 ? { status: 500, body: "error" }
      : { json: { items: [], next_cursor: null } });
  });
  await page.goto("https://common.test/");
  await page.addScriptTag({ content: script });
  await page.getByText("Common market inputs", { exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("公共市场输入加载失败。重新加载首页");
  expect(reads).toBe(1);
  await page.getByRole("button", { name: "English", exact: true }).click();

  await page.getByRole("button", { name: "Reload first page" }).click();
  await expect(page.getByText("This research does not use common market inputs.")).toBeVisible();
});
