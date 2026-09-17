import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { build } from "vite";

const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
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
        entry: fileURLToPath(new URL("./fixtures/operator-financial-status.tsx", import.meta.url)),
        formats: ["iife"],
        name: "OperatorFinancialStatusFixture",
      },
    },
  });
  if ("on" in result) throw new Error("Expected a one-off component build");
  const chunk = (Array.isArray(result) ? result : [result])
    .flatMap((bundle) => bundle.output)
    .find((output) => output.type === "chunk" && output.isEntry);
  if (chunk?.type !== "chunk") throw new Error("Missing component bundle");
  script = chunk.code;
});

for (const width of [1280, 390]) {
  test(`Financial pending indicators remain visible when statements are complete at ${width}px`, async ({ page }, testInfo) => {
    let complete = false;
    await page.setViewportSize({ width, height: 1080 });
    await page.route("http://operator.test/**", async (route) => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === "/") {
        return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
      }
      if (pathname !== "/api/operator/data/status") return route.fulfill({ status: 404 });
      return route.fulfill({ json: {
        head: {
          data_identity: "d".repeat(64), prepared_at: "2026-09-17T07:20:25Z",
          data_through_session: "2026-09-11", market_research_readiness: true,
          benchmark_research_readiness: true, industry_research_readiness: true,
          financial_research_readiness: complete ? "ready" : "ready_with_pending",
          market_coverage_start: "2010-01-04", market_last_refresh_at: "2026-09-17T07:12:54Z",
          benchmark_coverage_start: "2010-01-04", benchmark_coverage_end: "2026-09-11",
          benchmark_last_published_at: "2026-09-17T07:12:54Z",
          financial_coverage_start: "2010-01-04", financial_attempted_through_session: "2026-09-11",
          financial_complete_through_session: "2026-09-11", financial_last_refresh_at: "2026-09-17T07:17:26Z",
          financial_pending_instrument_count: 0,
          financial_indicator_pending_instrument_count: complete ? 0 : 13,
          financial_indicator_checked_through_session: "2026-09-11",
          financial_indicator_complete_through_session: complete ? "2026-09-11" : "2026-09-03",
          financial_discovery_gap_count: 0, financial_earliest_unresolved_date: null,
          industry_coverage_start: "2010-01-04", industry_observation_through_session: "2026-09-11",
          industry_last_refresh_at: "2026-09-17T07:20:25Z",
        },
        worker: { available: true, last_heartbeat_at: "2026-09-17T07:39:07Z" },
        latest_by_kind: [], operations: [], next_cursor: null,
      } });
    });
    await page.goto("http://operator.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
    const financial = page.getByRole("region", { name: "Financial data status", exact: true });
    const fact = (label: string) => financial.locator("dl > div").filter({ has: page.getByText(label, { exact: true }) });
    await expect(financial).toContainText("Financial ready with pending");
    await expect(fact("Statement companies pending").locator("dd")).toHaveText("0");
    await expect(fact("Indicator companies pending").locator("dd")).toHaveText("13");
    await expect(fact("Disclosure list complete through").locator("dd")).toHaveText("2026-09-11");
    await expect(fact("Indicators complete through").locator("dd")).toHaveText("2026-09-03");
    await financial.screenshot({ path: testInfo.outputPath("financial-pending.png") });
    complete = true;
    await page.getByRole("button", { name: "Reload", exact: true }).click();
    await expect(financial.getByText("Financial ready", { exact: true })).toBeVisible();
    await expect(fact("Indicator companies pending").locator("dd")).toHaveText("0");
    await expect(fact("Indicators complete through").locator("dd")).toHaveText("2026-09-11");
  });
}
