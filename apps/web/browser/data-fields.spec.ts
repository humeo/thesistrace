import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";
import type { AlphaCatalog } from "../src/alphaCatalog";
import { fontStylesheet, serveBrandAssets } from "./brand-assets";

let styles: string;
const catalog = JSON.parse(readFileSync(
  new URL("./fixtures/data-field-catalog.json", import.meta.url), "utf8",
)) as AlphaCatalog;
let script: string;

test.beforeAll(async () => {
  ({ script, styles } = await buildProductFixture(new URL("./fixtures/data-fields.tsx", import.meta.url), "DataFieldsFixture"));
});

const fieldTable = (page: Page) => page.getByRole("table", { name: /Research fields|研究字段/, exact: true });
const fieldDetails = (page: Page) => page.getByRole("complementary", { name: /Field details|字段详情/ }).or(page.getByRole("dialog", { name: /Field details|字段详情/ }));
async function closeDetails(page: Page) {
  const drawer = page.getByRole("dialog", { name: /Field details|字段详情/ });
  if (await drawer.count()) { await page.keyboard.press("Escape"); await expect(drawer).toHaveCount(0); await expect(fieldTable(page).getByRole("button", { pressed: true })).toBeFocused(); }
}
async function purpose(page: Page, label: string) {
  await page.getByRole("combobox", { name: "Research purpose" }).click();
  await page.getByRole("option", { name: label, exact: true }).click();
}

for (const width of [1440, 1280, 768, 390, 320]) {
  test(`Data fields use one snapshot, show partial sources and filter at ${width}px`, async ({ page }) => {
    const requests: string[] = [];
    let unavailable = false;
    const fieldsFor = (family: string) => catalog.fields
      .filter((field) => field.family_id === family).map((field) => field.field_id);
    await page.setViewportSize({ width, height: 960 });
    await page.route("http://data.test/**", async (route) => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === "/") {
        return route.fulfill({ contentType: "text/html", body: `<!doctype html>${fontStylesheet}<div id="root"></div>` });
      }
      requests.push(pathname);
      if (pathname !== "/api/data") return route.fulfill({ status: 404 });
      if (unavailable) return route.fulfill({ status: 503 });
      return route.fulfill({ json: {
        catalog,
        generation_manifest_sha256: "a".repeat(64),
        available_field_ids: catalog.fields.map((field) => field.field_id),
        field_families: [
          ...["equity.eod_price", "equity.daily_basic", "equity.financial_pit", "equity.financial_indicator"].map((family) => ({
            family_id: family,
            research_category: family.startsWith("equity.financial_") ? "financial" : "market",
            source_endpoints: family === "equity.daily_basic" ? ["daily_basic"]
              : family === "equity.eod_price" ? ["daily"]
              : family === "equity.financial_indicator" ? ["fina_indicator"] : ["balancesheet", "cashflow", "income"],
            supported_field_ids: fieldsFor(family), available_field_ids: fieldsFor(family),
            coverage_start: "2010-01-04",
            coverage_end: family === "equity.daily_basic" ? "2026-09-08" : "2026-09-09",
            readiness: family === "equity.daily_basic" ? "partial" : "ready",
          })),
        ],
        market_coverage: { start: "2010-01-04", end: "2026-09-09" },
        financial_coverage: {
          start: "2010-01-04", discovery_baseline_session: "2026-09-08",
          discovery_attempted_through_session: "2026-09-09",
          discovery_complete_through_session: "2026-09-09",
          historical_reconciliation_watermark: "2026-09-08",
          revision_coverage: "announcement-aligned-observed",
          seed_policy: "latest-pre-start-annual-flow-and-reported-stock-facts",
          readiness_status: "ready", pending_instrument_count: 0,
          discovery_gap_count: 0, earliest_unresolved_date: null, sparse_facts: true,
        },
        industry_coverage: null, benchmark_coverage: null,
        benchmark_snapshot_sha256: null, benchmark_last_published_at: null,
        data_through_session: "2026-09-09", last_market_refresh_at: null,
        last_financial_refresh_at: null, last_industry_refresh_at: null,
        industry_refresh_status: null, industry_refresh_failure_code: null,
        market_research_readiness: true, financial_research_readiness: "ready",
        benchmark_research_readiness: false, industry_research_readiness: false,
      } });
    });
    await serveBrandAssets(page);
    await page.goto("http://data.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
    await expect(page.getByText("226 fields", { exact: true })).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await expect(page.getByText("Limited coverage", { exact: true })).toBeVisible();
    expect(requests).toEqual(["/api/data"]);
    await expect(page.getByRole("region", { name: "Data coverage", exact: true }).locator("tbody tr")).toHaveCount(4);
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(25);
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "Showing" })).toHaveText("Showing 26–50 of 226");
    const secondPageIdentifiers = await fieldTable(page).locator("tbody td:nth-child(2)").allTextContents();
    await page.getByText("简体中文", { exact: true }).evaluate(element => (element as HTMLButtonElement).click());
    await expect(page.getByRole("status").filter({ hasText: "显示第" })).toHaveText("显示第 26–50 项，共 226 项");
    expect(await fieldTable(page).locator("tbody td:nth-child(2)").allTextContents()).toEqual(secondPageIdentifiers);
    await page.getByRole("button", { name: "English", exact: true }).click();
    await page.getByRole("button", { name: "Previous", exact: true }).click();
    await page.getByRole("button", { name: "Financial 204", exact: true }).click();
    const liabilities = page.getByRole("row").filter({ has: page.getByRole("button", { name: "Total liabilities", exact: true }) });
    await liabilities.getByRole("cell", { name: "liabilities", exact: true }).click();
    await expect(fieldDetails(page).getByRole("heading", { level: 3 })).toHaveText("Total liabilities");
    await page.evaluate(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async () => { throw new DOMException("denied", "NotAllowedError"); } } }));
    await fieldDetails(page).getByRole("button", { name: "Copy formula name", exact: true }).click();
    await expect(fieldDetails(page).getByRole("alert")).toContainText("Copy unavailable");
    await expect(page.getByText("Copied", { exact: true })).toHaveCount(0);
    if (width === 1280) {
      await page.setViewportSize({ width: 390, height: 960 });
      await expect(page.getByRole("dialog", { name: "Field details", exact: true })).toBeVisible();
      await expect(fieldDetails(page).getByRole("heading", { level: 3 })).toHaveText("Total liabilities");
      await expect(fieldDetails(page).getByRole("alert")).toContainText("Copy unavailable");
      await page.setViewportSize({ width: 1280, height: 960 });
      await expect(page.getByRole("dialog", { name: "Field details", exact: true })).toHaveCount(0);
      await expect(page.getByRole("complementary", { name: "Field details", exact: true })).toBeVisible();
      expect((await fieldDetails(page).boundingBox())?.width).toBe(320);
      await expect(fieldDetails(page).getByRole("alert")).toContainText("Copy unavailable");
    }

    await page.evaluate(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async (value: string) => { document.documentElement.dataset.copiedValue = value; } } }));
    await fieldDetails(page).getByRole("button", { name: "Copy formula name", exact: true }).click();
    await expect(page.getByText("Copied", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.dataset.copiedValue)).toBe("liabilities");
    await expect(fieldDetails(page).getByRole("alert")).toHaveCount(0);

    await closeDetails(page);
    await page.getByRole("button", { name: "Total assets", exact: true }).press("Enter");
    await expect(fieldDetails(page).getByRole("heading", { level: 3 })).toHaveText("Total assets");
    await closeDetails(page);
    await liabilities.getByRole("cell", { name: "CNY", exact: true }).click({ position: { x: 2, y: 2 } });
    await expect(fieldDetails(page).getByRole("heading", { level: 3 })).toHaveText("Total liabilities");
    await closeDetails(page);
    if (width === 1280) {
      await page.getByRole("button", { name: "Next", exact: true }).click();
      await expect(page.getByRole("status").filter({ hasText: "Showing" })).toHaveText("Showing 26–50 of 204");
      await page.setViewportSize({ width: 390, height: 960 });
      await expect(page.getByRole("dialog", { name: "Field details", exact: true })).toBeVisible();
      await closeDetails(page);
      await page.setViewportSize({ width: 1280, height: 960 });
      await page.getByRole("button", { name: "Previous", exact: true }).click();
    }
    await page.getByRole("searchbox", { name: "Search fields" }).fill("no_matching_field");
    await page.getByRole("button", { name: "Clear search", exact: true }).click();
    await expect(page.getByRole("searchbox", { name: "Search fields" })).toHaveValue("");
    await expect(page.getByRole("searchbox", { name: "Search fields" })).toBeFocused();
    await expect(page.getByRole("status").filter({ hasText: "Showing" })).toHaveText("Showing 1–25 of 204");
    await expect(page.getByRole("button", { name: "Clear search", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "All fields", exact: true }).click();
    await expect(page.getByText("More filters", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Source & calculation", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("combobox")).toHaveCount(1);
    await page.getByRole("combobox", { name: "Research purpose" }).click();
    await expect(page.getByRole("option", { name: "All purposes", exact: true })).toHaveCount(1);
    await page.keyboard.press("Escape");
    if (width < 600) {
      for (const control of await page.getByRole("combobox", { name: "Research purpose" }).all()) {
        const bounds = await control.boundingBox();
        expect(bounds?.height).toBeGreaterThanOrEqual(44);
        expect(bounds?.width).toBeGreaterThanOrEqual(44);
      }
    }

    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(25);
    await page.getByRole("searchbox", { name: "Search fields" }).fill("单季净资产收益率");
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(1);
    await expect(fieldTable(page).locator("tbody tr")).toContainText("q_roe");
    await page.getByRole("searchbox", { name: "Search fields" }).fill("");
    await page.getByRole("searchbox", { name: "Search fields" }).fill("自由流通换手率");
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(1);
    await expect(fieldTable(page).locator("tbody tr")).toContainText("turnover_rate_f");
    await page.getByRole("searchbox", { name: "Search fields" }).fill("close_raw");
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(1);
    await expect(fieldTable(page).locator("tbody tr")).toContainText("Unadjusted close");
    await page.getByRole("searchbox", { name: "Search fields" }).fill("营业总收入");
    // Chinese descriptions now also find turnover ratios whose denominator is total revenue.
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(25);
    await expect(page.getByRole("status").filter({ hasText: "Showing" })).toHaveText("Showing 1–25 of 27");
    await expect(fieldTable(page).locator("tbody tr").first()).toContainText("revenue");
    await page.getByRole("searchbox", { name: "Search fields" }).fill("");
    await page.getByRole("searchbox", { name: "Search fields" }).fill("期末现金");
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(1);
    await expect(fieldTable(page).locator("tbody tr")).toContainText("cash_equivalents");
    await page.getByRole("searchbox", { name: "Search fields" }).fill("");
    await purpose(page, "Earnings");
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(12);
    await purpose(page, "All purposes");
    await page.getByRole("searchbox", { name: "Search fields" }).fill("no_matching_field");
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(0);
    await expect(page.getByText("No fields match these filters.")).toHaveCount(1);
    await expect(fieldDetails(page)).toHaveCount(0);
    await page.getByRole("searchbox", { name: "Search fields" }).fill("close_raw");
    await page.getByRole("button", { name: "Unadjusted close", exact: true }).click();
    await expect(fieldDetails(page)).toContainText("close_raw");
    await expect(fieldDetails(page)).toContainText("Missing values");
    await closeDetails(page);
    await page.getByRole("button", { name: "Financial 204", exact: true }).click();
    await expect(page.getByText("No fields match these filters.")).toBeVisible();
    await page.getByRole("button", { name: "All fields", exact: true }).click();
    await purpose(page, "Market prices");
    await page.getByRole("searchbox", { name: "Search fields" }).fill("Unadjusted close");
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(1);
    await page.getByRole("button", { name: "Unadjusted close", exact: true }).click();
    await page.getByText("简体中文", { exact: true }).evaluate(element => (element as HTMLButtonElement).click());
    await expect(fieldDetails(page)).toContainText("close_raw");
    await expect(fieldDetails(page).getByRole("heading", { level: 3 })).toHaveText("未复权收盘价");
    await closeDetails(page);
    await expect(page.getByRole("searchbox", { name: "搜索字段" })).toHaveValue("Unadjusted close");
    await expect(page.getByRole("combobox", { name: "研究用途" })).toContainText("行情");
    await page.getByRole("searchbox", { name: "搜索字段" }).fill("未复权收盘价");
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(1);
    await page.getByRole("searchbox", { name: "搜索字段" }).fill("close_raw");
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(await page.evaluate(() => document.documentElement.clientWidth));
    await page.screenshot({ path: test.info().outputPath(`data-zh-${width}.png`), fullPage: true });
    await page.getByRole("button", { name: "English", exact: true }).click();
    await expect(page.getByRole("combobox", { name: "Research purpose" })).toContainText("Market prices");
    expect(requests).toEqual(["/api/data"]);
    await purpose(page, "All purposes");
    const editor = page.locator(".cm-content");
    await editor.click();
    await editor.pressSequentially("turnover_rate_");
    const turnover = page.getByRole("option").filter({ hasText: "turnover_rate_f" });
    await expect(turnover).toBeVisible();
    await turnover.click();
    await expect(editor).toHaveText("turnover_rate_f");
    await editor.press("ControlOrMeta+A");
    await editor.press("Backspace");
    await editor.pressSequentially("close_r");
    const rawClose = page.getByRole("option").filter({ hasText: "close_raw" });
    await expect(rawClose).toBeVisible();
    await rawClose.click();
    await expect(editor).toHaveText("close_raw");
    await editor.press("ControlOrMeta+A");
    await editor.press("Backspace");
    await editor.pressSequentially("cash_equ");
    const cash = page.getByRole("option").filter({ hasText: "cash_equivalents" });
    await expect(cash).toBeVisible();
    await cash.click();
    await expect(editor).toHaveText("cash_equivalents");
    await editor.press("ControlOrMeta+A");
    await editor.press("Backspace");
    await editor.pressSequentially("q_ro");
    const quarterRoe = page.getByRole("option").filter({ hasText: "q_roe" });
    await expect(quarterRoe).toBeVisible();
    await quarterRoe.click();
    await expect(editor).toHaveText("q_roe");
    await page.getByRole("searchbox", { name: "Search fields" }).fill("monetary_funds");
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(1);
    await expect(fieldTable(page).locator("tbody tr")).toContainText("monetary_funds");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(await page.evaluate(() => document.documentElement.clientWidth));
    unavailable = true;
    await page.getByRole("button", { name: "Reload status", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("Data unavailable");
    await expect(page.getByRole("searchbox", { name: "Search fields" })).toHaveValue("monetary_funds");
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(1);
    unavailable = false;
    await page.getByRole("button", { name: "Reload status", exact: true }).click();
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect(page.getByRole("searchbox", { name: "Search fields" })).toHaveValue("monetary_funds");

  });
}

test("editor language changes preserve the formula, selection and undo history", async ({ page }) => {
  await page.route("http://data.test/**", route => route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' }));
  await page.goto("http://data.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  const editor = page.locator(".cm-content");
  await editor.click();
  await editor.pressSequentially("rank(close)");
  await editor.press("ControlOrMeta+A");
  await expect(page.getByLabel("Editor selection")).toHaveText("0:11");
  // Dispatching the existing language control retains editor focus while the locale updates.
  await page.getByRole("button", { name: "简体中文", exact: true }).dispatchEvent("click");
  await expect(editor).toHaveAttribute("aria-label", "Alpha 公式");
  await expect(editor).toBeFocused();
  await expect(editor).toHaveText("rank(close)");
  await expect(page.getByLabel("Editor selection")).toHaveText("0:11");
  await editor.press("ControlOrMeta+z");
  await expect(editor.locator(".cm-placeholder")).toHaveText("从字段或函数开始");
  await editor.press("ControlOrMeta+Shift+z");
  await expect(editor).toHaveText("rank(close)");
  await editor.press("ControlOrMeta+A");
  await editor.pressSequentially("industry_r");
  await expect(page.getByRole("listbox", { name: "补全建议" })).toBeVisible();
  await expect(page.getByText(/在所选研究股票池内，限定指定 SW2021 一级行业/)).toBeVisible();
  await page.getByRole("button", { name: "English", exact: true }).dispatchEvent("click");
  await expect(page.getByRole("listbox", { name: "Completions" })).toBeVisible();
  await expect(page.getByText(/Within the selected research Universe, restricted to the specified SW2021/)).toBeVisible();
  await expect(editor).toBeFocused();
  await expect(editor).toHaveText("industry_r");
  const industry = page.getByRole("option").filter({ hasText: "industry_return" });
  await industry.click();
  await expect(editor).toHaveText("industry_return");
  await page.getByRole("button", { name: "Show diagnostic" }).click();
  const invalidWindow = page.locator(".cm-lintRange-error");
  await expect(invalidWindow).toHaveText("0");
  await invalidWindow.hover();
  await expect(page.getByText("Window must be between 1 and 252; received 0.")).toBeVisible();
  await page.getByText("简体中文", { exact: true }).evaluate(element => (element as HTMLButtonElement).click());
  await expect(invalidWindow).toHaveText("0");
  await invalidWindow.hover();
  await expect(page.getByText("窗口必须在 1 到 252 之间，实际为 0。")).toBeVisible();
  await expect(editor).toHaveText("ts_mean(close, 0)");
  await page.getByRole("button", { name: "Show Unicode diagnostic" }).click();
  await expect(invalidWindow).toHaveText("𠮷");
  await invalidWindow.hover();
  await expect(page.getByText("未知 Alpha 标识：𠮷")).toBeVisible();
});
