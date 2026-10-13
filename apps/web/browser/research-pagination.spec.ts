import { expect, test, type Page } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";

let styles: string;
let timelineScript: string;
test.beforeAll(async () => {
  ({ script: timelineScript, styles } = await buildProductFixture(new URL("./fixtures/research-pagination.tsx", import.meta.url), "ResearchPaginationFixture"));
});

const optionLabels: Record<string, string> = { factor_evaluation: "Factor Evaluation", strategy_backtest: "Strategy Backtest", annualized_excess_return: "Annualized excess", maximum_drawdown: "Max drawdown", one_session_rank_ic: "1-session Rank IC", five_session_rank_ic: "5-session Rank IC", twenty_session_rank_ic: "20-session Rank IC", gt: ">", gte: "≥", lt: "<", lte: "≤" };
async function choose(page: Page, name: string, value: string) {
  await page.getByRole("combobox", { name, exact: true }).click();
  await page.getByRole("option", { name: optionLabels[value] ?? value, exact: true }).click();
}

for (const width of [1080, 390]) {
  test(`pagination totals, filters and last page at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 964 });
    await page.route("http://research.test/**", async route => {
      const url = new URL(route.request().url());
      if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
      if (url.pathname === "/api/research-folders") return route.fulfill({ json: { items: [{ id: "folder_default", name: "Default", is_default: true, created_at: "2026-08-01T00:00:00Z" }], next_cursor: null } });
      const pageNumber = Number(url.searchParams.get("page"));
      const total = url.searchParams.get("research_kind") === "factor_evaluation" ? 0 : 21;
      const items = Array.from({ length: total === 0 ? 0 : pageNumber === 1 ? 20 : 1 }, (_, index) => ({
        id: `run_${pageNumber}_${index}`, name: `Research ${pageNumber}-${index}`, status: "succeeded", folder_id: "folder_default", created_at: "2026-09-08T00:00:00Z", start_date: "2026-08-01", end_date: "2026-08-05", formula_summary: "close", research_kind: "factor_evaluation",
      }));
      await route.fulfill({ json: { items, total_count: total } });
    });
    await page.goto("http://research.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: timelineScript });
    const nav = page.getByRole("navigation", { name: "Research Runs pages" });
    await expect(nav).toContainText("21 total · 20 per page");
    await expect(nav).toContainText("Page 1 / 2");
    await expect(nav.getByRole("button", { name: "Previous" })).toBeDisabled();
    await nav.getByRole("button", { name: "Next" }).click();
    await expect(nav).toContainText("Page 2 / 2");
    await expect(nav.getByRole("button", { name: "Next" })).toBeDisabled();
    await expect(page.getByText("Research 2-0", { exact: true })).toBeVisible();
    if (width < 768) expect(await page.getByRole("link", { name: "Research 2-0", exact: true }).evaluate(element => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44);
    await nav.getByRole("button", { name: "Previous" }).click();
    await expect(nav).toContainText("Page 1 / 2");
    await choose(page, "Filter by Type", "factor_evaluation");
    await expect(nav).toContainText("0 total · 20 per page");
    await expect(nav).toContainText("Page 0 / 0");
    await expect(nav.getByRole("button", { name: "Next" })).toBeDisabled();
    await expect(nav.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(await nav.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  });
}

test("sorts all Research on the server before paging and keeps sorting across pages", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const requests: URLSearchParams[] = [];
  const records = Array.from({ length: 21 }, (_, i) => ({
    id: `global_${i}`, name: i === 20 ? "Older highest return" : `Recent research ${i}`,
    status: "succeeded", folder_id: "folder_default", created_at: "2026-09-08T00:00:00Z",
    start_date: "2026-08-01", end_date: "2026-08-05", formula_summary: "close",
    research_kind: "strategy_backtest",
    key_metrics: { research_kind: "strategy_backtest", annualized_excess_return: i === 20 ? 0.9 : 0.1, sharpe: 1, maximum_drawdown: 0.2 },
  }));
  await page.route("http://research.test/", route => route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' }));
  await page.route("**/api/research-folders", route => route.fulfill({ json: { items: [{ id: "folder_default", name: "Default", is_default: true, created_at: "2026-08-01T00:00:00Z" }], next_cursor: null } }));
  await page.route("**/api/research-runs?*", async route => {
    const params = new URL(route.request().url()).searchParams;
    requests.push(params);
    const ordered = params.get("sort_by") === "annualized_excess_return" && params.get("sort_direction") === "descending"
      ? [records[20], ...records.slice(0, 20)] : records;
    const offset = (Number(params.get("page")) - 1) * 20;
    await route.fulfill({ json: { items: ordered.slice(offset, offset + 20), total_count: 21 } });
  });
  await page.goto("http://research.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: timelineScript });
  await choose(page, "Filter by Type", "strategy_backtest");
  const nav = page.getByRole("navigation", { name: "Research Runs pages" });
  await expect(page.getByText("Recent research 0", { exact: true })).toBeVisible();
  await expect(page.getByText("Older highest return", { exact: true })).toHaveCount(0);
  await nav.getByRole("button", { name: "Next" }).click();
  await expect(nav).toContainText("Page 2 / 2");
  await page.getByRole("button", { name: "Annualized excess", exact: true }).click();
  await expect(nav).toContainText("Page 1 / 2");
  await expect(page.locator("tbody tr").first()).toContainText("Older highest return");
  expect(requests.at(-1)?.get("sort_by")).toBe("annualized_excess_return");
  expect(requests.at(-1)?.get("sort_direction")).toBe("descending");
  await nav.getByRole("button", { name: "Next" }).click();
  await expect(nav).toContainText("Page 2 / 2");
  await expect(page.getByText("Older highest return", { exact: true })).toHaveCount(0);
  expect(requests.at(-1)?.get("sort_by")).toBe("annualized_excess_return");
  await page.getByRole("button", { name: "Annualized excess", exact: true }).click();
  await expect(nav).toContainText("Page 1 / 2");
  expect(requests.at(-1)?.get("sort_direction")).toBe("ascending");
});

test("applies percentage and factor conditions globally and clears them on Type change", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const requests: URLSearchParams[] = [];
  await page.route("http://research.test/", route => route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' }));
  await page.route("**/api/research-folders", route => route.fulfill({ json: { items: [{ id: "folder_default", name: "Default", is_default: true }], next_cursor: null } }));
  await page.route("**/api/research-runs?*", async route => {
    requests.push(new URL(route.request().url()).searchParams);
    await route.fulfill({ json: { items: [], total_count: 0 } });
  });
  await page.goto("http://research.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: timelineScript });
  await choose(page, "Filter by Type", "strategy_backtest");
  await page.getByRole("button", { name: "Metric filters", exact: true }).click();
  await page.getByRole("button", { name: "Add condition", exact: true }).click();
  await page.getByLabel("Threshold 1", { exact: true }).fill("10");
  await page.getByRole("button", { name: "Add condition", exact: true }).click();
  await choose(page, "Metric 2", "maximum_drawdown");
  await choose(page, "Comparison 2", "lt");
  await page.getByLabel("Threshold 2", { exact: true }).fill("20");
  await expect(page.getByText("Changes not applied.")).toBeVisible();
  await page.getByRole("button", { name: "Apply filters", exact: true }).click();
  await expect.poll(() => requests.at(-1)?.get("metric_filters")).toBe(JSON.stringify([
    { metric: "annualized_excess_return", operator: "gt", value: 0.1 },
    { metric: "maximum_drawdown", operator: "lt", value: 0.2 },
  ]));
  expect(requests.at(-1)?.get("page")).toBe("1");
  await expect(page.getByText("Changes not applied.")).toHaveCount(0);
  const form = page.getByRole("form", { name: "Metric filters" });
  expect(await form.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("metric-filters-desktop.png"), fullPage: true });
  await page.getByRole("combobox", { name: "Metric 2", exact: true }).click();
  await expect(page.getByRole("option")).toHaveCount(3);
  await expect(page.getByRole("option", { name: "1-session Rank IC", exact: true })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await choose(page, "Filter by Type", "factor_evaluation");
  await expect.poll(() => requests.at(-1)?.has("metric_filters")).toBe(false);
  await expect(page.getByLabel("Threshold 1", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Add condition", exact: true }).click();
  for (const metric of ["one_session_rank_ic", "five_session_rank_ic", "twenty_session_rank_ic"]) {
    await choose(page, "Metric 1", metric);
    await page.getByLabel("Threshold 1", { exact: true }).fill("0.05");
    await page.getByRole("button", { name: "Apply filters", exact: true }).click();
    await expect.poll(() => requests.at(-1)?.get("metric_filters")).toBe(JSON.stringify([
      { metric, operator: "gt", value: 0.05 },
    ]));
  }
  await choose(page, "Metric 1", "five_session_rank_ic");
  await choose(page, "Comparison 1", "gte");
  await page.getByLabel("Threshold 1", { exact: true }).fill("0.05");
  await page.getByRole("button", { name: "Apply filters", exact: true }).click();
  await expect.poll(() => requests.at(-1)?.get("metric_filters")).toBe(JSON.stringify([
    { metric: "five_session_rank_ic", operator: "gte", value: 0.05 },
  ]));
  await page.getByRole("button", { name: "Clear filters", exact: true }).click();
  await expect.poll(() => requests.at(-1)?.has("metric_filters")).toBe(false);
});

const folderList = { items: [{ id: "folder_default", name: "Default", is_default: true }], next_cursor: null };
const sampleRun = {
  id: "run_context", name: "Long research name 中文 " + "Context".repeat(16), status: "failed", failure_reason: "Execution unavailable",
  folder_id: "folder_default", created_at: "2026-09-08T00:00:00Z", start_date: "2026-08-01", end_date: "2026-08-05",
  formula_summary: "close", research_kind: "strategy_backtest",
};

test("searches globally on submit, preserves filters and language state, and clears the search", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const requests: URLSearchParams[] = [];
  await page.route("http://research.test/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (url.pathname === "/api/research-folders") return route.fulfill({ json: folderList });
    if (url.pathname === "/api/research-runs/run_context") return route.fulfill({ json: sampleRun });
    requests.push(url.searchParams);
    const search = url.searchParams.get("search");
    return route.fulfill({ json: { items: search === "no match" ? [] : [sampleRun], total_count: search ? (search === "no match" ? 0 : 1) : 21 } });
  });
  await page.goto("http://research.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: timelineScript });
  await choose(page, "Filter by Folder", "Default");
  await choose(page, "Filter by Type", "strategy_backtest");
  await page.getByRole("button", { name: "Metric filters", exact: true }).click();
  await page.getByRole("button", { name: "Add condition", exact: true }).click();
  await page.getByLabel("Threshold 1", { exact: true }).fill("10");
  await page.getByRole("button", { name: "Apply filters", exact: true }).click();
  const nav = page.getByRole("navigation", { name: "Research Runs pages" });
  await nav.getByRole("button", { name: "Next", exact: true }).click();
  await expect(nav).toContainText("Page 2 / 2");
  const search = page.getByRole("searchbox", { name: "Search research", exact: true });
  await expect(search).toHaveAttribute("placeholder", "Research name, formula keywords or notes");
  await search.fill("  动量 100%_  ");
  expect(requests.at(-1)?.has("search")).toBe(false);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(nav).toContainText("Page 1 / 1");
  expect(requests.at(-1)?.get("search")).toBe("动量 100%_");
  expect(requests.at(-1)?.get("page")).toBe("1");
  expect(requests.at(-1)?.get("folder_id")).toBe("folder_default");
  expect(requests.at(-1)?.get("research_kind")).toBe("strategy_backtest");
  expect(requests.at(-1)?.get("metric_filters")).toBe(JSON.stringify([{ metric: "annualized_excess_return", operator: "gt", value: 0.1 }]));
  await page.getByRole("link", { name: sampleRun.name, exact: true }).click();
  await page.getByRole("link", { name: "Back to Research Runs", exact: true }).click();
  await expect(search).toHaveValue("动量 100%_");
  const query = requests.at(-1)?.toString();
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(page.getByRole("searchbox", { name: "搜索研究", exact: true })).toHaveValue("动量 100%_");
  expect(requests.at(-1)?.toString()).toBe(query);
  await page.getByRole("searchbox", { name: "搜索研究", exact: true }).fill("no match");
  await page.getByRole("searchbox", { name: "搜索研究", exact: true }).press("Enter");
  await expect(page.getByText("没有符合搜索或筛选条件的研究运行。", { exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "研究运行分页" })).toContainText("第 0 / 0 页");
  await page.getByRole("button", { name: "清空搜索", exact: true }).click();
  await expect(page.getByRole("searchbox", { name: "搜索研究", exact: true })).toHaveValue("");
  await expect(page.getByRole("navigation", { name: "研究运行分页" })).toContainText("第 1 / 2 页");
  expect(requests.at(-1)?.has("search")).toBe(false);
  expect(requests.at(-1)?.get("folder_id")).toBe("folder_default");
});

test("returning from a Run keeps applied filters and page across language and width changes", async ({ page }) => {
  const requests: URLSearchParams[] = [];
  await page.route("http://research.test/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (url.pathname === "/api/research-folders") return route.fulfill({ json: folderList });
    if (url.pathname === "/api/research-runs/run_context") return route.fulfill({ json: sampleRun });
    requests.push(url.searchParams);
    return route.fulfill({ json: { items: [sampleRun], total_count: 21 } });
  });
  await page.goto("http://research.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: timelineScript });
  await choose(page, "Filter by Type", "strategy_backtest");
  await page.getByRole("button", { name: "Metric filters", exact: true }).click();
  await page.getByRole("button", { name: "Add condition", exact: true }).click();
  await page.getByLabel("Threshold 1", { exact: true }).fill("29");
  await page.getByRole("button", { name: "Apply filters", exact: true }).click();
  const pagination = page.getByRole("navigation", { name: "Research Runs pages", exact: true });
  await pagination.getByRole("button", { name: "Next", exact: true }).click();
  await expect(pagination).toContainText("Page 2 / 2");
  await page.getByRole("link", { name: sampleRun.name, exact: true }).click();
  await expect(page).toHaveURL(/\/research-runs\/run_context$/);
  await page.getByRole("link", { name: "Back to Research Runs", exact: true }).click();
  await expect(pagination).toContainText("Page 2 / 2");
  await expect(page.getByLabel("Threshold 1", { exact: true })).toHaveValue("29");
  expect(requests.at(-1)?.get("metric_filters")).toBe(JSON.stringify([{ metric: "annualized_excess_return", operator: "gt", value: 0.29 }]));
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await page.setViewportSize({ width: 320, height: 844 });
  await expect(page.getByRole("link", { name: sampleRun.name, exact: true })).toHaveAttribute("href", "/research-runs/run_context");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const scroller = page.locator('[data-slot="table-container"]');
  expect(await scroller.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true);
  await scroller.focus();
  await scroller.press("ArrowRight");
  await expect.poll(() => scroller.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
});

test("failed filter requests retain editable conditions and retry the same query", async ({ page }) => {
  let reject = false;
  const requests: URLSearchParams[] = [];
  await page.route("http://research.test/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (url.pathname === "/api/research-folders") return route.fulfill({ json: folderList });
    requests.push(url.searchParams);
    return reject ? route.fulfill({ status: 503, json: { error: "unavailable" } }) : route.fulfill({ json: { items: [sampleRun], total_count: 1 } });
  });
  await page.goto("http://research.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: timelineScript });
  await choose(page, "Filter by Type", "strategy_backtest");
  await page.getByRole("button", { name: "Metric filters", exact: true }).click();
  await page.getByRole("button", { name: "Add condition", exact: true }).click();
  await page.getByLabel("Threshold 1", { exact: true }).fill("10");
  reject = true;
  await page.getByRole("button", { name: "Apply filters", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("Threshold 1", { exact: true })).toHaveValue("10");
  const failedQuery = requests.at(-1)?.toString();
  reject = false;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByRole("link", { name: sampleRun.name, exact: true })).toBeVisible();
  expect(requests.at(-1)?.toString()).toBe(failedQuery);
});

test("an old response cannot replace a newer Type selection", async ({ page }) => {
  let release: (() => void) | undefined;
  await page.route("http://research.test/**", async route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (url.pathname === "/api/research-folders") return route.fulfill({ json: folderList });
    const kind = url.searchParams.get("research_kind");
    if (kind === "strategy_backtest") await new Promise<void>(resolve => { release = resolve; });
    return route.fulfill({ json: { items: [{ ...sampleRun, name: kind === "strategy_backtest" ? "Stale strategy" : "Current factor", research_kind: kind || "factor_evaluation" }], total_count: 1 } });
  });
  await page.goto("http://research.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: timelineScript });
  await choose(page, "Filter by Type", "strategy_backtest");
  await expect.poll(() => Boolean(release)).toBe(true);
  await choose(page, "Filter by Type", "factor_evaluation");
  await expect(page.getByRole("link", { name: "Current factor", exact: true })).toBeVisible();
  release!();
  await expect(page.getByRole("link", { name: "Stale strategy", exact: true })).toHaveCount(0);
});
