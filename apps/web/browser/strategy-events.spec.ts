import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { build } from "vite";

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

test("trading evidence pages and follows target, order, child and fill relationships", async ({ page }) => {
  const reads: Record<string, unknown>[] = [];
  await page.route("https://events.test/**", route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
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
  await expect(page.getByText("70% exposure", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
  expect(reads.at(-1)?.cursor).toBe("page-2");
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeEnabled();
  await page.getByLabel("From", { exact: true }).fill("2026-08-03");
  await page.getByLabel("Through", { exact: true }).fill("2026-08-03");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect.poll(() => reads.at(-1)?.end_session).toBe("2026-08-03");
  await page.getByRole("button", { name: "View orders", exact: true }).click();
  await expect(page.getByLabel("Event type")).toHaveValue("strategy_orders");
  await expect(page.getByText("2026-08-04", { exact: true }).first()).toBeVisible();
  expect(reads.at(-1)?.target_id).toBe("target_a");
  expect(reads.at(-1)?.end_session).toBeUndefined();
  expect(reads.at(-1)?.cursor).toBeNull();
  await page.getByRole("button", { name: "View child orders" }).click();
  await expect(page.getByLabel("Event type")).toHaveValue("strategy_child_orders");
  await expect(page.getByRole("button", { name: "View fills" })).toBeVisible();
  expect(reads.at(-1)?.order_id).toBe("order_a");
  await page.getByRole("button", { name: "View fills" }).click();
  await expect(page.getByLabel("Event type")).toHaveValue("strategy_fills");
  await page.locator(".strategy-event-list summary").click();
  await expect(page.getByText("Research Settlement (CNY)", { exact: true })).toBeVisible();
  await expect(page.getByText("-1005", { exact: true })).toBeVisible();
  expect(reads.at(-1)?.child_order_id).toBe("child_a");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "../../.local/browser-tests/strategy-events.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("event failures, unrecorded evidence and an empty result remain distinct", async ({ page }) => {
  let reads = 0;
  await page.route("https://events.test/**", route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    reads++;
    return route.fulfill(reads === 1 ? { status: 503 } : { json: { section: "strategy_targets", status: reads === 2 ? "not_recorded" : "recorded", rows: [], next_cursor: null } });
  });
  await page.goto("https://events.test/");
  await page.addScriptTag({ content: script });
  await page.getByText("Trading events", { exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: "Reload first page" }).click();
  await expect(page.getByText("Trading events were not recorded for this result.")).toBeVisible();
  await page.getByRole("button", { name: "Reload first page" }).click();
  await expect(page.getByText("No targets match these filters.")).toBeVisible();
});
