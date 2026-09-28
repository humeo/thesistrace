import { expect, test, type Page } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";
let script: string;
let styles: string;
const track = {
  id: "track_ui", status: "active", checkpoint_manifest_sha256: "a".repeat(64),
  origin: { seed_run_id: "My original run", seed_research_available: true, strategy_session: "2026-08-01",
    result_checksum_sha256: "b".repeat(64), terminal_account: { net_nav: "10000", net_cash: "10000", positions: [] } },
  strategy_session: "2026-08-20", data_through_session: "2026-08-21", lag_sessions: 1,
  progress: { phase: "waiting", head_session: "2026-08-20", lag_sessions: 1, target_start_session: null,
    target_end_session: null, target_session_count: 0, completed_target_sessions: 0, current_session: null,
    cycle_attempt: null, cycle_attempt_limit: 3, retry_wait: false, next_attempt_eligible_at: null },
  blocked_reason: null, blocked_code: null,
  observation: { session: "2026-08-20", net_asset_value_cny: "11000", close_risk_nav_cny: "11000", cash_cny: "2000", net_change_cny: "1000",
    net_return: 0.1, maximum_drawdown: 0.025, transaction_cost_cny: "27.50", session_count: 20,
    holdings: [{ instrument_id: "000001.SZ", shares: 1000, market_value_cny: "9000", weight: 9 / 11,
      adjusted_units: "1000", last_close_adjusted_price: "9", remaining_acquisition_cost_cny: "8500",
      holding_cycle_started_session: "2026-08-01", holding_age: 20 }],
    decision_state: { mode: "framework", selection: { signal_session: "2026-08-19", eligibility_exclusions: {} }, selection_interval: 5, exposure: 0.7 },
    target_selection: { signal_session: "2026-08-19", eligibility_exclusions: {} },
    target_exposure: 0.7, selection_interval: 5, pending_target_session: null, sessions_until_next_signal: 4,
    returns: Array.from({ length: 20 }, (_, index) => ({ session: `2026-08-${String(index + 1).padStart(2, "0")}`, net_return: index / 1000 })) },
  strategy: { summary: { metrics: { net_cumulative_return: 0.1, benchmark_cumulative_return: null, benchmark_cagr: null,
    annualized_excess_return: null, maximum_drawdown: { value: 0.025 }, sharpe: null, transaction_costs: { cumulative_amount: 27.50 } } },
    comparison: { status: "unavailable", reason: "benchmark_snapshot_unavailable" }, observations: [] },
};

test.beforeAll(async () => {
  test.setTimeout(120_000);
  ({ script, styles } = await buildProductFixture(new URL("./fixtures/daily-tracks-language.tsx", import.meta.url), "DailyLanguage"));
});

async function open(page: Page, value = track) {
  let reads = 0;
  let mutations = 0;
  await page.route("https://daily-language.test/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (route.request().method() !== "GET") { mutations += 1; return route.fulfill({ status: 503 }); }
    reads += 1;
    return url.pathname === "/api/daily-tracks/track_ui" ? route.fulfill({ json: value }) : route.fulfill({ status: 503 });
  });
  await page.goto("https://daily-language.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await expect(page.getByRole("tab", { name: "Holdings" })).toBeVisible();
  return { reads: () => reads, mutations: () => mutations };
}

test("switching retains holdings filters, open stop decision and failure state on all widths", async ({ page }) => {
  const requests = await open(page);
  await page.getByRole("tab", { name: "Holdings" }).click();
  await page.getByRole("searchbox", { name: "Filter holdings by symbol" }).fill("000001");
  await page.getByRole("tab", { name: "Performance", exact: true }).click();
  await page.getByRole("tab", { name: "Holdings" }).click();
  await expect(page.getByRole("searchbox", { name: "Filter holdings by symbol" })).toHaveValue("000001");
  const reads = requests.reads();
  for (const width of [1440, 1280, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 964 });
    await page.getByRole("button", { name: "简体中文", exact: true }).click();
    await expect(page.getByRole("tab", { name: "持仓" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("searchbox", { name: "按证券代码筛选持仓" })).toHaveValue("000001");
    await expect(page.getByRole("region", { name: "持仓表" })).toContainText("1,000");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("button", { name: "English", exact: true }).click();
  }
  expect(requests.reads()).toBe(reads);
  await page.getByRole("button", { name: /Tracking origin/ }).click();
  expect((await page.getByRole("link", { name: "My original run", exact: true }).boundingBox())?.height).toBeGreaterThanOrEqual(44);
  await page.getByRole("button", { name: /Tracking origin/ }).click();
  expect(requests.mutations()).toBe(0);
  await page.getByRole("button", { name: "Manage", exact: true }).click();
  await page.getByRole("menuitem", { name: "Stop DailyTrack", exact: true }).click();
  const decision = page.getByRole("alertdialog", { name: "Stop this DailyTrack?" });
  await decision.getByRole("button", { name: "Keep tracking" }).focus();
  await page.getByRole("button", { name: "简体中文", exact: true, includeHidden: true }).evaluate(element => (element as HTMLButtonElement).click());
  const translated = page.getByRole("alertdialog", { name: "停止此每日跟踪？" });
  await expect(translated.getByRole("button", { name: "继续跟踪" })).toBeFocused();
  await translated.getByRole("button", { name: "停止每日跟踪", exact: true }).click();
  await expect(translated.getByRole("alert")).toHaveText("无法停止跟踪，请重试。");
  await page.getByRole("button", { name: "English", exact: true, includeHidden: true }).evaluate(element => (element as HTMLButtonElement).click());
  await expect(decision.getByRole("alert")).toHaveText("The track could not be stopped. Please try again.");
  expect(requests.mutations()).toBe(1);
  expect(requests.reads()).toBe(reads);
});

test("tracking chart retains its zoom and data while switching display language", async ({ page }) => {
  const requests = await open(page);
  await expect(page.getByRole("region", { name: "Daily Tracks list" }).getByRole("link", { name: "track_ui" })).toHaveAttribute("aria-current", "page");
  const chart = page.getByRole("figure", { name: /Return since tracking|跟踪开始以来收益/ });
  const plot = chart.locator("canvas").first();
  await plot.scrollIntoViewIfNeeded();
  const bounds = (await plot.boundingBox())!;
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + 100);
  await page.mouse.wheel(0, -350);
  const inspect = async () => {
    await plot.scrollIntoViewIfNeeded();
    const bounds = (await plot.boundingBox())!;
    const result: string[] = [];
    for (const ratio of [0.3, 0.5, 0.7]) {
      await page.mouse.move(bounds.x + bounds.width * ratio, bounds.y + 100);
      const footer = chart.locator("div[aria-live] > span");
      await expect(footer).toContainText("%");
      result.push((await footer.innerText()).match(/-?[\d.]+%/)![0]);
    }
    return result;
  };
  expect((await chart.getByRole("link", { name: "TradingView Lightweight Charts™" }).boundingBox())?.height).toBeGreaterThanOrEqual(44);
  const before = await inspect();
  await page.getByRole("tab", { name: "Holdings" }).click();
  await page.getByRole("tab", { name: "Performance", exact: true }).click();
  expect(await inspect()).toEqual(before);
  await page.getByRole("button", { name: "Full strategy", exact: true }).click();
  await page.getByRole("button", { name: "Since tracking", exact: true }).click();
  expect(await inspect()).toEqual(before);
  await page.getByRole("button", { name: "Reload status", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Reloading" })).toHaveCount(0);
  expect(await inspect()).toEqual(before);
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(chart).toHaveAttribute("aria-label", "跟踪开始以来收益");
  expect(await inspect()).toEqual(before);
  await page.getByRole("button", { name: "English", exact: true }).click();
  expect(await inspect()).toEqual(before);
  expect(requests.mutations()).toBe(0);
});

test("stop confirmation guards pending work and waits for the server terminal status", async ({ page }) => {
  const value = structuredClone(track);
  await open(page, value);
  let posts = 0;
  let release!: () => void;
  const accepted = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/daily-tracks/track_ui/stop", async route => {
    posts += 1;
    await accepted;
    value.status = "stopping";
    value.progress.phase = "stopping";
    await route.fulfill({ json: { status: "accepted" } });
  });
  await page.getByRole("button", { name: "Manage", exact: true }).click();
  await page.getByRole("menuitem", { name: "Stop DailyTrack", exact: true }).click();
  const dialog = page.getByRole("alertdialog", { name: "Stop this DailyTrack?" });
  await expect(dialog.getByRole("button", { name: "Keep tracking" })).toBeFocused();
  await dialog.getByRole("button", { name: "Stop DailyTrack", exact: true }).evaluate(element => { (element as HTMLButtonElement).click(); (element as HTMLButtonElement).click(); });
  await expect.poll(() => posts).toBe(1);
  await expect(dialog.getByRole("button", { name: "Stopping…", exact: true })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeVisible();
  release();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 2, name: /Stopping/ })).toContainText("Stopping");
  await expect(page.getByRole("button", { name: "Reload status", exact: true })).toBeFocused();
  await expect(page.getByText("DailyTrack is stopping. Waiting for the current execution to finish stopping.")).toBeVisible();
  await expect(page.getByRole("group", { name: "Tracking account", exact: true })).toContainText("10.00%");
  await page.getByRole("tab", { name: "Rebalance", exact: true }).click();
  await expect(page.getByRole("tabpanel", { name: "Rebalance", exact: true })).toContainText("Tracking is stopping");
  await expect(page.getByRole("tabpanel", { name: "Rebalance", exact: true })).not.toContainText("Tracking stopped");
  value.status = "stopped";
  value.progress.phase = "stopped";
  await expect(page.getByRole("heading", { level: 2, name: /Stopped/ })).toContainText("Stopped");
  await expect(page.getByRole("button", { name: "Refresh to latest data" })).toHaveCount(0);
});

test("stopped track deletion failure remains recoverable in the confirmation", async ({ page }) => {
  const value = structuredClone(track); value.status = "stopped"; value.progress.phase = "stopped";
  const requests = await open(page, value);
  await page.getByRole("button", { name: "Manage", exact: true }).click();
  await page.getByRole("menuitem", { name: "Delete DailyTrack", exact: true }).click();
  const dialog = page.getByRole("alertdialog", { name: "Delete DailyTrack", exact: true });
  await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeFocused();
  await dialog.getByRole("button", { name: "Delete DailyTrack", exact: true }).click();
  await expect(dialog.getByRole("alert")).toHaveText("DailyTrack deletion failed");
  await expect(dialog.getByRole("button", { name: "Delete DailyTrack", exact: true })).toBeEnabled();
  expect(requests.mutations()).toBe(1);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Manage", exact: true })).toBeFocused();
  await expect(page.getByRole("group", { name: "Tracking account", exact: true })).toContainText("10.00%");
});


test("track list retains published rows after failure and distinguishes an empty list", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  let failed = false;
  let empty = false;
  await page.route("https://daily-list.test/**", route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/") return route.fulfill({ contentType: "text/html", body: '<!doctype html><meta charset="utf-8"><div id="root"></div>' });
    if (failed) return route.fulfill({ status: 503 });
    return route.fulfill({ json: { items: empty ? [] : ["active", "blocked", "stopping", "stopped"].map((status, index) => ({
      id: `track_${index}`, status, seed_run_id: "run_origin", result_checksum_sha256: "a".repeat(64), origin_session: "2026-08-01", strategy_session: "2026-08-20",
    })), next_cursor: null } });
  });
  await page.goto("https://daily-list.test/?list");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  const list = page.getByRole("region", { name: "Daily Tracks list", exact: true });
  await expect(list.getByRole("link")).toHaveCount(4);
  await expect(list).toContainText("2026-08-20");
  expect((await page.getByRole("link", { name: "track_0", exact: true }).boundingBox())?.height).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  failed = true;
  await page.getByRole("button", { name: "Reload status", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Showing the last loaded list");
  await expect(list.getByRole("link")).toHaveCount(4);
  failed = false; empty = true;
  await page.getByRole("button", { name: "Reload status", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Your strategy watch starts with a backtest" })).toBeVisible();
});
