import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { build } from "vite";

let script: string;
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
test.beforeAll(async () => {
  const result = await build({
    configFile: false, logLevel: "silent", esbuild: { jsx: "automatic" },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, lib: {
      entry: fileURLToPath(new URL("./fixtures/research-cancellation.tsx", import.meta.url)),
      formats: ["iife"], name: "ResearchEvidenceFixture",
    } },
  });
  if ("on" in result) throw new Error("Expected a one-off build");
  const chunk = (Array.isArray(result) ? result : [result]).flatMap(bundle => bundle.output)
    .find(output => output.type === "chunk" && output.isEntry);
  if (chunk?.type !== "chunk") throw new Error("Missing component bundle");
  script = chunk.code;
});

const run = {
  id: "run_cancel", status: "succeeded", name: "Evidence regression",
  folder_id: "folder_default", created_at: "2026-09-15T00:00:00Z",
  start_date: "2026-08-03", end_date: "2026-08-04", formula_summary: "rank(-pb)",
  research_kind: "strategy_backtest",
  result: {
    strategy: {
      summary: { alpha_checksum: "a", source_checksum: "b", entry_session: "2026-08-04", initial_cash_cny: "100000",
        metrics: { net_cumulative_return: 0, benchmark_cumulative_return: null, benchmark_cagr: null,
          annualized_excess_return: null, maximum_drawdown: { value: 0 }, sharpe: null, transaction_costs: { ratio: 0 } } },
      observations: [], comparison: { status: "unavailable", reason: "benchmark_snapshot_unavailable" },
    },
    terminal_strategy_state: {
      session: "2026-08-04", net_cash: "100000", gross_cash: "100000", net_nav: "100000", gross_nav: "100000",
      cumulative_transaction_cost: "0", positions: [], pending_target: null, contract_checksum: "contract",
      decision_state: { mode: "framework", selection: { signal_session: "2026-08-03", eligibility_exclusions: {} }, selection_interval: 10, exposure: 1 },
      research_phase: { origin_session: "2026-08-03", report_session_count: 2 },
    },
    provenance: { schema_version: "research-result-v3", research_run_id: "run_cancel", immutable_input_sha256: "a".repeat(64),
      calculation_contracts: {}, semantic_versions: {}, research_kind: "strategy_backtest" },
  },
};

test("strategy summary prioritizes metrics and keeps execution conventions expandable", async ({ page }) => {
  await page.route("https://research-evidence.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (path === "/api/research-folders") return route.fulfill({ json: {
      items: [{ id: "folder_default", name: "Default", is_default: true }], next_cursor: null,
    } });
    return route.fulfill({ json: run });
  });
  await page.goto("https://research-evidence.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  const summary = page.locator(".research-result-section");
  const conventions = summary.locator("summary");
  const explanation = summary.getByText(/Decisions execute at the next Open/);
  for (const width of [1050, 390]) {
    await page.setViewportSize({ width, height: 964 });
    await expect(summary.getByText("Account through 2026-08-04")).toBeVisible();
    await expect(summary.getByText("Last Close target")).toBeVisible();
    await expect(summary.getByText("Actual Open allocation")).toBeVisible();
    await expect(summary.getByText("No candidates excluded by weighting.")).toBeVisible();
    await expect(explanation).not.toBeVisible();
    const metricsBox = await summary.locator(".strategy-metrics").boundingBox();
    const contextBox = await summary.locator(".strategy-execution-context").boundingBox();
    expect(metricsBox!.y + metricsBox!.height).toBeLessThanOrEqual(contextBox!.y);
    await conventions.focus();
    await conventions.press("Enter");
    await expect(explanation).toBeVisible();
    await expect(summary.getByText(/not a hard allocation limit/)).toBeVisible();
    expect(await summary.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
    await conventions.press("Enter");
    await expect(explanation).not.toBeVisible();
  }
});

test.describe("Frozen Framework touch controls", () => {
  test.use({ hasTouch: true });
  test("frozen module source disclosures work on wide and narrow touch layouts", async ({ page }) => {
    const program = { source: "def decide(context, state, parameters):\n    return {'output': None, 'state': state}",
      parameters: { threshold: 0.03 }, data_requirements: { field_ids: [], history_sessions: 1 } };
    const input = { research_kind: "strategy_backtest", strategy_mode: "framework", initial_cash_cny: "100000",
      hypothesis: null, start_date: "2026-08-03", end_date: "2026-08-04", universe: "top300", modules: {
        universe_selection: "dataset_universe/v1", alpha: { kind: "python", program },
        portfolio_construction: { kind: "python", program }, risk_management: "no_risk/v1",
      } };
    await page.route("https://research-evidence.test/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
      if (path === "/api/research-folders") return route.fulfill({ json: {
        items: [{ id: "folder_default", name: "Default", is_default: true }], next_cursor: null,
      } });
      return route.fulfill({ json: { ...run, input } });
    });
    await page.goto("https://research-evidence.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 964 });
      const disclosure = page.getByText("Portfolio Construction · Frozen Python source and parameters", { exact: true });
      const bounds = await disclosure.boundingBox();
      expect(bounds?.height).toBeGreaterThanOrEqual(44);
      expect(bounds?.width).toBeGreaterThanOrEqual(44);
      await disclosure.focus();
      await disclosure.press("Enter");
      await expect(disclosure.locator("..").getByText(program.source, { exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await disclosure.press("Enter");
    }
  });
});
