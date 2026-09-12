import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { build } from "vite";

let script: string;
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
test.beforeAll(async () => {
  const result = await build({
    configFile: false, logLevel: "silent", esbuild: { jsx: "automatic" },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, lib: {
      entry: fileURLToPath(new URL("./fixtures/selection-exposure.tsx", import.meta.url)),
      formats: ["iife"], name: "SelectionExposureFixture",
    } },
  });
  if ("on" in result) throw new Error("Expected one-off build");
  const chunk = (Array.isArray(result) ? result : [result]).flatMap(bundle => bundle.output)
    .find(output => output.type === "chunk" && output.isEntry);
  if (chunk?.type !== "chunk") throw new Error("Missing component bundle");
  script = chunk.code;
});

for (const weighting of ["rank_weight", "inverse_volatility"] as const) {
test(`Exposure, ${weighting}, retained draft and submission share one source`, async ({ page }) => {
  const diagnostics: Record<string, unknown>[] = [];
  const submissions: Record<string, unknown>[] = [];
  const localContexts: string[] = [];
  await page.route("https://exposure.test/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/alpha/diagnostics") {
      localContexts.push(route.request().postDataJSON().context);
      return route.fulfill({ json: { valid: true, diagnostics: [] } });
    }
    if (path === "/api/research/diagnostics") {
      diagnostics.push(route.request().postDataJSON());
      return route.fulfill({ json: { valid: true, issues: [] } });
    }
    if (path === "/api/research-runs") {
      submissions.push(route.request().postDataJSON());
      return route.fulfill({ json: { id: "run_exposure" }, status: 202 });
    }
    return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
  });
  const mount = async () => {
    await page.goto("https://exposure.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
  };
  await mount();
  await expect(page.getByLabel("Portfolio weighting", { exact: false })).toHaveValue("equal_weight");
  await page.getByLabel("Portfolio weighting", { exact: false }).selectOption(weighting);
  if (weighting === "inverse_volatility") {
    await expect(page.getByLabel("Volatility window", { exact: false })).toHaveValue("20");
    await page.getByLabel("Volatility window", { exact: false }).fill("10");
  }
  await expect(page.getByLabel("Fixed exposure (%)", { exact: true })).toHaveValue("100");
  await page.getByLabel("Fixed exposure (%)", { exact: true }).fill("70");
  await expect(page.getByLabel("Exposure expression", { exact: true })).toHaveText("0.7");
  await mount();
  await expect(page.getByLabel("Portfolio weighting", { exact: false })).toHaveValue(weighting);
  if (weighting === "inverse_volatility") {
    await expect(page.getByLabel("Volatility window", { exact: false })).toHaveValue("10");
  }
  await expect(page.getByLabel("Fixed exposure (%)", { exact: true })).toHaveValue("70");
  await page.getByLabel("Exposure expression", { exact: true }).fill("7 / 10");
  await expect(page.getByLabel("Fixed exposure (%)", { exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "Check configuration" }).click();
  await expect(page.getByText("Configuration is valid.", { exact: false })).toBeVisible();
  expect(diagnostics).toHaveLength(1);
  expect(diagnostics[0]).toMatchObject({ exposure_expression: "7 / 10", weighting, volatility_window: weighting === "inverse_volatility" ? 10 : 20, selection_every_sessions: 5, initial_cash_cny: "100000" });
  expect(diagnostics[0]).not.toHaveProperty("request_id");
  expect(submissions).toHaveLength(0);
  await page.getByLabel("Exposure expression", { exact: true }).fill("0");
  await expect(page.getByText("Configuration is valid.", { exact: false })).not.toBeVisible();
  await expect(page.getByLabel("Fixed exposure (%)", { exact: true })).toHaveValue("0");
  await expect.poll(() => localContexts.includes("exposure")).toBe(true);
  await page.screenshot({ path: `../../.local/browser-tests/selection-${weighting}.png`, fullPage: true });
  await page.getByRole("button", { name: "Run research", exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(submissions[0]).toMatchObject({ exposure_expression: "0", weighting, volatility_window: weighting === "inverse_volatility" ? 10 : 20, selection_every_sessions: 5, initial_cash_cny: "100000" });
  expect(submissions[0]).toHaveProperty("request_id");
  expect(submissions[0]).not.toHaveProperty("rebalance_every_sessions");
});

}

test("configuration checks show rejection and recover from an unavailable service", async ({ page }) => {
  let checks = 0;
  await page.route("https://exposure.test/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
    if (path === "/api/research/diagnostics") {
      checks++;
      if (checks === 1) return route.fulfill({ json: {
        valid: false, issues: [{ code: "EXPOSURE_OUT_OF_RANGE", field: "exposure_expression",
          message: "Exposure must be between zero and one.", severity: "error", range: null }],
      } });
      if (checks === 2) return route.fulfill({ status: 503, body: "Unavailable" });
      return route.fulfill({ json: { valid: true, issues: [] } });
    }
    return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
  });
  await page.goto("https://exposure.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByLabel("Exposure expression", { exact: true }).fill("1.1");
  const check = page.getByRole("button", { name: "Check configuration" });
  await check.click();
  await expect(page.getByLabel("Configuration issues")).toContainText("exposure_expression");
  await page.getByLabel("Exposure expression", { exact: true }).fill("0.3");
  await expect(page.getByLabel("Configuration issues")).not.toBeVisible();
  await check.click();
  await expect(page.getByText("Configuration check is unavailable. Try again.")).toBeVisible();
  await expect(check).toBeEnabled();
  await check.click();
  await expect(page.getByText("Configuration is valid.", { exact: false })).toBeVisible();
  expect(checks).toBe(3);
});


test("Exposure completion excludes stock scope and keeps daily expression in the draft", async ({ page }) => {
  await page.route("https://exposure.test/**", route => {
    if (new URL(route.request().url()).pathname === "/api/alpha/diagnostics") {
      return route.fulfill({ json: { valid: true, diagnostics: [] } });
    }
    return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
  });
  const mount = async () => {
    await page.goto("https://exposure.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
  };
  await mount();
  const editor = page.getByLabel("Exposure expression", { exact: true });
  await editor.fill("");
  await editor.press("Control+Space");
  await expect(page.getByRole("listbox", { name: "Completions" }).getByRole("option").filter({ hasText: "universe_return" })).toBeVisible();
  await expect(page.getByRole("listbox", { name: "Completions" }).getByRole("option").filter({ hasText: "rank" })).toHaveCount(0);
  await expect(page.getByRole("listbox", { name: "Completions" }).getByRole("option").filter({ hasText: "close" })).toHaveCount(0);
  await editor.press("Escape");
  const expression = "if_else(universe_return() > 0, 1, 0.3)";
  await editor.fill(expression);
  await expect(page.getByLabel("Fixed exposure (%)", { exact: true })).toHaveValue("");
  await mount();
  await expect(page.getByLabel("Exposure expression", { exact: true })).toHaveText(expression);
  const signal = page.getByLabel("Alpha formula", { exact: true });
  await signal.fill("");
  await signal.press("Control+Space");
  await expect(page.getByRole("listbox", { name: "Completions" }).getByRole("option").filter({ hasText: "rank" })).toBeVisible();
  await expect(page.getByRole("listbox", { name: "Completions" }).getByRole("option").filter({ hasText: "close" })).toBeVisible();
});

for (const weighting of ["equal_weight", "rank_weight"] as const) {
  test(`Leaving invalid inverse window for ${weighting} keeps a runnable form`, async ({ page }) => {
    const submissions: Record<string, unknown>[] = [];
    await page.route("https://exposure.test/**", async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
      if (path === "/api/research-runs") {
        submissions.push(route.request().postDataJSON());
        return route.fulfill({ json: { id: "run_window" }, status: 202 });
      }
      return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    });
    await page.goto("https://exposure.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
    const selector = page.getByLabel("Portfolio weighting", { exact: false });
    await selector.selectOption("inverse_volatility");
    await page.getByLabel("Volatility window", { exact: false }).fill("253");
    await expect(page.getByRole("button", { name: "Run research", exact: true })).toBeDisabled();
    await selector.selectOption(weighting);
    await expect(page.getByLabel("Volatility window", { exact: false })).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Check configuration" })).toBeEnabled();
    await page.getByRole("button", { name: "Run research", exact: true }).click();
    await expect.poll(() => submissions.length).toBe(1);
    expect(submissions[0]).toMatchObject({ weighting, volatility_window: 20 });
  });
}
