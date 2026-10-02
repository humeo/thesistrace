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
  test.setTimeout(120_000);
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

for (const width of [1000, 1776]) {
  test(`Data directory keeps one snapshot and works at ${width}px`, async ({ page }) => {
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
    await expect(page.getByRole("region", { name: "Data coverage" }).locator(":scope > div")).toHaveCount(4);
    await expect(page.getByText("Limited coverage", { exact: true })).toBeVisible();
    const coverageHelp = page.getByRole("button", { name: "Market data · Availability refers to the published data range.", exact: true });
    await expect(coverageHelp.locator("svg")).toHaveCSS("width", "12px");
    await coverageHelp.hover();
    const coverageInfo = page.getByRole("dialog", { name: "Market data", exact: true });
    await expect(coverageInfo).toContainText("Prices, volume & valuation");
    await expect(coverageInfo).toContainText("Field availability varies by instrument and date.");
    await coverageHelp.press("Escape");
    await expect(coverageInfo).toHaveCount(0);
    await coverageHelp.press("Enter");
    await expect(coverageInfo).toBeVisible();
    await coverageHelp.press("Escape");
    await expect(page.getByText("Limited coverage", { exact: true })).toBeVisible();
    await expect(page.getByRole("tab", { name: /Fields 226/ })).toBeVisible();
    await expect(page.getByRole("tab", { name: /Aggregate functions 4/ })).toBeVisible();
    await expect(page.getByRole("tab", { name: /Industry codes 31/ })).toBeVisible();
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(226);
    await expect(page.getByRole("button", { name: "Next", exact: true })).toHaveCount(0);
    expect(requests).toEqual(["/api/data"]);

    await page.getByRole("button", { name: "Financial 204", exact: true }).click();
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(204);
    await page.getByRole("searchbox", { name: "Search fields" }).fill("liabilities");
    await page.getByRole("button", { name: "Total liabilities", exact: true }).click();
    if (width === 1000) {
      await expect(page.getByRole("dialog", { name: "Field details" })).toBeVisible();
    } else {
      await expect(page.getByRole("complementary", { name: "Field details" })).toBeVisible();
    }
    await expect(fieldDetails(page)).toContainText("liabilities");
    await page.evaluate(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async () => { throw new DOMException("denied", "NotAllowedError"); } } }));
    await fieldDetails(page).getByRole("button", { name: "Copy formula name" }).click();
    await expect(fieldDetails(page).getByRole("alert")).toContainText("Copy unavailable");
    await page.evaluate(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async (value: string) => { document.documentElement.dataset.copiedValue = value; } } }));
    await fieldDetails(page).getByRole("button", { name: "Copy formula name" }).click();
    expect(await page.evaluate(() => document.documentElement.dataset.copiedValue)).toBe("liabilities");
    await expect(fieldDetails(page).getByRole("alert")).toHaveCount(0);
    await closeDetails(page);
    await page.getByRole("searchbox", { name: "Search fields" }).fill("close_raw");
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(0);
    await page.getByRole("button", { name: "All fields", exact: true }).click();
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(1);
    await fieldTable(page).getByRole("cell", { name: "close_raw" }).click();
    await expect(fieldDetails(page)).toContainText("close_raw");
    await closeDetails(page);
    await page.getByRole("button", { name: "Clear search" }).click();
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(226);
    await purpose(page, "Earnings");
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(12);
    await purpose(page, "All purposes");

    await page.getByRole("tab", { name: /Aggregate functions 4/ }).click();
    const functionSearch = page.getByRole("searchbox", { name: "Search aggregate functions" });
    const searchBounds = await functionSearch.boundingBox();
    expect(searchBounds!.width).toBeLessThanOrEqual(360);
    const functionRows = page.getByRole("button", { name: /(?:universe|industry)_(?:return|advancing_fraction)\(/ });
    await expect(functionRows).toHaveCount(4);
    for (const row of await functionRows.all()) {
      const bounds = await row.boundingBox();
      expect(bounds!.height).toBeGreaterThanOrEqual(80);
      const contentBounds = await row.locator("code").boundingBox();
      expect(contentBounds!.y + contentBounds!.height).toBeLessThanOrEqual(bounds!.y + bounds!.height);
    }
    if (width === 1776) {
      const rowBounds = await functionRows.first().boundingBox();
      const detailBounds = await page.getByRole("complementary", { name: "Function details" }).boundingBox();
      expect(detailBounds!.width).toBeGreaterThan(rowBounds!.width);
    }
    const functionDetails = page.getByRole("complementary", { name: "Function details" });
    await expect(functionDetails).toContainText("universe_return");
    await expect(functionDetails.getByText("Two positive finite Closes required; no valid members means missing.")).toBeVisible();
    const calculationNotes = functionDetails.getByRole("button", { name: "Calculation notes" });
    const example = functionDetails.getByRole("button", { name: "Example", exact: true });
    await expect(calculationNotes).toHaveAttribute("aria-expanded", "true");
    await expect(example).toHaveAttribute("aria-expanded", "true");
    await expect(functionDetails.getByText(/Calculated from historical members of your selected research Universe/)).toBeVisible();
    await expect(functionDetails.getByText("universe_return()", { exact: true }).last()).toBeVisible();
    const functionList = page.getByRole("group", { name: "Aggregate functions", exact: true });
    const expandedListBounds = await functionList.boundingBox();
    const lastRowBounds = await functionRows.last().boundingBox();
    expect(expandedListBounds!.y + expandedListBounds!.height).toBeLessThanOrEqual(lastRowBounds!.y + lastRowBounds!.height + 1);
    await calculationNotes.press("Enter");
    await example.press("Enter");
    await expect(functionDetails.getByText(/Calculated from historical members of your selected research Universe/)).not.toBeVisible();
    await expect(example).toHaveAttribute("aria-expanded", "false");
    const collapsedListBounds = await functionList.boundingBox();
    expect(collapsedListBounds!.height).toBeCloseTo(expandedListBounds!.height, 0);
    await page.getByRole("button", { name: "Industry return industry_return(sw2021_l1)", exact: true }).press("Enter");
    await expect(functionDetails).toContainText("SW2021 L1 members within the selected research Universe");
    await functionDetails.getByRole("button", { name: "Copy expression" }).click();
    expect(await page.evaluate(() => document.documentElement.dataset.copiedValue)).toBe("industry_return(sw2021_l1)");
    await functionSearch.fill("no-such-function");
    await expect(page.getByText("No matching aggregate functions.", { exact: true })).toBeVisible();
    await expect(functionDetails).toHaveCount(0);
    await page.getByRole("button", { name: "Clear search" }).click();
    await expect(functionRows).toHaveCount(4);
    await expect(functionSearch).toBeFocused();
    await page.getByRole("searchbox", { name: "Search aggregate functions" }).fill("industry_advancing_fraction");
    await expect(page.getByRole("button", { name: /industry_advancing_fraction/ })).toHaveCount(1);
    await expect(page.getByRole("complementary", { name: "Function details" })).toContainText("0–1");
    await expect(page.getByRole("complementary", { name: "Function details" })).not.toContainText("> 0,");
    await page.getByRole("tab", { name: /Industry codes 31/ }).click();
    await page.getByRole("searchbox", { name: "Search industry codes" }).fill("801010");
    await expect(page.getByRole("listitem")).toHaveCount(1);
    await page.getByRole("button", { name: "Copy industry code 801010" }).click();
    expect(await page.evaluate(() => document.documentElement.dataset.copiedValue)).toBe("801010");
    await page.getByRole("searchbox", { name: "Search industry codes" }).fill("农林牧渔");
    await expect(page.getByRole("listitem")).toHaveCount(1);
    await page.getByRole("button", { name: "简体中文", exact: true }).click();
    await expect(page.getByRole("tab", { name: /行业代码 31/ })).toBeVisible();
    await page.getByRole("tab", { name: /字段 226/ }).click();
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(226);
    await page.getByRole("button", { name: "English", exact: true }).click();
    expect(requests).toEqual(["/api/data"]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(await page.evaluate(() => document.documentElement.clientWidth));
    unavailable = true;
    await page.getByRole("button", { name: "Reload status" }).click();
    await expect(page.getByRole("alert")).toContainText("Data unavailable");
    await expect(fieldTable(page).locator("tbody tr")).toHaveCount(226);
    unavailable = false;
    await page.getByRole("button", { name: "Reload status" }).click();
    await expect(page.getByRole("alert")).toHaveCount(0);
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
  await expect(editor.locator(".cm-placeholder")).toHaveText("rank(pct_change(close, 20))");
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
