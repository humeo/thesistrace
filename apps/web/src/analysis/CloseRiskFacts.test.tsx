import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, test } from "vitest";
import { i18n } from "../i18n";
import { CloseRiskFacts } from "./CloseRiskFacts";
import { FrameworkDecisionDetails, type FrameworkRecord } from "./FrameworkDecisionDetails";

beforeEach(async () => { await i18n.changeLanguage("zh-CN"); });
afterEach(async () => { await i18n.changeLanguage("en"); });

test("shows authoritative Close facts separately from Open performance", () => {
  const markup = renderToStaticMarkup(<CloseRiskFacts session="2026-08-05" nav="9994.9" positions={[{
    instrument_id: "equity:600001.SH", execution_shares: 1000, adjusted_units: "500",
    remaining_acquisition_cost_cny: "10005.1", holding_age: 2,
    holding_cycle_started_session: "2026-08-04", last_close_adjusted_price: "18",
  }]} />);
  for (const text of ["收盘风险净值", "9994.9", "开盘后净值", "10005.1", "2026-08-04", "持有时长（交易日）"]) {
    expect(markup).toContain(text);
  }
});

test("shows frozen stop-loss observations and preserves the execution distinction", () => {
  const row: FrameworkRecord = {
    decision_session: "2026-08-05", modules: {},
    universe: { instrument_ids: ["equity:600001.SH"], updated: true, reason: null },
    alpha: { kind: "formula", values: [] }, proposal: null, target_id: "target-1",
    risk_adjustment: { mode: "builtin_risk", reason: "stop_loss", position_limits: { "equity:600001.SH": 0 },
      observations: [{ reason: "stop_loss", instrument_id: "equity:600001.SH", remaining_acquisition_cost_cny: "1e4",
        close_market_value_cny: "8900", holding_return: "-0.11", stop_loss_threshold: "0.1",
        execution_shares: 1000, holding_age: 1 }] },
  };
  const markup = renderToStaticMarkup(<FrameworkDecisionDetails row={row} />);
  for (const text of ["风险判断依据", "10000", "8900", "-11", "10", "下一开盘尝试退出", "实际成交或拒绝"]) {
    expect(markup).toContain(text);
  }
});

test("explains a frozen holding expiry without requiring stop-loss cost fields", () => {
  const markup = renderToStaticMarkup(<FrameworkDecisionDetails row={{
    decision_session: "2026-08-05", modules: {},
    universe: { instrument_ids: ["equity:600001.SH"], updated: false, reason: null },
    alpha: { kind: "formula", values: [] }, proposal: null, target_id: "expiry-target",
    risk_adjustment: { mode: "builtin_risk", reason: "maximum_holding_period",
      position_limits: { "equity:600001.SH": 0 }, observations: [{ reason: "maximum_holding_period",
        instrument_id: "equity:600001.SH", execution_shares: 1000, holding_age: 3,
        maximum_holding_sessions: 3 }] },
  }} />);
  expect(markup).toContain("已达到最长持仓期限：3 个研究交易日");
  expect(markup).toContain("下一开盘尝试退出");
  expect(markup).not.toContain("止损阈值");
});

test("explains retained shares, occupied slots and risk exceptions from frozen observations", () => {
  const markup = renderToStaticMarkup(<FrameworkDecisionDetails row={{
    decision_session: "2026-08-05", modules: {},
    universe: { instrument_ids: [], updated: false, reason: null },
    alpha: { kind: "formula", values: [] }, target_id: "retain-target", risk_adjustment: null,
    proposal: { reason: "selection", position_limits: {}, allocation: {
      mode: "rebalance", instrument_ids: [], relative_weights: {}, exposure: 1,
      retained_instrument_ids: ["equity:600001.SH"],
    } },
    portfolio_retentions: [{ reason: "minimum_holding_period", instrument_id: "equity:600001.SH",
      execution_shares: 1000, holding_age: 1, minimum_holding_sessions: 3 }],
  }} />);
  for (const text of ["最短持仓保留依据", "未满最短 3 日", "保留 1000 股", "占用一个名额", "风险调整仍可减仓或退出"]) {
    expect(markup).toContain(text);
  }
});

test("shows cumulative intent separately from actual take-profit fills", () => {
  const markup = renderToStaticMarkup(<FrameworkDecisionDetails row={{
    decision_session: "2026-08-05", modules: {},
    universe: { instrument_ids: [], updated: false, reason: null },
    alpha: { kind: "formula", values: [] }, proposal: null, target_id: "profit-target",
    risk_adjustment: { mode: "builtin_risk", reason: "take_profit", position_limits: { "equity:600001.SH": 400 },
      observations: [{ reason: "take_profit", instrument_id: "equity:600001.SH", cycle_ended: false,
        holding_return: "0.2", profit_threshold: "0.2", cumulative_reduction: "0.6",
        baseline_execution_shares: 1000, baseline_adjusted_units: "500", target_adjusted_units: "200",
        executed_reduction_units: "150", remaining_reduction_units: "150", execution_shares: 700, position_limit: 400 }] },
  }} />);
  for (const text of ["累计减仓 60%", "首次基准 1000 股", "实际卖出 150", "待减 150", "禁止普通补仓"]) expect(markup).toContain(text);
  expect(markup).not.toContain("下一开盘尝试退出");
});

test("shows portfolio cooldown and recovery separately from actual exposure and Open history", () => {
  const row: FrameworkRecord = {
    decision_session: "2026-08-05", modules: {},
    universe: { instrument_ids: [], updated: false, reason: null },
    alpha: { kind: "formula", values: [] }, proposal: null, target_id: "cap-target",
    risk_adjustment: { mode: "builtin_risk", reason: "portfolio_drawdown", position_limits: {},
      observations: [{ reason: "portfolio_drawdown", status: "awaiting_new_portfolio",
        cycle_started_session: "2026-08-03", peak_close_nav_cny: "120000", close_risk_nav_cny: "108000",
        drawdown: "0.1", drawdown_threshold: 0.1, maximum_stock_exposure: 0.3,
        cooldown_sessions: 2, completed_cooldown_sessions: 2, triggered_session: "2026-08-03" }] },
  };
  const markup = renderToStaticMarkup(<FrameworkDecisionDetails row={row} />);
  for (const text of ["冷却结束，等待新的组合决策", "120000", "108000", "30%", "不表示实际仓位已恢复", "历史最大回撤不重置"]) expect(markup).toContain(text);
});
