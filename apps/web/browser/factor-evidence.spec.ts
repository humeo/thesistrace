import { fontStylesheet, serveBrandAssets } from "./brand-assets";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { build } from "vite";

test.beforeEach(async ({ page }) => { await serveBrandAssets(page); });

let script: string;
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8")
  + readFileSync(new URL("../src/analysis/factor-evidence.css", import.meta.url), "utf8");

test.beforeAll(async () => {
  const result = await build({
    configFile: false, logLevel: "silent", esbuild: { jsx: "automatic" },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, lib: {
      entry: fileURLToPath(new URL("./fixtures/factor-evidence.tsx", import.meta.url)),
      formats: ["iife"], name: "FactorEvidenceFixture",
    } },
  });
  if ("on" in result) throw new Error("Expected a one-off build");
  const chunk = (Array.isArray(result) ? result : [result]).flatMap(bundle => bundle.output)
    .find(output => output.type === "chunk" && output.isEntry);
  if (chunk?.type !== "chunk") throw new Error("Missing component bundle");
  script = chunk.code;
});


const groups = { q1: 0, q2: 0.01, q3: 0.02, q4: 0.03, q5: 0.04 };
const counts = { q1: 6, q2: 6, q3: 6, q4: 6, q5: 6 };
const daily = { session: "2026-08-03", horizon: 5, label_entry_session: "2026-08-04",
  label_exit_session: "2026-08-11", label_status: "within_research_period",
  alpha_candidate_count: 31, alpha_sample_count: 30, sample_count: 30,
  alpha_exclusions: { missing_expression: 1 }, label_exclusions: {},
  ic: 0.4, rank_ic: 0.5, correlation_reason: null, quantile_reason: null,
  quantile_returns: groups, quantile_counts: counts, top_bottom_return: 0.04 };
const period = { horizon: 5, granularity: "month", period: "2026-08",
  summary: { ic: { mean: 0.4, icir: 0.8 }, rank_ic: { mean: 0.5, icir: 1.2 },
    quantile_returns: groups, top_bottom_return: 0.04 },
  coverage: { signal_session_count: 20, ic_valid_session_count: 14, rank_ic_valid_session_count: 14,
    first_signal_session: "2026-08-03", last_signal_session: "2026-08-28",
    first_evaluable_signal_session: "2026-08-03", last_evaluable_signal_session: "2026-08-20",
    label_evaluable_session_count: 14, right_censored_session_count: 6,
    alpha_candidate_count: 620, alpha_sample_count: 600, sample_count: 420,
    alpha_exclusions: { missing_expression: 20 }, label_exclusions: { right_censored_by_research_period_end: 180 } } };

test("Factor evidence loads on demand, resets cursors with filters and shows daily coverage", async ({ page }) => {
  const reads: URL[] = [];
  await page.route("https://factor.test/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
    reads.push(url);
    const isDaily = url.pathname.endsWith("factor-observations");
    return route.fulfill({ json: { section: isDaily ? "factor_observations" : "factor_periods",
      items: [isDaily ? daily : period], next_cursor: url.searchParams.has("cursor") ? null : "next-page" } });
  });
  await page.goto("https://factor.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  expect(reads).toHaveLength(0);
  await page.getByText("Factor evidence", { exact: true }).click();
  await expect(page.getByRole("cell", { name: "2026-08", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
  await page.getByLabel("Horizon").selectOption("20");
  await expect.poll(() => reads.at(-1)?.searchParams.get("horizon")).toBe("20");
  expect(reads.at(-1)?.searchParams.has("cursor")).toBe(false);
  await page.getByLabel("View").selectOption("daily");
  await expect(page.getByRole("cell", { name: "2026-08-03", exact: true })).toBeVisible();
  await page.getByText("Coverage and label", { exact: true }).click();
  await expect(page.getByText("Missing signal: 1", { exact: true })).toBeVisible();
  await expect(page.getByText(/2026-08-04 → 2026-08-11/)).toBeVisible();
  await expect(page.getByText(/before costs/)).toBeVisible();
  const beforeLanguageReads = reads.length;
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(page.getByText("缺少信号: 1", { exact: true })).toBeVisible();
  await expect(page.getByLabel("预测周期")).toHaveValue("20");
  await expect(page.getByLabel("视图")).toHaveValue("daily");
  expect(reads).toHaveLength(beforeLanguageReads);
  for (const width of [1050, 390, 320]) {
    await page.setViewportSize({ width, height: 964 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }

  await page.screenshot({ path: "../../.local/browser-tests/factor-evidence.png", fullPage: true });
});

test("Factor request failure stays distinct from an empty page and can retry", async ({ page }) => {
  let reads = 0;
  await page.route("https://factor.test/**", route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
    reads++;
    return route.fulfill(reads === 1 ? { status: 503 } : { json: { section: "factor_periods", items: [], next_cursor: null } });
  });
  await page.goto("https://factor.test/");
  await page.addScriptTag({ content: script });
  await page.getByText("Factor evidence", { exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: "Reload first page" }).click();
  await expect(page.getByText("No observations in this selection.")).toBeVisible();
});

test("narrow Factor view preserves missing values and rejects reversed signal dates locally", async ({ page }) => {
  let reads = 0;
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("https://factor.test/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
    reads++;
    return route.fulfill({ json: { section: url.pathname.endsWith("factor-periods") ? "factor_periods" : "factor_observations",
      items: url.pathname.endsWith("factor-periods") ? [period] : [{ ...daily, ic: null, rank_ic: null,
        label_exit_session: null, label_status: "right_censored_by_research_period_end", sample_count: 0,
        label_exclusions: { right_censored_by_research_period_end: 30 },
        quantile_returns: { q1: null, q2: null, q3: null, q4: null, q5: null },
        quantile_counts: { q1: 0, q2: 0, q3: 0, q4: 0, q5: 0 }, top_bottom_return: null }],
      next_cursor: null } });
  });
  await page.goto("https://factor.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByText("Factor evidence", { exact: true }).focus();
  await page.keyboard.press("Enter");
  await page.getByLabel("View").selectOption("daily");
  await expect(page.getByRole("cell", { name: "—", exact: true }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "../../.local/browser-tests/factor-evidence-mobile.png", fullPage: true });
  await page.getByLabel("Signal from").fill("2026-08-10");
  await expect(page.getByRole("cell", { name: "2026-08-03", exact: true })).toBeVisible();
  const beforeInvalid = reads;
  await page.getByLabel("Signal through").fill("2026-08-01");
  await expect(page.getByRole("alert")).toHaveText("Signal through must be on or after Signal from.");
  expect(reads).toBe(beforeInvalid);
});
