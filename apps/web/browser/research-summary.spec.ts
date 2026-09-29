import { expect, test } from "@playwright/test";
import { defaultSimulationCosts } from "../src/research/simulationCosts";
import { buildProductFixture } from "./build-product-fixture";

let script: string;
let styles: string;
test.beforeAll(async () => {
  ({ script, styles } = await buildProductFixture(new URL("./fixtures/research-cancellation.tsx", import.meta.url), "ResearchEvidenceFixture"));
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
      close_risk_nav_cny: "98995",
      session: "2026-08-04", net_cash: "89995", gross_cash: "90000", net_nav: "99995", gross_nav: "100000",
      cumulative_transaction_cost: "5", positions: [{
        instrument_id: "equity:600001.SH", execution_shares: 1000, adjusted_units: "1000",
        remaining_acquisition_cost_cny: "10005", holding_cycle_started_session: "2026-08-04",
        holding_age: 1, last_adjusted_price: "10", last_close_adjusted_price: "9",
      }], pending_target: null, contract_checksum: "contract",
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
  const summary = page.getByRole("region", { name: "Strategy Summary", exact: true });
  const conventions = summary.getByRole("button", { name: "Execution conventions", exact: true });
  const explanation = summary.getByText(/Decisions execute at the next Open/);
  for (const width of [1050, 1440]) {
    await page.setViewportSize({ width, height: 964 });
    await expect(summary.getByRole("region", { name: "Ending state", exact: true }).getByText("2026-08-04", { exact: true })).toBeVisible();
    await expect(summary.getByText("Target stock exposure", { exact: true })).toBeVisible();
    await expect(summary.getByText("Actual stock exposure", { exact: true })).toBeVisible();
    const selection = summary.getByRole("button", { name: "Selection check", exact: true });
    await expect(summary.getByText("No candidates excluded by weighting.")).not.toBeVisible();
    await selection.click();
    await expect(summary.getByText("No candidates excluded by weighting.")).toBeVisible();
    await selection.click();
    await expect(explanation).not.toBeVisible();
    const metricsBox = await summary.getByRole("group", { name: "Strategy Summary", exact: true }).boundingBox();
    const contextBox = await summary.getByRole("heading", { name: "Ending state", exact: true }).boundingBox();
    expect(metricsBox!.y + metricsBox!.height).toBeLessThanOrEqual(contextBox!.y);
    await conventions.focus();
    await conventions.press("Enter");
    await expect(explanation).toBeVisible();
    await expect(summary.getByText(/not a hard allocation limit/)).toBeVisible();
    expect(await summary.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
    await conventions.press("Enter");
    await expect(explanation).not.toBeVisible();
    const risk = summary.locator('[data-slot="collapsible"]').filter({ has: page.getByRole("button", { name: "Close risk and holdings", exact: true }) });
    await risk.getByRole("button", { name: "Close risk and holdings", exact: true }).click();
    await expect(risk.getByText("98995", { exact: true })).toBeVisible();
    await expect(risk.getByText("10005", { exact: true })).toBeVisible();
    await expect(risk.getByText("Holding age (trading sessions)")).toBeVisible();
    expect(await summary.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
    await page.screenshot({ path: `../../.local/browser-tests/close-risk-${width}.png`, fullPage: true });
    await risk.getByRole("button", { name: "Close risk and holdings", exact: true }).click();
  }
});

test("result tabs hide inactive panels and retain applied holdings filters", async ({ page }) => {
  const reads: Record<string, unknown>[] = [];
  await page.route("https://research-evidence.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (path === "/api/research-folders") return route.fulfill({ json: { items: [{ id: "folder_default", name: "Default", is_default: true }], next_cursor: null } });
    if (path.endsWith("/holdings/query")) {
      const query = route.request().postDataJSON(); reads.push(query);
      const unit = { unit_id: "period1", source_kind: "research_run", first_session: "2026-08-03", last_session: "2026-08-04", expires_at: "2026-08-11T00:00:00Z", status: "available" };
      return route.fulfill({ json: query.section === "daily_holdings_status"
        ? { status: "recorded", units: [unit], next_cursor: null }
        : { status: "available", unit, rows: [], coverage: { session_count: 2 }, next_cursor: null } });
    }
    return route.fulfill({ json: run });
  });
  await page.goto("https://research-evidence.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  const resultTabs = page.getByRole("tablist", { name: "Result views", exact: true });
  expect(await resultTabs.evaluate(element => element.scrollHeight <= element.clientHeight)).toBe(true);
  await page.getByRole("tab", { name: "Configuration", exact: true }).click();
  await expect(page.getByRole("tabpanel", { name: "Overview", exact: true, includeHidden: true })).not.toBeVisible();
  await expect(page.getByRole("group", { name: "Research execution conditions" })).toBeVisible();
  await page.getByRole("tab", { name: "Daily holdings", exact: true }).click();
  await expect(page.getByRole("group", { name: "Research execution conditions", includeHidden: true })).not.toBeVisible();
  await page.getByRole("textbox", { name: "From", exact: true }).fill("2026-08-03");
  await page.getByRole("button", { name: "Load holdings", exact: true }).click();
  await expect(page.getByText("No holdings on this page.")).toBeVisible();
  const loaded = reads.length;
  await page.getByRole("tab", { name: "Overview", exact: true }).click();
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await page.setViewportSize({ width: 320, height: 844 });
  await page.getByRole("tab", { name: "每日持仓", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "开始", exact: true })).toHaveValue("2026-08-03");
  expect(reads).toHaveLength(loaded);
});

test.describe("Frozen Framework touch controls", () => {
  test.use({ hasTouch: true });
  test("frozen module source disclosures work on desktop touch layouts", async ({ page }) => {
    const program = { source: "def decide(context, state, parameters):\n    return {'output': None, 'state': state}",
      parameters: { threshold: 0.03 }, data_requirements: { field_ids: [], history_sessions: 1 } };
    const input = { research_kind: "strategy_backtest", strategy_mode: "framework", initial_cash_cny: "100000", costs: defaultSimulationCosts(),
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
    await page.getByRole("tab", { name: "Configuration", exact: true }).click();
    for (const width of [1280, 1440]) {
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

test("Start Tracking prevents duplicate submissions and preserves results after failure", async ({ page }) => {
  const admissions: unknown[] = [];
  let release: (() => void) | undefined;
  await page.route("https://research-evidence.test/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (path === "/api/research-folders") return route.fulfill({ json: { items: [{ id: "folder_default", name: "Default", is_default: true }], next_cursor: null } });
    if (path.endsWith("/daily-tracks")) {
      admissions.push(route.request().postDataJSON());
      if (admissions.length === 1) {
        await new Promise<void>(resolve => { release = resolve; });
        return route.fulfill({ status: 503, json: { error: "temporarily unavailable" } });
      }
      return route.fulfill({ status: 202, json: { id: "track_created" } });
    }
    return route.fulfill({ json: run });
  });
  await page.goto("https://research-evidence.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  const start = page.getByRole("button", { name: "Start Tracking", exact: true });
  await start.evaluate(button => { (button as HTMLButtonElement).click(); (button as HTMLButtonElement).click(); });
  await expect(page.getByRole("button", { name: "Starting Tracking…", exact: true })).toBeDisabled();
  await expect.poll(() => admissions.length).toBe(1);
  release!();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByText("Net cumulative", { exact: true })).toBeVisible();
  await start.click();
  await expect(page).toHaveURL(/\/daily-tracks\/track_created$/);
  expect(admissions).toHaveLength(2);
  expect(admissions[0]).toEqual(admissions[1]);
});

test("result header keeps its title readable beside an expanded sidebar", async ({ page }) => {
  await page.route("https://research-evidence.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (path === "/api/research-folders") return route.fulfill({ json: {
      items: [{ id: "folder_default", name: "Default", is_default: true }], next_cursor: null,
    } });
    return route.fulfill({ json: { ...run, batch_id: "batch_completed" } });
  });
  await page.goto("https://research-evidence.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  for (const [width, sidebar] of [[1280, 224], [1440, 400], [1584, 224]]) {
    await page.setViewportSize({ width, height: 964 });
    // The shell owns this width; the result must fit the remaining content area.
    await page.locator("#root").evaluate((element, offset) => { element.style.marginLeft = `${offset}px`; }, sidebar);
    const title = page.getByRole("heading", { name: run.name, exact: true });
    const titleBounds = await title.boundingBox();
    expect(titleBounds!.width).toBeGreaterThanOrEqual(200);
    for (const name of ["Back to Research Runs", "View batch", "Start Tracking", "More actions"]) {
      const action = page.getByRole(name === "Start Tracking" || name === "More actions" ? "button" : "link", { name, exact: true });
      await expect(action).toBeVisible();
      const bounds = await action.boundingBox();
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
});
