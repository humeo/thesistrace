import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { CloseRiskFacts } from "./CloseRiskFacts";
import { FrameworkDecisionDetails, type FrameworkRecord } from "./FrameworkDecisionDetails";

test("shows authoritative Close facts separately from Open performance", () => {
  const markup = renderToStaticMarkup(<CloseRiskFacts session="2026-08-05" nav="9994.9" positions={[{
    instrument_id: "equity:600001.SH", execution_shares: 1000, adjusted_units: "500",
    remaining_acquisition_cost_cny: "10005.1", holding_age: 2,
    holding_cycle_started_session: "2026-08-04", last_close_adjusted_price: "18",
  }]} />);
  for (const text of ["Close Risk NAV", "9994.9", "post-Open NAV", "10005.1", "2026-08-04", "Holding age (trading sessions)"]) {
    expect(markup).toContain(text);
  }
});

test("shows frozen stop-loss observations and preserves the execution distinction", () => {
  const row: FrameworkRecord = {
    decision_session: "2026-08-05", modules: {},
    universe: { instrument_ids: ["equity:600001.SH"], updated: true, reason: null },
    alpha: { kind: "formula", values: [] }, proposal: null, target_id: "target-1",
    risk_adjustment: { mode: "holding_risk", reason: "stop_loss", position_limits: { "equity:600001.SH": 0 },
      observations: [{ reason: "stop_loss", instrument_id: "equity:600001.SH", remaining_acquisition_cost_cny: "1e4",
        close_market_value_cny: "8900", holding_return: "-0.11", stop_loss_threshold: "0.1",
        execution_shares: 1000, holding_age: 1 }] },
  };
  const markup = renderToStaticMarkup(<FrameworkDecisionDetails row={row} />);
  for (const text of ["持仓风险触发依据", "10000", "8900", "-11", "10", "下一开盘尝试退出", "实际成交或拒绝"]) {
    expect(markup).toContain(text);
  }
});

test("explains a frozen holding expiry without requiring stop-loss cost fields", () => {
  const markup = renderToStaticMarkup(<FrameworkDecisionDetails row={{
    decision_session: "2026-08-05", modules: {},
    universe: { instrument_ids: ["equity:600001.SH"], updated: false, reason: null },
    alpha: { kind: "formula", values: [] }, proposal: null, target_id: "expiry-target",
    risk_adjustment: { mode: "holding_risk", reason: "maximum_holding_period",
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
