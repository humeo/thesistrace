import { expect, test, type Page } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";
let script: string;
let styles: string;
import { exampleDailyTrack as track } from "./fixtures/daily-track";

test.beforeAll(async () => {
  test.setTimeout(120_000);
  ({ script, styles } = await buildProductFixture(new URL("./fixtures/daily-tracks-language.tsx", import.meta.url), "DailyLanguage"));
});

test("comparison language changes preserve zoom, canvas and translated fallback names without rereading data", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const value = structuredClone(track);
  value.observation.returns = Array.from({ length: 300 }, (_, index) => ({
    session: new Date(Date.UTC(2025, 0, 1 + index)).toISOString().slice(0, 10),
    net_return: index / 1000,
  }));
  let reads = 0;
  await page.route("https://daily-compare-language.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    reads += 1;
    if (path === "/api/daily-tracks") return route.fulfill({ json: { items: [{ id: "track_ui", status: "active", seed_run_id: "run_origin", origin_session: "2025-01-01", strategy_session: "2025-10-27" }], next_cursor: null } });
    if (path.startsWith("/api/research-runs/")) return route.fulfill({ status: 503 });
    return route.fulfill({ json: value });
  });
  await page.goto("https://daily-compare-language.test/?list");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  const chart = page.getByRole("figure", { name: /Strategy comparison chart|策略比较曲线/ });
  const canvases = chart.locator("canvas");
  await expect(canvases.first()).toBeVisible();
  const plot = canvases.nth(await canvases.evaluateAll(elements => elements.reduce((largest, element, index) => element.clientWidth > elements[largest].clientWidth ? index : largest, 0)));
  const original = await plot.elementHandle();
  await plot.scrollIntoViewIfNeeded();
  async function observation(ratio: number) {
    const bounds = (await plot.boundingBox())!;
    await page.mouse.move(bounds.x + bounds.width * ratio - 3, bounds.y + 100);
    await page.mouse.move(bounds.x + bounds.width * ratio, bounds.y + 100);
    const footer = chart.locator("p[aria-live]");
    await expect(footer).toContainText("%");
    return (await footer.innerText()).match(/\d{4}-\d{2}-\d{2}|-?[\d.]+%/g);
  }
  const initial = await observation(0.7);
  await observation(0.3);
  await page.mouse.wheel(0, -600);
  await expect.poll(() => observation(0.7)).not.toEqual(initial);
  const before = [await observation(0.3), await observation(0.5), await observation(0.7)];
  const readsBefore = reads;
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(chart).toHaveAttribute("aria-label", "策略比较曲线");
  expect(await original!.evaluate(element => element.isConnected)).toBe(true);
  expect([await observation(0.3), await observation(0.5), await observation(0.7)]).toEqual(before);
  await expect(chart.locator("p[aria-live]")).toContainText("每日跟踪 ui");
  await page.getByRole("button", { name: "English", exact: true }).click();
  expect([await observation(0.3), await observation(0.5), await observation(0.7)]).toEqual(before);
  expect(reads).toBe(readsBefore);
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

test("daily metric explanations share compact hover and keyboard help without changing the observation", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const requests = await open(page);
  await page.getByRole("tab", { name: /^Holdings\b/ }).click();
  const help = page.getByRole("button", { name: "Return since tracking", exact: true });
  await expect(help.locator("svg")).toHaveCSS("width", "12px");
  const reads = requests.reads();
  await help.hover();
  const info = page.getByRole("dialog", { name: "Return since tracking", exact: true });
  await expect(info).toContainText("Since 2026-08-01");
  await help.press("Escape");
  await expect(info).toHaveCount(0);
  await expect(help).toBeFocused();
  await help.press("Enter");
  await expect(info).toBeVisible();
  await help.press("Escape");
  await expect(page.getByRole("tab", { name: /^Holdings\b/ })).toHaveAttribute("aria-selected", "true");
  expect(requests.reads()).toBe(reads);
  expect(requests.mutations()).toBe(0);
});

test("a failed track detail request shows an error instead of loading forever", async ({ page }) => {
  await page.route("https://daily-language.test/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (url.pathname === "/api/daily-tracks") return route.fulfill({ json: { items: [track], next_cursor: null } });
    return route.fulfill({ status: 503 });
  });
  await page.goto("https://daily-language.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await expect(page.getByText("DailyTrack unavailable")).toBeVisible();
  await expect(page.getByText("Loading DailyTrack…")).toHaveCount(0);
});

test("a deleted track link points back to the Daily Tracks list", async ({ page }) => {
  await page.route("https://daily-language.test/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (url.pathname === "/api/daily-tracks") return route.fulfill({ json: { items: [], next_cursor: null } });
    return route.fulfill({ status: 404 });
  });
  await page.goto("https://daily-language.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await expect(page.getByText("DailyTrack not found")).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to Daily Tracks" })).toHaveAttribute("href", "/daily-tracks");
});

test("switching retains holdings filters, open stop decision and failure state on desktop", async ({ page }) => {
  const requests = await open(page);
  await page.getByRole("tab", { name: "Holdings" }).click();
  await page.getByRole("searchbox", { name: "Filter holdings by symbol" }).fill("000001");
  await page.getByRole("tab", { name: "Overview", exact: true }).click();
  await page.getByRole("tab", { name: "Holdings" }).click();
  await expect(page.getByRole("searchbox", { name: "Filter holdings by symbol" })).toHaveValue("000001");
  const reads = requests.reads();
  for (const width of [1440, 1280]) {
    await page.setViewportSize({ width, height: 964 });
    await page.getByRole("button", { name: "简体中文", exact: true }).click();
    await expect(page.getByRole("tab", { name: "持仓" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("searchbox", { name: "按证券代码筛选持仓" })).toHaveValue("000001");
    await expect(page.getByRole("region", { name: "持仓表" })).toContainText("1,000");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("button", { name: "English", exact: true }).click();
  }
  expect(requests.reads()).toBe(reads);
  await page.getByRole("button", { name: "Source and starting account", exact: true }).click();
  expect((await page.getByRole("link", { name: "My original run", exact: true }).boundingBox())?.height).toBeGreaterThanOrEqual(44);
  await page.keyboard.press("Escape");
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
  await page.getByRole("button", { name: "Switch strategy" }).click();
  await expect(page.getByRole("menuitem", { name: "track_ui" })).toHaveAttribute("aria-current", "page");
  await page.keyboard.press("Escape");
  const chart = page.getByRole("figure", { name: /Return since tracking|跟踪开始以来收益/ });
  const canvases = chart.locator("canvas");
  // The left price axis precedes the plot in the chart library's DOM.
  const plot = canvases.nth(await canvases.evaluateAll(elements => elements.reduce((largest, element, index) => element.clientWidth > elements[largest].clientWidth ? index : largest, 0)));
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
  await page.getByRole("tab", { name: "Overview", exact: true }).click();
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
  await page.setViewportSize({ width: 1440, height: 960 });
  let failed = false;
  let empty = false;
  await page.route("https://daily-list.test/**", route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/") return route.fulfill({ contentType: "text/html", body: '<!doctype html><meta charset="utf-8"><div id="root"></div>' });
    if (failed) return route.fulfill({ status: 503 });
    if (pathname !== "/api/daily-tracks") return route.fulfill({ status: 503 });
    return route.fulfill({ json: { items: empty ? [] : ["active", "blocked", "stopping", "stopped"].map((status, index) => ({
      id: `track_${index}`, status, seed_run_id: "run_origin", result_checksum_sha256: "a".repeat(64), origin_session: "2026-08-01", strategy_session: "2026-08-20",
    })), next_cursor: null } });
  });
  await page.goto("https://daily-list.test/?list");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  const list = page.getByRole("region", { name: "Daily Tracks list", exact: true });
  await expect(list.getByRole("link")).toHaveCount(4);
  const reload = page.getByRole("button", { name: "Reload status", exact: true });
  await expect(reload).toHaveText("");
  await expect(reload.locator("svg")).toHaveAttribute("aria-hidden", "true");
  await expect(reload).toHaveCSS("width", "40px");
  await expect(reload).toHaveAttribute("data-variant", "ghost");
  await expect(list).toContainText("2026-08-20");
  expect((await list.getByRole("button", { name: "Daily Track 0", exact: true }).boundingBox())?.height).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  failed = true;
  await page.getByRole("button", { name: "Reload status", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Showing the last loaded list");
  await expect(list.getByRole("link")).toHaveCount(4);
  failed = false; empty = true;
  await reload.press("Enter");
  await expect(page.getByRole("alert")).toHaveCount(0);
  const heading = page.getByRole("heading", { name: "Your strategy watch starts with a backtest" });
  await expect(heading).toBeVisible();
  await expect(heading).toHaveCSS("font-size", "20px");
  await expect(heading).toHaveCSS("line-height", "28px");
  await expect(page.locator('[data-slot="empty-description"]')).toHaveCSS("font-size", "14px");
  await expect(page.getByRole("link", { name: "Browse Research Runs" })).toHaveAttribute("href", "/research-runs");
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(page.getByRole("heading", { name: "从一次回测开始观察策略" })).toHaveCSS("font-size", "20px");
  const translatedReload = page.getByRole("button", { name: "重新加载状态", exact: true });
  await translatedReload.hover();
  await expect(page.getByText("重新加载状态", { exact: true })).toBeVisible();
  await translatedReload.press("Escape");
  await expect(page.getByText("重新加载状态", { exact: true })).toHaveCount(0);
});

test("daily review queries the selected published session and distinguishes expired events", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const value = structuredClone(track);
  value.observation.returns = [
    { session: "2026-08-01", net_return: 0 },
    { session: "2026-08-19", net_return: 0.05 },
    { session: "2026-08-20", net_return: 0.10 },
  ];
  const queries: { section: string; start_session: string; end_session: string }[] = [];
  await open(page, value);
  await page.route("**/api/daily-tracks/track_ui/events/query", async route => {
    const body = route.request().postDataJSON(); queries.push(body);
    return route.fulfill({ json: { section: body.section, status: body.start_session === "2026-08-19" ? "expired" : "recorded", rows: [], next_cursor: null, expires_at: null } });
  });
  await page.getByRole("tab", { name: "Daily review", exact: true }).click();
  const review = page.getByRole("tabpanel", { name: "Daily review", exact: true });
  await expect(review.getByRole("group", { name: "Session result" })).toContainText("4.76%");
  await expect(review).toContainText("No records of this event type");
  expect(queries.at(-1)).toMatchObject({ section: "strategy_fills", start_session: "2026-08-20", end_session: "2026-08-20" });
  await review.getByRole("button", { name: "2026-08-19", exact: true }).click();
  await expect(review).toContainText("These event records have expired");
  await expect(review.getByRole("group", { name: "Session result" })).toContainText("10,500.00");
  expect(queries.at(-1)).toMatchObject({ start_session: "2026-08-19", end_session: "2026-08-19" });
  const count = queries.length;
  await review.getByRole("button", { name: /2026-08-01/ }).click();
  await expect(review).toContainText("This is the starting account");
  await expect(review.getByRole("group", { name: "Session result" })).toContainText("—");
  expect(queries).toHaveLength(count);
});

test("comparison selects real account previews and leaves failed observations unavailable", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const summaries = ["track_ui", "track_other", "track_failed"].map(id => ({ id, status: "active", seed_run_id: id === "track_ui" ? "run_momentum" : "run_quality", result_checksum_sha256: "a".repeat(64), origin_session: "2026-08-01", strategy_session: "2026-08-20" }));
  let mutations = 0;
  await page.route("https://daily-compare.test/**", route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (route.request().method() !== "GET") { mutations++; return route.fulfill({ status: 503 }); }
    if (pathname === "/api/daily-tracks") return route.fulfill({ json: { items: summaries, next_cursor: null } });
    if (pathname.startsWith("/api/research-runs/")) return route.fulfill({ json: { name: pathname.endsWith("run_momentum") ? "Momentum" : "Quality" } });
    if (pathname.endsWith("track_failed")) return route.fulfill({ status: 503 });
    const value = structuredClone(track);
    if (pathname.endsWith("track_other")) { value.id = "track_other"; value.observation.cash_cny = "8000"; value.observation.holdings[0].instrument_id = "600000.SH"; value.observation.holdings[0].market_value_cny = "3000"; value.observation.holdings[0].weight = 3 / 11; }
    return route.fulfill({ json: value });
  });
  await page.goto("https://daily-compare.test/?list"); await page.addStyleTag({ content: styles }); await page.addScriptTag({ content: script });
  const rows = page.getByRole("region", { name: "Strategy comparison table" });
  await expect(rows.getByRole("row", { name: /track_failed/ })).toContainText("Observation unavailable");
  await expect(rows.getByRole("row", { name: /track_failed/ })).not.toContainText("0.00%");
  await rows.getByRole("button", { name: "Quality", exact: true }).first().click();
  await expect(page.getByRole("region", { name: "Largest holdings", exact: true })).toContainText("600000.SH");
  await expect(page.getByRole("figure", { name: "Strategy comparison chart" }).locator("canvas").first()).toBeVisible();
  const visible = page.getByRole("group", { name: "Visible strategies", exact: true });
  await visible.getByRole("button", { name: "Momentum", exact: true }).click();
  await visible.getByRole("button", { name: "Quality", exact: true }).click();
  await expect(page.getByText("All strategy curves are hidden", { exact: true })).toBeVisible();
  await visible.getByRole("button", { name: "Quality", exact: true }).click();
  await expect(page.getByRole("figure", { name: "Strategy comparison chart" }).locator("canvas").first()).toBeVisible();
  await expect(rows.getByRole("link", { name: "track_other", exact: true })).toHaveAttribute("href", "/daily-tracks/track_other");
  expect(mutations).toBe(0);
});
