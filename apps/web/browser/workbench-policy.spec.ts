import { expect, test } from "./workbench-fixture";
import { completedStrategyRun } from "./fixtures/strategy-result";

const cases = [
  { name: "Custom fees", fields: [], expectedRisk: "no_risk/v1", slippage: "15", edit: ["Price slippage (basis points)", "25"] },
  { name: "Close stop loss", fields: [["Stop loss (%)", "1"]], expectedRisk: { kind: "builtin_risk/v1", stop_loss_threshold: 0.01 }, slippage: "1000", edit: ["Stop loss (%)", "2"] },
  { name: "Holding periods", fields: [["Minimum holding (trading sessions)", "2"], ["Maximum holding (trading sessions)", "2"]], expectedRisk: { kind: "builtin_risk/v1", maximum_holding_sessions: 2 }, slippage: "0", edit: ["Minimum holding (trading sessions)", "1"] },
  { name: "Cumulative take profit", fields: [["Profit threshold (%)", "0.01"], ["Cumulative reduction (%)", "30"]], expectedRisk: { kind: "builtin_risk/v1", take_profit_tiers: [{ profit_threshold: 0.0001, cumulative_reduction: 0.3 }] }, slippage: "0", edit: ["Cumulative reduction (%)", "60"] },
  { name: "Portfolio drawdown", fields: [["Drawdown threshold (%)", "1"], ["Maximum stock exposure (%)", "30"], ["Cooldown (trading sessions)", "2"]], expectedRisk: { kind: "builtin_risk/v1", portfolio_drawdown: { drawdown_threshold: 0.01, maximum_stock_exposure: 0.3, cooldown_sessions: 2 } }, slippage: "1000", edit: ["Maximum stock exposure (%)", "20"] },
] as const;

const instrument = "equity:600001.SH";
const observations = {
  "Close stop loss": { reason: "stop_loss", instrument_id: instrument, remaining_acquisition_cost_cny: "10000", close_market_value_cny: "8900", holding_return: "-0.11", stop_loss_threshold: "0.01", execution_shares: 1000, holding_age: 1 },
  "Cumulative take profit": { reason: "take_profit", instrument_id: instrument, cycle_ended: false, holding_return: "0.2", profit_threshold: "0.0001", cumulative_reduction: "0.3", baseline_execution_shares: 1000, baseline_adjusted_units: "1000", target_adjusted_units: "700", executed_reduction_units: "100", remaining_reduction_units: "200", execution_shares: 900, position_limit: 700 },
  "Portfolio drawdown": { reason: "portfolio_drawdown", status: "threshold_reached", cycle_started_session: "2026-08-04", peak_close_nav_cny: "100000", close_risk_nav_cny: "98000", drawdown: "0.02", drawdown_threshold: 0.01, maximum_stock_exposure: 0.3, cooldown_sessions: 2, completed_cooldown_sessions: 0, triggered_session: "2026-08-05" },
};
const fill = { target_id: "target_a", order_id: "order_a", child_order_id: "child_a", fill_id: "fill_a", decision_session: "2026-08-04", session: "2026-08-05", instrument_id: instrument, side: "buy", reason: "selection", quantity: 100, raw_open: "10", adjusted_open: "20", execution_price: "10.015", price_slippage: "0.015", raw_notional: "1001.5", research_settlement: "1001.5", cost: "2", commission_cny: "2", stamp_duty_cny: "0", transfer_fee_cny: "0", cash_rounding_delta: "0", net_cash_delta: "-1003.5", adjusted_units_delta: "50", execution_shares_delta: 100 };

type Submission = { costs: Record<string, string>; modules: Record<string, unknown>; [key: string]: unknown };

for (const scenario of cases) {
  test(`${scenario.name} submits exact inputs, renders frozen evidence and restores an editable draft`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 960 });
    const runId = "run_cafebabefeed1234";
    const submitted: Submission[] = [];
    const observation = scenario.name in observations ? observations[scenario.name as keyof typeof observations] : null;
    const decision = {
      decision_id: "decision_a", decision_session: "2026-08-05", target_id: "target_a", modules: {},
      universe: { instrument_ids: [instrument], updated: true, reason: "dataset_universe" },
      alpha: { kind: "formula", values: [] }, proposal: null,
      portfolio_retentions: scenario.name === "Holding periods" ? [{ reason: "minimum_holding_period", instrument_id: instrument, execution_shares: 1000, holding_age: 1, minimum_holding_sessions: 2 }] : [],
      risk_adjustment: observation ? { mode: "builtin_risk", reason: observation.reason, position_limits: {}, observations: [observation] } : null,
    };
    await page.route("**/api/research-runs**", async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/research-runs" && route.request().method() === "POST") {
        submitted.push(route.request().postDataJSON());
        return route.fulfill({ status: 202, json: { id: runId } });
      }
      if (path.endsWith("/events/query")) {
        const section = route.request().postDataJSON().section;
        return route.fulfill({ json: { section, status: "recorded", rows: section === "strategy_framework" ? [decision] : section === "strategy_fills" ? [fill] : [], next_cursor: null } });
      }
      expect(path).toBe(`/api/research-runs/${runId}`);
      expect(submitted).toHaveLength(1);
      return route.fulfill({ json: { ...completedStrategyRun, id: runId, name: scenario.name, input: submitted[0] } });
    });
    await page.goto("/research?new");
    await page.getByRole("radio", { name: /Strategy Backtest/ }).check();
    await page.getByLabel("Research name").fill(scenario.name);
    await page.getByRole("combobox", { name: "How should stocks be ranked?", exact: true }).click();
    await page.getByRole("option", { name: "Custom scoring formula", exact: true }).click();
    await page.getByRole("textbox", { name: "Alpha formula", exact: true }).fill("close");
    await page.getByLabel("Research start date").fill("2026-08-04");
    await page.getByLabel("Research end date").fill("2026-08-05");
    await page.getByRole("combobox", { name: "Universe", exact: true }).click();
    await page.getByRole("option", { name: "Top 300", exact: true }).click();
    await page.getByRole("button", { name: "Industry adjustment", exact: true }).click();
    await page.getByRole("combobox", { name: "Neutralization", exact: true }).click();
    await page.getByRole("option", { name: "None", exact: true }).click();
    await page.getByLabel("Initial cash (CNY)").fill("100000");
    await page.getByLabel("Holdings count").fill("1");
    await page.getByLabel("Selection interval (trading days)").fill("1");
    if (scenario.name === "Close stop loss" || scenario.name === "Holding periods") await page.getByRole("button", { name: "Stop loss and holding limits", exact: true }).click();
    if (scenario.name === "Holding periods") await page.getByRole("button", { name: "Minimum holding period", exact: true }).click();
    if (scenario.name === "Portfolio drawdown") await page.getByRole("button", { name: "Limit portfolio drawdown", exact: true }).click();
    if (scenario.name === "Cumulative take profit") await page.getByRole("button", { name: "Take profit in stages", exact: true }).click();
    if (scenario.name === "Cumulative take profit") await page.getByRole("button", { name: "Add take-profit tier", exact: true }).click();
    for (const [label, value] of scenario.fields) await page.getByLabel(label, { exact: true }).fill(value);
    await page.getByRole("button", { name: "Fees and slippage", exact: true }).click();
    await page.getByLabel("Price slippage (basis points)", { exact: true }).fill(scenario.slippage);
    await page.getByLabel("Minimum commission per child order (CNY)", { exact: true }).fill("2");
    await page.getByRole("button", { name: "Fees and slippage", exact: true }).click();
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/research-runs/${runId}$`));
    await expect(page.getByRole("heading", { name: "Strategy Summary" })).toBeVisible();
    expect(submitted).toHaveLength(1);
    const original = structuredClone(submitted[0]);
    expect(original.modules.risk_management).toEqual(scenario.expectedRisk);
    if (scenario.name === "Holding periods") expect(original.modules.portfolio_construction).toEqual({ kind: "periodic_top_n/v1", minimum_holding_sessions: 2 });
    expect(original.costs).toEqual({ commission_rate_all_in: "0.0003", commission_min_cny: "2", stamp_duty_sell_rate: "0.0005", transfer_fee_rate: "0.00001", slippage_bps: scenario.slippage });
    await page.getByRole("button", { name: "Close risk and holdings", exact: true }).click();
    await expect(page.getByText(/Close Risk NAV \(CNY\):/)).toBeVisible();
    if (scenario.name === "Custom fees") {
      await page.getByRole("tab", { name: "Configuration", exact: true }).click();
      await page.getByText("Frozen fees and slippage", { exact: true }).click();
      await expect(page.getByRole("group", { name: "Research execution conditions" })).toContainText("Price slippage (basis points) 15");
    }
    await page.getByText("Trading events", { exact: true }).click();
    await page.getByRole("combobox", { name: "Event type" }).click();
    await page.getByRole("option", { name: scenario.name === "Custom fees" ? "Fills" : "Framework decisions", exact: true }).click();
    await page.getByRole("button", { name: /View raw record/ }).first().click();
    if (scenario.name === "Custom fees") {
      await expect(page.getByRole("columnheader", { name: "Simulated execution price (CNY)" })).toBeVisible();
      await expect(page.getByRole("region", { name: "Fill price and cost details" })).toContainText("Per-share slippage");
    } else if (scenario.name === "Holding periods") {
      await expect(page.getByRole("list", { name: "Minimum-holding retention reasons" })).toContainText("below minimum 2");
    } else if (scenario.name === "Cumulative take profit") {
      await expect(page.getByRole("list", { name: "Risk decision reasons" })).toContainText("cumulative reduction 30%");
      await expect(page.getByRole("list", { name: "Risk decision reasons" })).toContainText("ordinary additions are forbidden");
    } else if (scenario.name === "Portfolio drawdown") {
      await expect(page.getByRole("list", { name: "Risk decision reasons" })).toContainText("Stock target cap 30%");
      await expect(page.getByRole("list", { name: "Risk decision reasons" })).toContainText("historical maximum drawdown is not reset");
    } else await expect(page.getByRole("list", { name: "Risk decision reasons" })).toContainText("stop-loss threshold");
    await page.screenshot({ path: testInfo.outputPath("frozen-policy.png"), fullPage: true });
    await page.getByRole("tab", { name: "Overview", exact: true }).click();
    await page.getByRole("button", { name: "Create draft", exact: true }).click();
    await expect(page).toHaveURL(/\/research$/);
    for (const [label, value] of scenario.fields) await expect(page.getByLabel(label, { exact: true })).toHaveValue(value);
    if (scenario.name === "Custom fees") {
      await page.getByRole("button", { name: "Fees and slippage", exact: true }).click();
      await expect(page.getByLabel("Price slippage (basis points)", { exact: true })).toHaveValue("15");
    }
    await page.getByLabel(scenario.edit[0], { exact: true }).fill(scenario.edit[1]);
    await expect(page.getByLabel(scenario.edit[0], { exact: true })).toHaveValue(scenario.edit[1]);
    expect(submitted).toEqual([original]);
  });
}
