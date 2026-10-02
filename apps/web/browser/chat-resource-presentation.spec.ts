import { expect, test } from "@playwright/test";
import { buildModuleProductFixture } from "./build-product-fixture";

let files: Awaited<ReturnType<typeof buildModuleProductFixture>>;
test.use({ viewport: { width: 1552, height: 942 } });
test.beforeAll(async () => {
  test.setTimeout(60_000);
  files = await buildModuleProductFixture(new URL("./fixtures/chat-resources.tsx", import.meta.url));
});
test.beforeEach(async ({ page }) => {
  await page.route("https://resources.fixture/**", route => {
    const path = new URL(route.request().url()).pathname.slice(1) || "index.html";
    if (path.startsWith("api/research-runs/")) return route.fulfill({ json: {
      id: path.split("/").at(-1), name: path.includes("run_1") ? "5-day reversal" : path.includes("run_2") ? "Pending research" : "20-day momentum",
      status: path.includes("run_2") ? "queued" : "succeeded", research_kind: path.includes("run_1") ? "strategy_backtest" : "factor_evaluation",
      formula_summary: "rank(pct_change(close, 20))", start_date: "2026-01-01", end_date: "2026-09-30",
      result: path.includes("run_2") ? undefined : path.includes("run_1")
        ? { strategy: { summary: { metrics: { annualized_excess_return: 0.2, sharpe: 1.234, maximum_drawdown: { value: 0.12 } } } } }
        : { factor: { horizons: Object.fromEntries(["1", "5", "20"].map(h => [h, { summary: { rank_ic: { mean: 0.125 } } }])) } },
    } });
    const asset = files.get(path);
    return asset ? route.fulfill(asset) : route.fulfill({ status: 404 });
  });
  await page.goto("https://resources.fixture/");
});

test("research results use compact ordered list rows with links and inline metrics", async ({ page }) => {
  const list = page.getByRole("list");
  const rows = list.getByRole("listitem");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0).getByRole("link", { name: "20-day momentum", exact: true })).toHaveAttribute("href", "/research-runs/run_0123456789abcdef0123");
  await expect(rows.nth(1).getByRole("link", { name: "5-day reversal", exact: true })).toHaveAttribute("href", "/research-runs/run_1123456789abcdef0123");
  await expect(rows.nth(0)).toContainText("1S Rank IC 0.125");
  await expect(rows.nth(1)).toContainText("20.00%");
  await expect(rows.nth(1)).toContainText("1.234");
  await expect(rows.nth(2)).toContainText("Results are available after this research succeeds.");
  await expect(page.locator(".ant-card, .ant-statistic")).toHaveCount(0);
  expect((await list.boundingBox())!.width).toBe(768);
  expect((await rows.nth(0).boundingBox())!.height).toBeLessThan(100);
  const metrics = rows.nth(0).getByLabel("20-day momentum", { exact: true });
  await expect(metrics).toHaveCSS("font-size", "14px");
  const scroll = await page.locator(".ant-listy").evaluate(element => ({ height: element.clientHeight, scrollHeight: element.scrollHeight }));
  expect(scroll.scrollHeight).toBe(scroll.height);
  const reload = rows.nth(0).getByRole("button", { name: "Reload view: 20-day momentum", exact: true });
  await reload.focus();
  await page.keyboard.press("Enter");
  await expect(rows.nth(0)).toContainText("0.125");
});

test("A2UI text uses one layout gap without stacking paragraph and heading margins", async ({ page }) => {
  const intro = (await page.getByText("The authoritative research results are ready.", { exact: true }).boundingBox())!;
  const heading = (await page.getByRole("heading", { name: "Factor comparison", exact: true }).boundingBox())!;
  const list = (await page.getByRole("list").boundingBox())!;
  expect(Math.abs(heading.y - intro.y - intro.height - 16)).toBeLessThanOrEqual(1);
  expect(Math.abs(list.y - heading.y - heading.height - 16)).toBeLessThanOrEqual(1);
  const firstRow = (await page.getByRole("region", { name: "ResearchRun run_0123456789abcdef0123", exact: true }).boundingBox())!;
  expect(Math.abs(firstRow.y - list.y)).toBeLessThanOrEqual(1);
  await expect(page.getByRole("heading", { name: "Factor comparison" })).toHaveCSS("font-size", "16px");
  await expect(page.getByRole("heading", { name: "Factor comparison" })).toHaveCSS("font-weight", "600");
});
