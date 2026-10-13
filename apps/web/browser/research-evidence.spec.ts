import { expect, test } from "@playwright/test";
import { completedStrategyRun as run } from "./fixtures/strategy-result";
import { buildProductFixture } from "./build-product-fixture";
import { defaultSimulationCosts } from "../src/research/simulationCosts";
import { builtinFrameworkModules } from "../src/research/frameworkModules";
import { emptyResearchDraft } from "../src/research/draft";

let script: string;
let styles: string;
test.beforeAll(async () => {
  ({ script, styles } = await buildProductFixture(new URL("./fixtures/research-evidence.tsx", import.meta.url), "ResearchEvidenceFixture"));
});

// Shared deterministic result facts; request behavior remains local to each test.

test("configuration groups accepted research settings, strategy stages and readable fees", async ({ page }) => {
  await page.setViewportSize({ width: 1492, height: 954 });
  const input = { research_kind: "strategy_backtest", strategy_mode: "framework", initial_cash_cny: "1000000",
    costs: { ...defaultSimulationCosts(), commission_min_cny: "2", slippage_bps: "15" }, hypothesis: null,
    start_date: run.start_date, end_date: run.end_date, universe: "top300", formula: "rank(roe)", neutralization: "industry",
    holdings_count: 20, selection_every_sessions: 5, weighting: "equal_weight", exposure_expression: "1",
    modules: { ...builtinFrameworkModules,
      portfolio_construction: { kind: "periodic_top_n/v1", minimum_holding_sessions: 5 },
      risk_management: { kind: "builtin_risk/v1", stop_loss_threshold: 0.1, maximum_holding_sessions: 20 } } };
  await page.route("https://research-evidence.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (path === "/api/research-folders") return route.fulfill({ json: { items: [], next_cursor: null } });
    return route.fulfill({ json: { ...run, input,
      progress: { phase: "succeeded", completed_warmup_sessions: 0, total_warmup_sessions: 0,
        completed_research_sessions: 2, total_research_sessions: 2, committed_chunk_count: 1,
        last_completed_warmup_session: null, last_completed_research_session: run.end_date,
        remaining_duration_estimate_seconds: null, duration_is_estimate: false },
      execution_timing: { started_at: "2026-09-15T01:00:00Z", finished_at: "2026-09-15T02:00:00Z", elapsed_seconds: 487, is_final: true },
    } });
  });
  await page.goto("https://research-evidence.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByRole("tab", { name: "Configuration", exact: true }).click();
  const conditions = page.getByRole("region", { name: "Research conditions", exact: true });
  const fees = page.getByRole("region", { name: "Fees and slippage", exact: true });
  const strategy = page.getByRole("region", { name: "Strategy rules", exact: true });
  await expect(conditions).toContainText("1,000,000.00");
  await expect(conditions).toContainText("Top 300");
  await expect(strategy.getByRole("region", { name: "Alpha / Signals", exact: true })).toContainText("rank(roe)");
  await expect(strategy.getByRole("region", { name: "Portfolio Construction", exact: true })).toContainText("Minimum holding (trading sessions)5");
  await expect(strategy.getByRole("region", { name: "Risk Management", exact: true })).toContainText("10%");
  await expect(strategy.getByRole("region", { name: "Risk Management", exact: true })).not.toContainText("No additional exit rules");
  await expect(fees).toContainText("0.03%");
  await expect(fees).toContainText("0.05%");
  await expect(fees).toContainText("0.001%");
  await expect(fees).toContainText("2.00");
  await expect(fees.getByText("15", { exact: true })).toHaveAttribute("title", "15");
  const execution = page.getByRole("region", { name: "ResearchRun progress", exact: true });
  await expect(execution.getByRole("heading", { name: "Execution details", exact: true })).toBeVisible();
  await expect(execution.getByText("Execution complete", { exact: true })).toBeVisible();
  await expect(execution.getByText("8m 7s", { exact: true })).toBeVisible();
  await expect(execution).not.toContainText("1h 0m 0s");
  await expect(execution.getByText("8m 7s", { exact: true })).toHaveAttribute("title", /excluding queueing/);
  await expect(execution.getByText("2026-09-15 01:00:00 UTC", { exact: true })).toBeVisible();
  await expect(execution.getByText("2026-09-15 02:00:00 UTC", { exact: true })).toBeVisible();
  await execution.screenshot({ path: test.info().outputPath("execution-time.png") });
  await expect(execution.getByRole("button")).toHaveCount(0);
  const positions = await page.getByRole("group", { name: "Research execution conditions", exact: true }).evaluate(element => {
    const panels = [...element.querySelectorAll('[role="region"]')];
    return panels.map(panel => ({ label: panel.getAttribute("aria-label"), left: panel.getBoundingClientRect().left, top: panel.getBoundingClientRect().top }));
  });
  const research = positions.find(panel => panel.label === "Research conditions")!;
  const costs = positions.find(panel => panel.label === "Fees and slippage")!;
  expect(costs.left).toBeGreaterThan(research.left);
  expect(Math.abs(costs.top - research.top)).toBeLessThan(2);
});

test("ResearchRun trading event dates cannot query outside its backtest", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const queries: Record<string, unknown>[] = [];
  await page.route("https://research-evidence.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (path === "/api/research-folders") return route.fulfill({ json: { items: [], next_cursor: null } });
    if (path.endsWith("/events/query")) {
      const query = route.request().postDataJSON() as Record<string, unknown>;
      queries.push(query);
      return route.fulfill({ json: { section: query.section, status: "recorded", rows: [], next_cursor: null } });
    }
    return route.fulfill({ json: run });
  });
  await page.goto("https://research-evidence.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByRole("tab", { name: "Trading events", exact: true }).click();
  await expect(page.getByText("No matching Orders records.")).toBeVisible();
  await page.getByRole("textbox", { name: "From date", exact: true }).fill("2026-08-02");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("Choose a date from 2026-08-03 through 2026-08-04.");
  expect(queries).toHaveLength(1);
  await page.getByRole("textbox", { name: "From date", exact: true }).fill("2026-08-03");
  await page.getByRole("textbox", { name: "Through date", exact: true }).fill("2026-08-05");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("Choose a date from 2026-08-03 through 2026-08-04.");
  expect(queries).toHaveLength(1);
  await page.getByRole("textbox", { name: "Through date", exact: true }).fill("2026-08-04");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect.poll(() => queries.length).toBe(2);
  expect(queries.at(-1)).toMatchObject({ start_session: run.start_date, end_session: run.end_date });
});


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
    await page.getByRole("button", { name: "More actions", exact: true }).click();
    await page.getByRole("menuitem", { name: "Delete Research", exact: true }).click();
    await expect(page.getByRole("alertdialog")).toContainText("DailyTracks will remain.");
    await expect(page.getByRole("alertdialog")).toContainText("Evidence <br/> & regression");
    await expect(page.getByRole("alertdialog").locator("br")).toHaveCount(0);
    await page.getByRole("button", { name: "Keep Research", exact: true }).click();
    await expect(page.getByRole("alertdialog")).not.toBeVisible();
    await expect(page.getByRole("button", { name: "More actions", exact: true })).toBeFocused();
    await expect(page.getByText("Trading events", { exact: true })).toHaveCount(1);
    await expect(page.getByRole("tab", { name: "Daily holdings", exact: true })).toHaveCount(1);
    await expect(page.getByText("No matching Orders records.")).toBeVisible();
  }
  await page.getByRole("tab", { name: "Daily holdings", exact: true }).click();
  await expect(page.getByText("Daily holdings were not recorded for this result.")).toBeVisible();
});

test("result draft options open on demand and preserve the result when dismissed", async ({ page }) => {
  const input = { research_kind: "strategy_backtest", strategy_mode: "framework", initial_cash_cny: "100000",
    costs: defaultSimulationCosts(), hypothesis: null, start_date: run.start_date, end_date: run.end_date,
    universe: "top300", modules: builtinFrameworkModules };
  await page.route("https://research-evidence.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (path === "/api/research-folders") return route.fulfill({ json: { items: [
      { id: "folder_default", name: "Default", is_default: true },
      { id: "folder_followup", name: "Follow-up", is_default: false },
    ], next_cursor: null } });
    return route.fulfill({ json: { ...run, input } });
  });
  await page.goto("https://research-evidence.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await expect(page.getByRole("combobox", { name: "Target Folder" })).not.toBeVisible();
  await page.getByRole("button", { name: "Use as draft", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Create a draft", exact: true });
  await expect(dialog.getByRole("combobox", { name: "Target Folder" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Use as draft", exact: true })).toBeFocused();
  await expect(page.getByRole("group", { name: "Strategy Summary", exact: true })).toBeVisible();
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
  await page.evaluate(draft => localStorage.setItem("thesistrace.research-draft.test.folder_followup", JSON.stringify(draft)), {
    ...emptyResearchDraft(), formula: "local unsent formula", storageSchema: "research-draft/v7",
  });
  await page.getByRole("button", { name: "Use as draft", exact: true }).click();
  await dialog.getByRole("combobox", { name: "Target Folder" }).click();
  await page.getByRole("option", { name: "Follow-up", exact: true }).click();
  await dialog.getByRole("button", { name: "Create draft", exact: true }).click();
  const replacement = page.getByRole("alertdialog");
  await expect(replacement).toContainText("discard unexecuted browser changes");
  await replacement.getByRole("button", { name: "Keep current draft", exact: true }).click();
  await expect(dialog.getByRole("combobox", { name: "Target Folder" })).toContainText("Follow-up");
  expect(await page.evaluate(() => localStorage.getItem("thesistrace.research-draft.test.folder_followup"))).toContain("local unsent formula");
  await dialog.getByRole("button", { name: "Create draft", exact: true }).click();
  await replacement.getByRole("button", { name: "Replace draft", exact: true }).click();
  await expect(page).toHaveURL(/\/research\?folder=folder_followup$/);
  expect(await page.evaluate(() => localStorage.getItem("thesistrace.research-draft.test.folder_followup"))).toContain('"researchKind":"strategy_backtest"');
});
