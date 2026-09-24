import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { build } from "vite";

let script: string;
test.beforeAll(async () => {
  const result = await build({
    configFile: false, logLevel: "silent", esbuild: { jsx: "automatic" },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, lib: {
      entry: fileURLToPath(new URL("./fixtures/research-evidence.tsx", import.meta.url)),
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
  id: "run_evidence", status: "succeeded", name: "Evidence regression",
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
      close_risk_nav_cny: "100000",
      session: "2026-08-04", net_cash: "100000", gross_cash: "100000", net_nav: "100000", gross_nav: "100000",
      cumulative_transaction_cost: "0", positions: [], pending_target: null, contract_checksum: "contract",
      decision_state: { mode: "framework", selection: { signal_session: "2026-08-03", eligibility_exclusions: {} }, selection_interval: 10, exposure: 1 },
      research_phase: { origin_session: "2026-08-03", report_session_count: 2 },
    },
    provenance: { schema_version: "research-result-v3", research_run_id: "run_evidence", immutable_input_sha256: "a".repeat(64),
      calculation_contracts: {}, semantic_versions: {}, research_kind: "strategy_backtest" },
  },
};

test("ResearchRun updates preserve one working events and holdings section", async ({ page }) => {
  await page.route("https://research-evidence.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (path === "/api/research-folders") return route.fulfill({ json: {
      items: [{ id: "folder_default", name: "Default", is_default: true }], next_cursor: null,
    } });
    if (path.endsWith("/events/query")) return route.fulfill({ json: {
      section: route.request().postDataJSON().section, status: "recorded", rows: [], next_cursor: null,
    } });
    if (path.endsWith("/holdings/query")) return route.fulfill({ json: { status: "not_recorded", units: [], next_cursor: null } });
    return route.fulfill({ json: run });
  });
  await page.goto("https://research-evidence.test/");
  await page.addScriptTag({ content: script });
  await expect(page.getByText("Trading events", { exact: true })).toHaveCount(1);
  await page.getByText("Trading events", { exact: true }).click();
  await expect(page.getByText("没有匹配的委托记录。")).toBeVisible();
  // Opening and dismissing the confirmation only updates the actual parent page;
  // it must not replace these independent sections or leave orphaned DOM nodes.
  for (let i = 0; i < 3; i++) {
    await page.getByRole("button", { name: "Delete Research", exact: true }).click();
    await page.getByRole("button", { name: "Keep Research", exact: true }).click();
    await expect(page.getByText("Trading events", { exact: true })).toHaveCount(1);
    await expect(page.getByRole("button", { name: "Daily holdings", exact: true })).toHaveCount(1);
    await expect(page.getByText("没有匹配的委托记录。")).toBeVisible();
  }
  await page.getByRole("button", { name: "Daily holdings", exact: true }).click();
  await expect(page.getByText("Daily holdings were not recorded for this result.")).toBeVisible();
});
