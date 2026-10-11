import { expect, test } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";

let timelineScript: string;
let styles: string;

test.beforeAll(async () => {
  ({ script: timelineScript, styles } = await buildProductFixture(new URL("./fixtures/research-resources.tsx", import.meta.url), "ChatTimelineFixture"));
});

test("desktop research cards retain public Python timeout and source diagnostics", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.route("http://research.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    const timedOut = path.endsWith("run_0123456789abcdef0123");
    return route.fulfill({ json: {
      id: timedOut ? "run_0123456789abcdef0123" : "run_1123456789abcdef0123",
      name: timedOut ? "Cashflow strategy" : "Dividend strategy", status: "failed",
      formula_summary: "Framework · Python Signals", start_date: "2023-09-01", end_date: "2026-09-01",
      research_kind: "strategy_backtest",
      failure_reason: timedOut
        ? "PYTHON_EXECUTION_TIMEOUT: program d57e161165ea on 2023-09-01: PythonExecutionTimeout: alpha: Python program exceeded its wall time limit"
        : "program 77f900359c48 on 2023-09-06, line 12: ValueError: weights must be positive",
    } });
  });
  await page.goto("http://research.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: timelineScript });
  await expect(page.getByRole("alert").filter({ hasText: "Python execution timed out" })).toContainText("2023-09-01");
  await expect(page.getByRole("alert").filter({ hasText: "weights must be positive" })).toContainText("line 12");
  await page.getByRole("button", { name: "简体中文" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Python 执行超时" })).toContainText("d57e161165ea");
  await expect(page.getByRole("alert").filter({ hasText: "Python 程序执行失败" })).toContainText("weights must be positive");
});


test("A2UI resource references read Core and isolate an unavailable sibling", async ({ page }) => {
  let status = "running";
  await page.route("http://research.test/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (path.endsWith("run_1123456789abcdef0123")) return route.fulfill({ status: 404 });
    const result = status === "succeeded" ? { factor: { horizons: Object.fromEntries(["1", "5", "20"].map(h => [h, { summary: { rank_ic: { mean: 0.125 } } }])) } } : undefined;
    return route.fulfill({ json: { id: "run_0123456789abcdef0123", name: "Core research", status, formula_summary: "rank(close)", start_date: "2026-01-01", end_date: "2026-08-27", research_kind: "factor_evaluation", ...(result ? { result } : {}) } });
  });
  await page.goto("http://research.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: timelineScript });
  const card = page.getByRole("region", { name: "ResearchRun run_0123456789abcdef0123", exact: true });
  await expect(card.getByRole("link", { name: "Core research", exact: true })).toBeVisible();
  await expect(card.getByText("running", { exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("Resource unavailable or access denied");
  await expect(page.getByText("Results are available after this research succeeds.")).toBeVisible();
  status = "succeeded";
  await card.getByRole("button", { name: "Reload view: Core research", exact: true }).click();
  await expect(page.getByText("0.125", { exact: true })).toHaveCount(3);
  await expect(card.getByText("succeeded", { exact: true })).toBeVisible();
  await expect(card.getByText("running", { exact: true })).toHaveCount(0);
});

for (const width of [320, 390, 768, 1280, 1440]) {
  test(`catalog table and authoritative refresh remain usable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    let failure = false;
    await page.route("http://research.test/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
      if (path.endsWith("run_1123456789abcdef0123")) return route.fulfill({ status: 403 });
      if (failure) return route.fulfill({ status: 503 });
      return route.fulfill({ json: { id: "run_0123456789abcdef0123", name: "Core research long name ".repeat(8), status: "succeeded", formula_summary: "rank(close)", start_date: "2026-01-01", end_date: "2026-08-27", research_kind: "factor_evaluation", result: { factor: { horizons: Object.fromEntries(["1", "5", "20"].map(h => [h, { summary: { rank_ic: { mean: 0.125 } } }])) } } } });
    });
    await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", { value: { writeText: async () => undefined }, configurable: true }));
    await page.goto("http://research.test/?catalog=1");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: timelineScript });
    const card = page.getByRole("region", { name: "ResearchRun run_0123456789abcdef0123", exact: true });
    await expect(card.getByText("0.125", { exact: true })).toHaveCount(3);
    const readAt = await card.locator("time").getAttribute("datetime");
    const disclosure = page.getByRole("button", { name: "Inspect sample" });
    await disclosure.focus();
    await page.keyboard.press("Enter");
    const table = page.getByRole("table", { name: "Research sample" });
    await expect(table.getByRole("cell")).toHaveCount(1200);
    const scroll = table.locator("..");
    await scroll.focus();
    await expect(scroll).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect.poll(() => scroll.evaluate(el => el.scrollLeft)).toBeGreaterThan(0);
    await page.getByRole("button", { name: "Copy", exact: true }).click();
    const formula = page.getByRole("region", { name: "Research formula", exact: true });
    await expect(formula).toContainText("Formula copied");
    failure = true;
    await card.getByRole("button", { name: "Reload view" }).click();
    await expect(card.getByRole("alert")).toBeVisible();
    await expect(card.getByText("0.125", { exact: true })).toHaveCount(3);
    await expect(card.locator("time")).toHaveAttribute("datetime", readAt!);
    await page.getByRole("button", { name: "简体中文" }).click();
    await expect(disclosure).toHaveAttribute("aria-expanded", "true");
    await expect(table.getByRole("cell")).toHaveCount(1200);
    await expect(formula).toContainText("公式已复制");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await disclosure.click();
    await expect(table).toBeHidden();
  });
}
