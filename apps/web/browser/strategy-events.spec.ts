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

const target = {
  target_id: "target_a", decision_session: "2026-08-03", reason: "selection",
  execution: "next_research_session_open", contract_checksum: "contract",
  allocation: { mode: "rebalance", exposure: 0.7, instrument_ids: ["equity:600000.SH"], relative_weights: { "equity:600000.SH": "1" } },
  position_limits: {},
};
const order = { target_id: "target_a", order_id: "order_a", decision_session: "2026-08-03", session: "2026-08-04", instrument_id: "equity:600000.SH", side: "buy", reason: "selection", legal_quantity: 100, rejection_reason: null };
const child = { ...order, child_order_id: "child_a", quantity: 100 };
const fill = { ...child, fill_id: "fill_a", raw_open: "10", adjusted_open: "20", execution_price: "10.01", price_slippage: "0.01", raw_notional: "1001", research_settlement: "1001", cost: "5", commission_cny: "5", stamp_duty_cny: "0", transfer_fee_cny: "0", cash_rounding_delta: "0", net_cash_delta: "-1006", adjusted_units_delta: "50", execution_shares_delta: 100 };

test("troubleshooting table preserves unknown quantities and copies the exact record", async ({ page, context }) => {
  const reads: Record<string, unknown>[] = [];
  const recorded = { ...order, intended_value: "1000.0000000000000001", unrounded_quantity: 100 };
  const suspended = { ...order, order_id: "order_suspended", instrument_id: "equity:000001.SZ", legal_quantity: null, unrounded_quantity: null, rejection_reason: "suspension" };
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: "https://events.test" });
  await page.route("https://events.test/**", route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    const query = route.request().postDataJSON() as Record<string, unknown>;
    reads.push(query);
    return route.fulfill({ json: { section: query.section, status: "recorded", rows: query.section === "strategy_targets" ? [target] : [recorded, suspended], next_cursor: null } });
  });
  await page.goto("https://events.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  expect(reads).toHaveLength(0);
  await page.getByText("Trading events", { exact: true }).click();
  const table = page.getByRole("table", { name: "委托" });
  await expect(table).toBeVisible();
  await expect(table.getByRole("row").filter({ hasText: "000001.SZ" })).toContainText("—");
  await expect(table.getByRole("row").filter({ hasText: "000001.SZ" })).toContainText("停牌");
  await expect(page.locator("pre")).toHaveCount(0);
  await table.getByRole("button", { name: /查看原始记录/ }).first().click();
  expect(JSON.parse(await page.locator("pre").innerText())).toEqual(recorded);
  await page.getByRole("button", { name: "复制 JSON", exact: true }).click();
  await expect(page.getByRole("button", { name: "已复制", exact: true })).toBeVisible();
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
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    return route.fulfill({ json: { section: "strategy_targets", status: "recorded", rows: [{
      ...target, allocation: { ...target.allocation, instrument_ids: ["equity:600000.SH", "equity:000001.SZ"],
        relative_weights: { "equity:600000.SH": weight, "equity:000001.SZ": `${BigInt(denominator) - BigInt(numerator)}/${denominator}` } },
    }], next_cursor: null } });
  });
  await page.goto("https://events.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByText("Trading events", { exact: true }).click();
  await page.getByLabel("事件类型").selectOption("strategy_targets");
  const table = page.getByRole("table", { name: "调仓目标" });
  await expect(table.getByRole("cell", { name: "2", exact: true })).toBeVisible();
  await expect(table.getByRole("cell", { name: "70.00%", exact: true })).toBeVisible();
  await expect(page.locator("pre")).toHaveCount(0);
  await table.getByRole("button", { name: /查看原始记录/ }).click();
  const raw = JSON.parse(await page.locator("pre").innerText());
  expect(raw.allocation.relative_weights["equity:600000.SH"]).toBe(weight);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await table.getByRole("button", { name: /查看原始记录/ }).click();
  await expect(page.locator("pre")).toHaveCount(0);
});

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
  await page.getByLabel("事件类型").selectOption("strategy_targets");
  await expect(page.getByText("70.00%", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.getByRole("button", { name: "下一页", exact: true })).toBeDisabled();
  expect(reads.at(-1)?.cursor).toBe("page-2");
  await page.getByRole("button", { name: "上一页", exact: true }).click();
  await expect(page.getByRole("button", { name: "下一页", exact: true })).toBeEnabled();
  await page.getByLabel("起始日期", { exact: true }).fill("2026-08-03");
  await page.getByLabel("结束日期", { exact: true }).fill("2026-08-03");
  await page.getByRole("button", { name: "查询", exact: true }).click();
  await expect.poll(() => reads.at(-1)?.end_session).toBe("2026-08-03");
  await page.getByRole("button", { name: /查看原始记录/ }).click();
  await page.getByRole("button", { name: "查看委托", exact: true }).click();
  await expect(page.getByLabel("事件类型")).toHaveValue("strategy_orders");
  await expect(page.getByRole("region", { name: "当前关联范围" })).toContainText("2026-08-03 的调仓目标");
  await expect(page.getByText("2026-08-04", { exact: true }).first()).toBeVisible();
  expect(reads.at(-1)?.target_id).toBe("target_a");
  expect(reads.at(-1)?.end_session).toBeUndefined();
  expect(reads.at(-1)?.cursor).toBeNull();
  await page.getByRole("button", { name: /查看原始记录/ }).click();
  await page.getByRole("button", { name: "查看子委托" }).click();
  await expect(page.getByLabel("事件类型")).toHaveValue("strategy_child_orders");
  await page.getByRole("button", { name: /查看原始记录/ }).click();
  await expect(page.getByRole("button", { name: "查看成交" })).toBeVisible();
  expect(reads.at(-1)?.order_id).toBe("order_a");
  await page.getByRole("button", { name: "查看成交" }).click();
  await expect(page.getByLabel("事件类型")).toHaveValue("strategy_fills");
  await expect(page.getByRole("heading", { name: "成交", exact: true })).toBeFocused();
  await expect(page.getByRole("cell", { name: "5.00", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /查看原始记录/ }).click();
  expect(JSON.parse(await page.locator("pre").innerText()).net_cash_delta).toBe("-1006");
  await expect(page.getByRole("region", { name: "成交价格与费用明细" })).toContainText("模拟成交价（元）10.01");
  await expect(page.getByRole("region", { name: "成交价格与费用明细" })).toContainText("每股滑点价差（元）0.01");
  expect(reads.at(-1)?.child_order_id).toBe("child_a");
  await expect(page.getByText("已到筛选结果末尾", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "返回子委托", exact: true }).click();
  await expect(page.getByLabel("事件类型")).toHaveValue("strategy_child_orders");
  await expect.poll(() => reads.at(-1)?.order_id).toBe("order_a");
  await page.getByRole("button", { name: "返回委托", exact: true }).click();
  await expect(page.getByLabel("事件类型")).toHaveValue("strategy_orders");
  await page.getByRole("button", { name: "返回调仓目标", exact: true }).click();
  await expect(page.getByLabel("起始日期", { exact: true })).toHaveValue("2026-08-03");
  await expect(page.getByRole("region", { name: "当前关联范围" })).toHaveCount(0);
  await page.getByRole("button", { name: /查看原始记录/ }).click();
  await page.getByRole("button", { name: "查看成交", exact: true }).click();
  await expect(page.getByRole("region", { name: "当前关联范围" })).toContainText("2026-08-03 的调仓目标");
  await page.getByRole("button", { name: "查看全部成交", exact: true }).click();
  await expect.poll(() => reads.at(-1)?.target_id).toBeUndefined();
  await expect(page.getByRole("region", { name: "当前关联范围" })).toHaveCount(0);
  await expect(page.getByText("全部日期 · 全部股票", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /查看原始记录/ }).click();
  await page.screenshot({ path: "../../.local/browser-tests/strategy-events-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "../../.local/browser-tests/strategy-events.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("execution constraints distinguish skipped, reduced and unrecorded trades", async ({ page }) => {
  const constraints = [
    { ...order, constraint_id: "constraint_reduced", mode: "rebalance", decision_reason: "selection", reason: "insufficient_cash", unrounded_quantity: 1000, legal_quantity: 1000, submitted_quantity: 900, available_cash_cny: "10000" },
    { ...order, constraint_id: "constraint_skipped", instrument_id: "equity:000001.SZ", mode: "rebalance", decision_reason: "selection", reason: "below_board_lot", unrounded_quantity: 50, legal_quantity: 0, submitted_quantity: 0, order_id: null, available_cash_cny: "500" },
  ];
  let availability = "recorded";
  const reads: Record<string, unknown>[] = [];
  await page.route("https://events.test/**", route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    const query = route.request().postDataJSON() as Record<string, unknown>;
    reads.push(query);
    return route.fulfill({ json: { section: query.section, status: availability, rows: query.section === "strategy_execution_constraints" && availability === "recorded" ? constraints : [], next_cursor: null } });
  });
  await page.goto("https://events.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByText("Trading events", { exact: true }).click();
  await page.getByLabel("事件类型").selectOption("strategy_execution_constraints");
  const table = page.getByRole("table", { name: "执行约束", exact: true });
  await expect(table.getByRole("row").filter({ hasText: "600000.SH" })).toContainText("1,0001,000900资金不足");
  await expect(page.getByRole("alert")).toHaveCount(0);
  await table.getByRole("button", { name: /000001.SZ/ }).click();
  await expect(page.getByRole("button", { name: "查看目标", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "查看委托", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "查看成交", exact: true })).toHaveCount(0);
  expect(JSON.parse(await page.locator("pre").innerText()).submitted_quantity).toBe(0);
  await table.getByRole("button", { name: /600000.SH/ }).click();
  await page.getByRole("button", { name: "查看委托", exact: true }).click();
  await expect.poll(() => reads.at(-1)?.order_id).toBe("order_a");
  availability = "not_recorded";
  await page.getByRole("button", { name: "返回执行约束", exact: true }).click();
  await expect(page.getByText("所选范围未完整记录执行约束，无法据此判断是否发生过资金或交易单位限制。")).toBeVisible();
  await expect(page.getByText("没有匹配的执行约束记录。")).toHaveCount(0);
});

test("event failures, unrecorded evidence and an empty result remain distinct", async ({ page }) => {
  let reads = 0;
  await page.route("https://events.test/**", route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    reads++;
    return route.fulfill(reads === 1 ? { status: 503 } : { json: { section: "strategy_orders", status: reads === 2 ? "not_recorded" : "recorded", rows: [], next_cursor: null } });
  });
  await page.goto("https://events.test/");
  await page.addScriptTag({ content: script });
  await page.getByText("Trading events", { exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: "重新加载首页" }).click();
  await expect(page.getByText("此结果未记录交易事件。")).toBeVisible();
  await page.getByRole("button", { name: "重新加载首页" }).click();
  await expect(page.getByText("没有匹配的委托记录。")).toBeVisible();
});

test("expired trading evidence is distinct from an empty query", async ({ page }) => {
  await page.route("https://events.test/**", route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    return route.fulfill({ json: { section: "strategy_orders", status: "expired", rows: [], next_cursor: null, expires_at: "2026-09-22T00:00:00Z" } });
  });
  await page.goto("https://events.test/");
  await page.addScriptTag({ content: script });
  await page.getByText("Trading events", { exact: true }).click();
  await expect(page.getByText("交易明细已过期。连续 7 天未查看后自动清理，收益报告和最终持仓仍然保留。")).toBeVisible();
  await expect(page.getByText("没有匹配的委托记录。")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "下一页" })).toBeDisabled();
});

test.describe("Framework touch interactions", () => {
  test.use({ hasTouch: true });

test("Framework evidence separates signal expiry, proposal, cancellation and final execution", async ({ page }) => {
  const records = [{
    decision_id: "framework_no_update", decision_session: "2026-08-03", target_id: null,
    modules: { universe_selection: "dataset_universe/v1", alpha: "python:signals", portfolio_construction: "python:portfolio", risk_management: "python:risk" },
    universe: { instrument_ids: ["equity:600000.SH"], updated: false, reason: null },
    alpha: { kind: "signals", signals: [], updated: false, reason: null,
      expired_signals: ["equity:000001.SZ"], removed_signals: [] },
    proposal: target, risk_adjustment: { mode: "replace", reason: "cooldown", target: null },
  }, {
    decision_id: "framework_target", decision_session: "2026-08-04", target_id: "target_a",
    modules: { universe_selection: "dataset_universe/v1", alpha: "alpha_formula/v1", portfolio_construction: "periodic_top_n/v1", risk_management: "no_risk/v1" },
    universe: { instrument_ids: ["equity:600000.SH"], updated: true, reason: "dataset_universe" },
    alpha: { kind: "formula", values: [{ instrument_id: "equity:600000.SH", value: 1 }] },
    proposal: target, risk_adjustment: null,
  }];
  const reads: Record<string, unknown>[] = [];
  await page.route("https://events.test/**", route => {
    if (new URL(route.request().url()).pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    const query = route.request().postDataJSON() as Record<string, unknown>;
    reads.push(query);
    return route.fulfill({ json: { section: query.section, status: "recorded",
      rows: query.section === "strategy_framework" ? records : query.section === "strategy_targets" ? [target] : [fill], next_cursor: null } });
  });
  await page.goto("https://events.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByText("Trading events", { exact: true }).click();
  await page.getByLabel("事件类型").selectOption("strategy_framework");
  const table = page.getByRole("table", { name: "Framework 决策" });
  await table.getByRole("button", { name: /查看原始记录/ }).first().click();
  await expect(page.getByRole("region", { name: "候选选择", exact: true })).toContainText("保留仍可用");
  for (const summary of await page.locator(".framework-decision-details summary").all()) {
    const bounds = await summary.boundingBox();
    expect(bounds!.height).toBeGreaterThanOrEqual(44);
    expect(bounds!.width).toBeGreaterThanOrEqual(44);
  }
  await expect(page.getByRole("region", { name: "信号", exact: true })).toContainText("本日到期：000001.SZ");
  await expect(page.getByRole("region", { name: "组合建议", exact: true })).toContainText("70.00%");
  await expect(page.getByRole("region", { name: "风险调整", exact: true })).toContainText("明确取消");
  await expect(page.getByRole("button", { name: "查看目标", exact: true })).toHaveCount(0);
  expect(JSON.parse(await page.locator("pre").innerText())).toEqual(records[0]);
  await page.screenshot({ path: "../../.local/browser-tests/framework-stage-evidence.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await table.getByRole("button", { name: /查看原始记录/ }).nth(1).click();
  await expect(page.getByRole("region", { name: "信号", exact: true })).toContainText("本日公式计算值");
  await page.getByRole("button", { name: "查看目标", exact: true }).click();
  await expect.poll(() => reads.at(-1)?.target_id).toBe("target_a");
  await page.getByRole("button", { name: /查看原始记录/ }).click();
  await page.getByRole("button", { name: "查看成交", exact: true }).click();
  await expect(page.getByRole("table", { name: "成交", exact: true })).toBeVisible();
  expect(reads.at(-1)?.target_id).toBe("target_a");
});

});
