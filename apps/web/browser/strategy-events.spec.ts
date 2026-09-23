import { fontStylesheet, serveBrandAssets } from "./brand-assets";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { build } from "vite";

test.beforeEach(async ({ page }) => { await serveBrandAssets(page); });

let script: string;
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8")
  + readFileSync(new URL("../src/analysis/strategy-events.css", import.meta.url), "utf8");

test.beforeAll(async () => {
  const result = await build({
    configFile: false, logLevel: "silent", esbuild: { jsx: "automatic" },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, lib: {
      entry: fileURLToPath(new URL("./fixtures/strategy-events.tsx", import.meta.url)),
      formats: ["iife"], name: "StrategyEventsFixture",
    } },
  });
  if ("on" in result) throw new Error("Expected a one-off build");
  const chunk = (Array.isArray(result) ? result : [result]).flatMap(bundle => bundle.output)
    .find(output => output.type === "chunk" && output.isEntry);
  if (chunk?.type !== "chunk") throw new Error("Missing component bundle");
  script = chunk.code;
});

const target = { target_id: "target_a", decision_session: "2026-08-03", mode: "selection", exposure: 0.7, selected_instrument_ids: ["equity:600000.SH"], relative_weights: { "equity:600000.SH": "1" } };
const order = { target_id: "target_a", order_id: "order_a", decision_session: "2026-08-03", session: "2026-08-04", instrument_id: "equity:600000.SH", side: "buy", reason: "selection", legal_quantity: 100, rejection_reason: null };
const child = { ...order, child_order_id: "child_a", quantity: 100 };
const fill = { ...child, fill_id: "fill_a", raw_open: "10", adjusted_open: "20", raw_notional: "1000", research_settlement: "1000", cost: "5", net_cash_delta: "-1005", adjusted_units_delta: "50", execution_shares_delta: 100 };

test("troubleshooting table preserves unknown quantities and copies the exact record", async ({ page, context }) => {
  const reads: Record<string, unknown>[] = [];
  const recorded = { ...order, intended_value: "1000.0000000000000001", unrounded_quantity: 100 };
  const suspended = { ...order, order_id: "order_suspended", instrument_id: "equity:000001.SZ", legal_quantity: null, unrounded_quantity: null, rejection_reason: "suspension" };
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: "https://events.test" });
  await page.route("https://events.test/**", route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
    const query = route.request().postDataJSON() as Record<string, unknown>;
    reads.push(query);
    return route.fulfill({ json: { section: query.section, status: "recorded", rows: query.section === "strategy_targets" ? [target] : [recorded, suspended], next_cursor: null } });
  });
  await page.goto("https://events.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  expect(reads).toHaveLength(0);
  await page.getByText("Trading events", { exact: true }).click();
  const table = page.getByRole("table", { name: "Orders" });
  await expect(table).toBeVisible();
  await expect(table.getByRole("row").filter({ hasText: "000001.SZ" })).toContainText("—");
  await expect(table.getByRole("row").filter({ hasText: "000001.SZ" })).toContainText("Suspension");
  await expect(page.locator("pre")).toHaveCount(0);
  await table.getByRole("button", { name: /View raw record/ }).first().click();
  expect(JSON.parse(await page.locator("pre").innerText())).toEqual(recorded);
  await page.getByRole("button", { name: "Copy JSON", exact: true }).click();
  await expect(page.getByRole("button", { name: "Copied", exact: true })).toBeVisible();
  expect(JSON.parse(await page.evaluate(() => navigator.clipboard.readText()))).toEqual(recorded);
  await page.getByText("Trading events", { exact: true }).click();
  await expect(table).not.toBeVisible();
});

test("long rational weights remain exact in optional raw records without widening the page", async ({ page }) => {
  // Canonical rational weights may be longer than Number can represent.
  const numerator = "1" + "0".repeat(320);
  const denominator = "4" + "0".repeat(319) + "1";
  const weight = `${numerator}/${denominator}`;
  await page.route("https://events.test/**", route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
    return route.fulfill({ json: { section: "strategy_targets", status: "recorded", rows: [{
      ...target, signal_session: "2026-08-03", selected_instrument_ids: ["equity:600000.SH", "equity:000001.SZ"],
      relative_weights: { "equity:600000.SH": weight, "equity:000001.SZ": `${BigInt(denominator) - BigInt(numerator)}/${denominator}` },
    }], next_cursor: null } });
  });
  await page.goto("https://events.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByText("Trading events", { exact: true }).click();
  await page.getByLabel("Event type").selectOption("strategy_targets");
  const table = page.getByRole("table", { name: "Rebalance targets" });
  await expect(table.getByRole("cell", { name: "2", exact: true })).toBeVisible();
  await expect(table.getByRole("cell", { name: "70.00%", exact: true })).toBeVisible();
  await expect(page.locator("pre")).toHaveCount(0);
  await table.getByRole("button", { name: /View raw record/ }).click();
  const raw = JSON.parse(await page.locator("pre").innerText());
  expect(raw.relative_weights["equity:600000.SH"]).toBe(weight);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await table.getByRole("button", { name: /View raw record/ }).click();
  await expect(page.locator("pre")).toHaveCount(0);
});

test("trading evidence pages and follows target, order, child and fill relationships", async ({ page }) => {
  const reads: Record<string, unknown>[] = [];
  await page.route("https://events.test/**", route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
    const query = route.request().postDataJSON() as Record<string, unknown>;
    reads.push(query);
    const row = query.section === "strategy_targets" ? { ...target, target_id: query.cursor ? "target_b" : "target_a" }
      : query.section === "strategy_orders" ? order : query.section === "strategy_child_orders" ? child : fill;
    return route.fulfill({ json: { section: query.section, status: "recorded", rows: [row], next_cursor: query.section === "strategy_targets" && !query.cursor ? "page-2" : null } });
  });
  await page.goto("https://events.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  expect(reads).toHaveLength(0);
  await page.getByText("Trading events", { exact: true }).click();
  await page.getByLabel("Event type").selectOption("strategy_targets");
  await expect(page.getByText("70.00%", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
  expect(reads.at(-1)?.cursor).toBe("page-2");
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeEnabled();
  await page.getByLabel("From date", { exact: true }).fill("2026-08-03");
  await page.getByLabel("Through date", { exact: true }).fill("2026-08-03");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect.poll(() => reads.at(-1)?.end_session).toBe("2026-08-03");
  await page.getByRole("button", { name: /View raw record/ }).click();
  await page.getByRole("button", { name: "View orders", exact: true }).click();
  await expect(page.getByLabel("Event type")).toHaveValue("strategy_orders");
  await expect(page.getByRole("region", { name: "Current related scope" })).toContainText("Rebalance target for 2026-08-03");
  const beforeLanguageReads = reads.length;
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(page.getByRole("region", { name: "当前关联范围" })).toContainText("2026-08-03 的调仓目标");
  await expect(page.getByLabel("事件类型")).toHaveValue("strategy_orders");
  expect(reads).toHaveLength(beforeLanguageReads);
  await page.getByRole("button", { name: "English", exact: true }).click();

  await expect(page.getByText("2026-08-04", { exact: true }).first()).toBeVisible();
  expect(reads.at(-1)?.target_id).toBe("target_a");
  expect(reads.at(-1)?.end_session).toBeUndefined();
  expect(reads.at(-1)?.cursor).toBeNull();
  await page.getByRole("button", { name: /View raw record/ }).click();
  await page.getByRole("button", { name: "View child orders" }).click();
  await expect(page.getByLabel("Event type")).toHaveValue("strategy_child_orders");
  await page.getByRole("button", { name: /View raw record/ }).click();
  await expect(page.getByRole("button", { name: "View fills" })).toBeVisible();
  expect(reads.at(-1)?.order_id).toBe("order_a");
  await page.getByRole("button", { name: "View fills" }).click();
  await expect(page.getByLabel("Event type")).toHaveValue("strategy_fills");
  await expect(page.getByRole("heading", { name: "Fills", exact: true })).toBeFocused();
  await expect(page.getByRole("cell", { name: "5.00", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /View raw record/ }).click();
  expect(JSON.parse(await page.locator("pre").innerText()).net_cash_delta).toBe("-1005");
  expect(reads.at(-1)?.child_order_id).toBe("child_a");
  await expect(page.getByText("End of filtered results", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Back to Child orders", exact: true }).click();
  await expect(page.getByLabel("Event type")).toHaveValue("strategy_child_orders");
  await expect.poll(() => reads.at(-1)?.order_id).toBe("order_a");
  await page.getByRole("button", { name: "Back to Orders", exact: true }).click();
  await expect(page.getByLabel("Event type")).toHaveValue("strategy_orders");
  await page.getByRole("button", { name: "Back to Rebalance targets", exact: true }).click();
  await expect(page.getByLabel("From date", { exact: true })).toHaveValue("2026-08-03");
  await expect(page.getByRole("region", { name: "Current related scope" })).toHaveCount(0);
  await page.getByRole("button", { name: /View raw record/ }).click();
  await page.getByRole("button", { name: "View fills", exact: true }).click();
  await expect(page.getByRole("region", { name: "Current related scope" })).toContainText("Rebalance target for 2026-08-03");
  await page.getByRole("button", { name: "View all Fills", exact: true }).click();
  await expect.poll(() => reads.at(-1)?.target_id).toBeUndefined();
  await expect(page.getByRole("region", { name: "Current related scope" })).toHaveCount(0);
  await expect(page.getByText("All dates · All instruments", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /View raw record/ }).click();
  await page.screenshot({ path: "../../.local/browser-tests/strategy-events-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "../../.local/browser-tests/strategy-events.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("execution constraints distinguish skipped, reduced and unrecorded trades", async ({ page }) => {
  const constraints = [
    { ...order, constraint_id: "constraint_reduced", mode: "selection", reason: "insufficient_cash", unrounded_quantity: 1000, legal_quantity: 1000, submitted_quantity: 900, available_cash_cny: "10000" },
    { ...order, constraint_id: "constraint_skipped", instrument_id: "equity:000001.SZ", mode: "selection", reason: "below_board_lot", unrounded_quantity: 50, legal_quantity: 0, submitted_quantity: 0, order_id: null, available_cash_cny: "500" },
  ];
  let availability = "recorded";
  const reads: Record<string, unknown>[] = [];
  await page.route("https://events.test/**", route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
    const query = route.request().postDataJSON() as Record<string, unknown>;
    reads.push(query);
    return route.fulfill({ json: { section: query.section, status: availability, rows: query.section === "strategy_execution_constraints" && availability === "recorded" ? constraints : [], next_cursor: null } });
  });
  await page.goto("https://events.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByText("Trading events", { exact: true }).click();
  await page.getByLabel("Event type").selectOption("strategy_execution_constraints");
  const table = page.getByRole("table", { name: "Execution constraints", exact: true });
  await expect(table.getByRole("row").filter({ hasText: "600000.SH" })).toContainText("1,0001,000900Insufficient cash");
  await expect(page.getByRole("alert")).toHaveCount(0);
  await table.getByRole("button", { name: /000001.SZ/ }).click();
  await expect(page.getByRole("button", { name: "View targets", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "View orders", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "View fills", exact: true })).toHaveCount(0);
  expect(JSON.parse(await page.locator("pre").innerText()).submitted_quantity).toBe(0);
  await table.getByRole("button", { name: /600000.SH/ }).click();
  await page.getByRole("button", { name: "View orders", exact: true }).click();
  await expect.poll(() => reads.at(-1)?.order_id).toBe("order_a");
  availability = "not_recorded";
  await page.getByRole("button", { name: "Back to Execution constraints", exact: true }).click();
  await expect(page.getByText("Execution constraints were not fully recorded for this selection. Cash or trading-unit limits cannot be determined from it.")).toBeVisible();
  await expect(page.getByText("No matching Execution constraints records.")).toHaveCount(0);
});

test("event failures, unrecorded evidence and an empty result remain distinct", async ({ page }) => {
  let reads = 0;
  await page.route("https://events.test/**", route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
    reads++;
    return route.fulfill(reads === 1 ? { status: 503 } : { json: { section: "strategy_orders", status: reads === 2 ? "not_recorded" : "recorded", rows: [], next_cursor: null } });
  });
  await page.goto("https://events.test/");
  await page.addScriptTag({ content: script });
  await page.getByText("Trading events", { exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: "Reload first page" }).click();
  await expect(page.getByText("Trading events were not recorded for this result.")).toBeVisible();
  await page.getByRole("button", { name: "Reload first page" }).click();
  await expect(page.getByText("No matching Orders records.")).toBeVisible();
});

test("expired trading evidence is distinct from an empty query", async ({ page }) => {
  await page.route("https://events.test/**", route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
    return route.fulfill({ json: { section: "strategy_orders", status: "expired", rows: [], next_cursor: null, expires_at: "2026-09-22T00:00:00Z" } });
  });
  await page.goto("https://events.test/");
  await page.addScriptTag({ content: script });
  await page.getByText("Trading events", { exact: true }).click();
  await expect(page.getByText("Trading details have expired after 7 days without a read. Performance reports and final positions remain available.")).toBeVisible();
  await expect(page.getByText("No matching Orders records.")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Next" })).toBeDisabled();
});
