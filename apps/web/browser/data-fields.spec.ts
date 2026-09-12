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
    const fieldsFor = (category: string) => catalog.fields
      .filter((field) => field.research_category === category).map((field) => field.field_id);
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
          ...["market", "financial"].map((category) => ({
            family_id: category === "market" ? "equity.eod_price" : "equity.financial_pit",
            research_category: category,
            source_endpoints: category === "market" ? ["daily"] : ["balancesheet", "cashflow", "income"],
            supported_field_ids: fieldsFor(category), available_field_ids: fieldsFor(category),
            coverage_start: "2010-01-04", coverage_end: "2026-09-09", readiness: "ready",
          })),
          {
            family_id: "equity.financial_indicator", research_category: "financial",
            source_endpoints: ["fina_indicator"], supported_field_ids: ["financial.indicator.roe"],
            available_field_ids: [], coverage_start: null, coverage_end: null, readiness: "not_ready",
          },
        ],
        market_coverage: { start: "2010-01-04", end: "2026-09-09" },
        financial_coverage: {
          start: "2010-01-04", discovery_baseline_session: "2026-09-08",
          discovery_attempted_through_session: "2026-09-09",
          discovery_complete_through_session: "2026-09-09",
          historical_reconciliation_watermark: "2026-09-08",
          revision_coverage: "announcement-aligned-observed",
          seed_policy: "latest-pre-start-annual-flow-and-balance-facts",
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
    await expect(page.getByText("12 available", { exact: true })).toBeVisible();
    await expect(page.getByText("Finance partially ready", { exact: true })).toBeVisible();
    expect(requests).toEqual(["/api/data"]);
    await expect(page.locator(".signal-strip")).toHaveCount(4);
    if (width < 600) {
      for (const control of await page.locator(".data-field-filters input, .data-field-filters select").all()) {
        const bounds = await control.boundingBox();
        expect(bounds?.height).toBeGreaterThanOrEqual(44);
        expect(bounds?.width).toBeGreaterThanOrEqual(44);
      }
    }

    await page.getByRole("searchbox", { name: "Search fields" }).fill("营业总收入");
    await expect(page.locator(".data-field-table tbody tr")).toHaveCount(1);
    await expect(page.locator(".data-field-table tbody tr").first()).toContainText("revenue");
    await page.getByRole("searchbox", { name: "Search fields" }).fill("");
    await page.getByRole("combobox", { name: "Field source" }).selectOption("cashflow");
    await expect(page.locator(".data-field-table tbody tr")).toHaveCount(1);
    await expect(page.locator(".data-field-table tbody tr").first()).toContainText("operating_cash_flow");
    await page.getByRole("combobox", { name: "Field source" }).selectOption("");
    await page.getByRole("combobox", { name: "Research purpose" }).selectOption("盈利");
    await expect(page.locator(".data-field-table tbody tr")).toHaveCount(2);
    await page.getByRole("combobox", { name: "Research purpose" }).selectOption("");
    await page.getByRole("combobox", { name: "Field period" }).selectOption("latest_visible_quarterly_or_annual");
    await expect(page.locator(".data-field-table tbody tr")).toHaveCount(3);
    await page.getByRole("searchbox", { name: "Search fields" }).fill("no_matching_field");
    await expect(page.locator(".data-field-table tbody tr")).toHaveCount(0);
    await expect(page.getByText("No fields match these filters.")).toHaveCount(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}
