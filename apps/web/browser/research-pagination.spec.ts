import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { build } from "vite";

const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
let timelineScript: string;

test.beforeAll(async () => {
  // Bundle the actual component, not a copy of its markup or resizing logic.
  // This browser test needs no server, Auth, Agent, or database.
  const result = await build({
    configFile: false,
    logLevel: "silent",
    esbuild: { jsx: "automatic" },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: {
      write: false,
      minify: false,
      lib: {
        entry: fileURLToPath(new URL("./fixtures/research-pagination.tsx", import.meta.url)),
        formats: ["iife"],
        name: "ChatTimelineFixture",
      },
    },
  });
  if ("on" in result) throw new Error("Timeline fixture must be a one-off build");
  const chunk = (Array.isArray(result) ? result : [result])
    .flatMap((bundle) => bundle.output)
    .find((output) => output.type === "chunk" && output.isEntry);
  if (chunk?.type !== "chunk") throw new Error("Timeline fixture entry is missing");
  timelineScript = chunk.code;
});


for (const width of [1080, 390]) {
  test(`pagination totals, filters and last page at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 964 });
    await page.route("http://research.test/**", async route => {
      const url = new URL(route.request().url());
      if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
      if (url.pathname === "/api/research-folders") return route.fulfill({ json: { items: [], next_cursor: null } });
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
    await nav.getByRole("button", { name: "Previous" }).click();
    await expect(nav).toContainText("Page 1 / 2");
    await page.getByLabel("Filter by Type", { exact: true }).selectOption("factor_evaluation");
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
  await page.route("**/api/research-folders", route => route.fulfill({ json: { items: [], next_cursor: null } }));
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
  await page.getByLabel("Filter by Type", { exact: true }).selectOption("strategy_backtest");
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

test("applies percentage and factor conditions globally and clears them on Type change", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 964 });
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
  await page.getByLabel("Filter by Type", { exact: true }).selectOption("strategy_backtest");
  await page.getByRole("button", { name: "Add condition", exact: true }).click();
  await page.getByLabel("Threshold 1", { exact: true }).fill("10");
  await page.getByRole("button", { name: "Add condition", exact: true }).click();
  await page.getByLabel("Metric 2", { exact: true }).selectOption("maximum_drawdown");
  await page.getByLabel("Comparison 2", { exact: true }).selectOption("lt");
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
  await page.screenshot({ path: "../../.scratch/research-global-sort/metric-filters-mobile.png", fullPage: true });
  for (const metric of ["one_session_rank_ic", "five_session_rank_ic", "twenty_session_rank_ic"]) {
    await page.getByLabel("Metric 2", { exact: true }).selectOption(metric);
    await page.getByLabel("Threshold 2", { exact: true }).fill("0.05");
    await page.getByRole("button", { name: "Apply filters", exact: true }).click();
    await expect.poll(() => requests.at(-1)?.get("metric_filters")).toBe(JSON.stringify([
      { metric: "annualized_excess_return", operator: "gt", value: 0.1 },
      { metric, operator: "lt", value: 0.05 },
    ]));
  }
  await page.getByLabel("Filter by Type", { exact: true }).selectOption("factor_evaluation");
  await expect.poll(() => requests.at(-1)?.has("metric_filters")).toBe(false);
  await expect(page.getByLabel("Threshold 1", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Add condition", exact: true }).click();
  await page.getByLabel("Metric 1", { exact: true }).selectOption("five_session_rank_ic");
  await page.getByLabel("Comparison 1", { exact: true }).selectOption("gte");
  await page.getByLabel("Threshold 1", { exact: true }).fill("0.05");
  await page.getByRole("button", { name: "Apply filters", exact: true }).click();
  await expect.poll(() => requests.at(-1)?.get("metric_filters")).toBe(JSON.stringify([
    { metric: "five_session_rank_ic", operator: "gte", value: 0.05 },
  ]));
  await page.getByRole("button", { name: "Clear filters", exact: true }).click();
  await expect.poll(() => requests.at(-1)?.has("metric_filters")).toBe(false);
});
