import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { build } from "vite";

let script: string;
const styles = ["../src/styles.css", "../src/daily-tracks/daily-tracks.css"]
  .map(path => readFileSync(new URL(path, import.meta.url), "utf8")).join("\n");
const track = {
  id: "track_ui", status: "active", checkpoint_manifest_sha256: "a".repeat(64),
  origin: { seed_run_id: "My original run", seed_research_available: true, strategy_session: "2026-08-01",
    result_checksum_sha256: "b".repeat(64), terminal_account: { net_nav: "10000", net_cash: "10000", positions: [] } },
  strategy_session: "2026-08-20", data_through_session: "2026-08-21", lag_sessions: 1,
  progress: { phase: "waiting", head_session: "2026-08-20", lag_sessions: 1, target_start_session: null,
    target_end_session: null, target_session_count: 0, completed_target_sessions: 0, current_session: null,
    cycle_attempt: null, cycle_attempt_limit: 3, retry_wait: false, next_attempt_eligible_at: null },
  blocked_reason: null, blocked_code: null,
  observation: { session: "2026-08-20", net_asset_value_cny: "11000", cash_cny: "2000", net_change_cny: "1000",
    net_return: 0.1, maximum_drawdown: 0.025, transaction_cost_cny: "27.50", session_count: 20,
    holdings: [{ instrument_id: "000001.SZ", shares: 1000, market_value_cny: "9000", weight: 9 / 11 }],
    target_selection: { signal_session: "2026-08-19", eligibility_exclusions: {} },
    target_exposure: 0.7, selection_interval: 5, pending_target_session: null, sessions_until_next_signal: 4,
    returns: Array.from({ length: 20 }, (_, index) => ({ session: `2026-08-${String(index + 1).padStart(2, "0")}`, net_return: index / 1000 })) },
  strategy: { summary: { metrics: { net_cumulative_return: 0.1, benchmark_cumulative_return: null, benchmark_cagr: null,
    annualized_excess_return: null, maximum_drawdown: { value: 0.025 }, sharpe: null, transaction_costs: { cumulative_amount: 27.50 } } },
    comparison: { status: "unavailable", reason: "benchmark_snapshot_unavailable" }, observations: [] },
};

test.beforeAll(async () => {
  const output = await build({ configFile: false, logLevel: "silent", esbuild: { jsx: "automatic" },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL("./fixtures/daily-tracks-language.tsx", import.meta.url)), formats: ["iife"], name: "DailyLanguage" } } });
  if ("on" in output) throw new Error("One-off build required");
  const entry = (Array.isArray(output) ? output : [output]).flatMap(bundle => bundle.output).find(item => item.type === "chunk" && item.isEntry);
  if (entry?.type !== "chunk") throw new Error("Missing fixture");
  script = entry.code;
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
  const reads = requests.reads();
  for (const width of [1050, 390, 320]) {
    await page.setViewportSize({ width, height: 964 });
    await page.getByRole("button", { name: "简体中文", exact: true }).click();
    await expect(page.getByRole("tab", { name: "持仓" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("searchbox", { name: "按证券代码筛选持仓" })).toHaveValue("000001");
    await expect(page.getByRole("region", { name: "持仓表" })).toContainText("1,000");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("button", { name: "English", exact: true }).click();
  }
  expect(requests.reads()).toBe(reads);
  expect(requests.mutations()).toBe(0);
  await page.locator(".track-manage summary").click();
  await page.getByRole("button", { name: "Stop DailyTrack", exact: true }).click();
  const decision = page.getByRole("dialog", { name: "Stop this DailyTrack?" });
  await decision.getByRole("button", { name: "Keep tracking" }).focus();
  await page.getByRole("button", { name: "简体中文", exact: true }).evaluate(element => (element as HTMLButtonElement).click());
  const translated = page.getByRole("dialog", { name: "停止此每日跟踪？" });
  await expect(translated.getByRole("button", { name: "继续跟踪" })).toBeFocused();
  await translated.getByRole("button", { name: "停止每日跟踪", exact: true }).click();
  await expect(translated.getByRole("alert")).toHaveText("无法停止跟踪，请重试。");
  await page.getByRole("button", { name: "English", exact: true }).evaluate(element => (element as HTMLButtonElement).click());
  await expect(decision.getByRole("alert")).toHaveText("The track could not be stopped. Please try again.");
  expect(requests.mutations()).toBe(1);
  expect(requests.reads()).toBe(reads);
});

test("tracking chart retains its zoom and data while switching display language", async ({ page }) => {
  const requests = await open(page);
  const chart = page.locator(".track-return-chart");
  const plot = chart.locator("canvas").first();
  const bounds = (await plot.boundingBox())!;
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + 100);
  await page.mouse.wheel(0, -350);
  const inspect = async () => {
    const result: string[] = [];
    for (const ratio of [0.3, 0.5, 0.7]) {
      await page.mouse.move(bounds.x + bounds.width * ratio, bounds.y + 100);
      const footer = chart.locator(".track-chart-footer > span");
      await expect(footer).toContainText("%");
      result.push((await footer.innerText()).match(/-?[\d.]+%/)![0]);
    }
    return result;
  };
  const before = await inspect();
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(chart).toHaveAttribute("aria-label", "跟踪开始以来收益");
  expect(await inspect()).toEqual(before);
  await page.getByRole("button", { name: "English", exact: true }).click();
  expect(await inspect()).toEqual(before);
  expect(requests.mutations()).toBe(0);
});
