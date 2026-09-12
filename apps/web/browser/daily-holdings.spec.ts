import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { build } from "vite";

let script: string;
const styles = readFileSync(new URL("../src/analysis/strategy-events.css", import.meta.url), "utf8")
  + readFileSync(new URL("../src/styles.css", import.meta.url), "utf8")
  + readFileSync(new URL("../src/analysis/daily-holdings.css", import.meta.url), "utf8");

test.beforeAll(async () => {
  const result = await build({
    configFile: false, logLevel: "silent", esbuild: { jsx: "automatic" },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, lib: {
      entry: fileURLToPath(new URL("./fixtures/daily-holdings.tsx", import.meta.url)),
      formats: ["iife"], name: "DailyHoldingsFixture",
    } },
  });
  if ("on" in result) throw new Error("Expected a one-off build");
  const chunk = (Array.isArray(result) ? result : [result]).flatMap(bundle => bundle.output)
    .find(output => output.type === "chunk" && output.isEntry);
  if (chunk?.type !== "chunk") throw new Error("Missing component bundle");
  script = chunk.code;
});

const unit = { unit_id: "unit_a", source_kind: "research_run", first_session: "2026-08-03", last_session: "2026-08-04", expires_at: "2026-08-11T00:00:00Z", status: "available" };
const row = { session: "2026-08-03", instrument_id: "equity:600000.SH", execution_shares: 7000, adjusted_units: "3500", adjusted_mark: "20", market_value_cny: "70000", weight: 0.7 };

test("holdings require explicit detail reads and preserve applied filters when paging", async ({ page }) => {
  const reads: Record<string, unknown>[] = [];
  await page.route("https://holdings.test/**", route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    const query = route.request().postDataJSON() as Record<string, unknown>;
    reads.push(query);
    return route.fulfill({ json: query.section === "daily_holdings_status"
      ? { status: "recorded", units: [unit], next_cursor: null }
      : { status: "available", unit, rows: [row], coverage: { session_count: 2 }, next_cursor: query.cursor ? null : "page-2" } });
  });
  await page.goto("https://holdings.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  expect(reads).toHaveLength(0);
  await page.getByRole("button", { name: "Daily holdings", exact: false }).click();
  await expect(page.getByLabel("Recorded period")).toBeVisible();
  expect(reads.map(query => query.section)).toEqual(["daily_holdings_status"]);
  await page.getByRole("button", { name: "Check availability" }).click();
  await expect.poll(() => reads.length).toBe(2);
  expect(reads.every(query => query.section === "daily_holdings_status")).toBe(true);
  await page.getByLabel("From", { exact: true }).fill("2026-08-04");
  await page.getByLabel("Through", { exact: true }).fill("2026-08-03");
  await page.getByRole("button", { name: "Load holdings", exact: true }).click();
  await page.getByLabel("Instrument", { exact: true }).focus();
  await expect(page.getByText("Through must be on or after From.")).toBeVisible();
  expect(reads).toHaveLength(2);
  await page.locator('input[type="date"]').nth(1).fill("");
  await page.getByLabel("From", { exact: true }).fill("2026-08-03");
  await page.getByRole("button", { name: "Load holdings", exact: true }).click();
  await expect(page.getByText("70.00%", { exact: true })).toBeVisible();
  expect(reads.at(-1)?.unit_id).toBe("unit_a");
  await expect(page.getByRole("cell", { name: "7000", exact: true })).toHaveCSS("text-align", "right");
  await page.getByLabel("From", { exact: true }).fill("2026-08-04");
  await page.getByRole("button", { name: "Next holdings page" }).click();
  await expect(page.getByRole("button", { name: "Next holdings page" })).toHaveCount(0);
  expect(reads.at(-1)).toMatchObject({ cursor: "page-2", start_session: "2026-08-03" });
  const count = reads.length;
  await page.getByRole("button", { name: "Daily holdings", exact: false }).click();
  await page.getByRole("button", { name: "Daily holdings", exact: false }).click();
  await expect(page.getByText("70.00%", { exact: true })).toBeVisible();
  expect(reads).toHaveLength(count);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "../../.local/browser-tests/daily-holdings.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("expired holdings, empty holdings and request failures remain distinct", async ({ page }) => {
  let detailReads = 0;
  await page.route("https://holdings.test/**", route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    const query = route.request().postDataJSON() as Record<string, unknown>;
    if (query.section === "daily_holdings_status") return route.fulfill({ json: { status: "recorded", units: [unit], next_cursor: null } });
    detailReads++;
    return route.fulfill(detailReads === 1 ? { status: 503 } : { json: { status: detailReads === 2 ? "expired" : "available", unit, rows: [], coverage: { session_count: 2 }, next_cursor: detailReads === 3 ? "scan-more" : null } });
  });
  await page.goto("https://holdings.test/");
  await page.addScriptTag({ content: script });
  await page.getByRole("button", { name: "Daily holdings", exact: false }).click();
  await page.getByRole("button", { name: "Load holdings", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: "Load holdings", exact: true }).click();
  await expect(page.getByText("These holdings have expired. Permanent results and trading events remain available.")).toBeVisible();
  await page.getByRole("button", { name: "Load holdings", exact: true }).click();
  await expect(page.getByText("No matching holdings on this page. Continue to check the remaining dates.")).toBeVisible();
  expect(detailReads).toBe(3);
  await page.getByRole("button", { name: "Next holdings page" }).click();
  await expect(page.getByText("No holdings on this page.")).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});
