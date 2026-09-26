import { expect, test } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";

let script: string;
let styles: string;
test.beforeAll(async () => {
  ({ script, styles } = await buildProductFixture(new URL("./fixtures/research-evidence.tsx", import.meta.url), "ResearchEvidenceFixture"));
});

const run = {
  id: "run_evidence", status: "succeeded", name: "Evidence <br/> & regression",
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
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await expect(page.getByText("Trading events", { exact: true })).toHaveCount(1);
  await page.getByText("Trading events", { exact: true }).click();
  await expect(page.getByText("No matching Orders records.")).toBeVisible();
  // Opening and dismissing the confirmation only updates the actual parent page;
  // it must not replace these independent sections or leave orphaned DOM nodes.
  for (let i = 0; i < 3; i++) {
    await page.getByRole("banner").getByRole("button", { name: "Delete Research", exact: true }).click();
    await expect(page.getByRole("alertdialog")).toContainText("DailyTracks will remain.");
    await expect(page.getByRole("alertdialog")).toContainText("Evidence <br/> & regression");
    await expect(page.getByRole("alertdialog").locator("br")).toHaveCount(0);
    await page.getByRole("button", { name: "Keep Research", exact: true }).click();
    await expect(page.getByRole("alertdialog")).not.toBeVisible();
    await expect(page.getByText("Trading events", { exact: true })).toHaveCount(1);
    await expect(page.getByRole("tab", { name: "Daily holdings", exact: true })).toHaveCount(1);
    await expect(page.getByText("No matching Orders records.")).toBeVisible();
  }
  await page.getByRole("tab", { name: "Daily holdings", exact: true }).click();
  await expect(page.getByText("Daily holdings were not recorded for this result.")).toBeVisible();
});
