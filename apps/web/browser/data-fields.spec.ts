import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { build } from "vite";
import type { AlphaCatalog } from "../src/alphaCatalog";

const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
const catalog = JSON.parse(readFileSync(
  new URL("./fixtures/data-field-catalog.json", import.meta.url), "utf8",
)) as AlphaCatalog;
let script: string;

test.beforeAll(async () => {
  const result = await build({
    configFile: false,
    logLevel: "silent",
    esbuild: { jsx: "automatic" },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: {
      write: false,
      minify: false,
      lib: {
        entry: fileURLToPath(new URL("./fixtures/data-fields.tsx", import.meta.url)),
        formats: ["iife"],
        name: "DataFieldsFixture",
      },
    },
  });
  if ("on" in result) throw new Error("Expected a one-off Data component build");
  const chunk = (Array.isArray(result) ? result : [result])
    .flatMap((bundle) => bundle.output)
    .find((output) => output.type === "chunk" && output.isEntry);
  if (chunk?.type !== "chunk") throw new Error("Missing Data component bundle");
  script = chunk.code;
});

for (const width of [1280, 390]) {
  test(`Data fields use one snapshot, show partial sources and filter at ${width}px`, async ({ page }) => {
    const requests: string[] = [];
    const fieldsFor = (family: string) => catalog.fields
      .filter((field) => field.family_id === family).map((field) => field.field_id);
    await page.setViewportSize({ width, height: 960 });
    await page.route("http://data.test/**", async (route) => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === "/") {
        return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
      }
      requests.push(pathname);
      if (pathname !== "/api/data") return route.fulfill({ status: 404 });
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
    await page.goto("http://data.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
    await expect(page.getByText("226 available", { exact: true })).toBeVisible();
    await expect(page.getByText("Market partially ready", { exact: true })).toBeVisible();
    expect(requests).toEqual(["/api/data"]);
    await expect(page.locator(".signal-strip")).toHaveCount(4);
    if (width < 600) {
      for (const control of await page.locator(".data-field-filters input, .data-field-filters select").all()) {
        const bounds = await control.boundingBox();
        expect(bounds?.height).toBeGreaterThanOrEqual(44);
        expect(bounds?.width).toBeGreaterThanOrEqual(44);
      }
    }

    await page.getByRole("combobox", { name: "Field source" }).selectOption("fina_indicator");
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toHaveCount(163);
    await page.getByRole("searchbox", { name: "Search fields" }).fill("单季净资产收益率");
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toHaveCount(1);
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toContainText("q_roe");
    await page.getByRole("searchbox", { name: "Search fields" }).fill("");
    await page.getByRole("combobox", { name: "Field source" }).selectOption("daily_basic");
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toHaveCount(15);
    await page.getByRole("searchbox", { name: "Search fields" }).fill("自由流通换手率");
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toHaveCount(1);
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toContainText("turnover_rate_f");
    await page.getByRole("combobox", { name: "Field source" }).selectOption("");
    await page.getByRole("searchbox", { name: "Search fields" }).fill("close_raw");
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toHaveCount(1);
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toContainText("未复权收盘价");
    await page.getByRole("searchbox", { name: "Search fields" }).fill("营业总收入");
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toHaveCount(22);
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr").first()).toContainText("revenue");
    await page.getByRole("searchbox", { name: "Search fields" }).fill("");
    await page.getByRole("combobox", { name: "Field source" }).selectOption("cashflow");
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toHaveCount(11);
    await page.getByRole("searchbox", { name: "Search fields" }).fill("期末现金");
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toHaveCount(1);
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toContainText("cash_equivalents");
    await page.getByRole("searchbox", { name: "Search fields" }).fill("");
    await page.getByRole("combobox", { name: "Field source" }).selectOption("");
    await page.getByRole("combobox", { name: "Research purpose" }).selectOption("盈利");
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toHaveCount(12);
    await page.getByRole("combobox", { name: "Research purpose" }).selectOption("");
    await page.getByRole("combobox", { name: "Field period" }).selectOption("latest_visible_ttm");
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toHaveCount(19);
    await page.getByRole("combobox", { name: "Field period" }).selectOption("latest_visible_quarterly_or_annual");
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toHaveCount(19);
    await page.getByRole("searchbox", { name: "Search fields" }).fill("no_matching_field");
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toHaveCount(0);
    await expect(page.getByText("No fields match these filters.")).toHaveCount(2);
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
    await page.getByRole("searchbox", { name: "Search fields" }).fill("货币资金");
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toHaveCount(1);
    await expect(page.locator(".data-field-dataset .data-field-table tbody tr")).toContainText("monetary_funds");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}
