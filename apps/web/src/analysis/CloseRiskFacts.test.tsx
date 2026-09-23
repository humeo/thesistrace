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
    risk_adjustment: { mode: "stop_loss", reason: "stop_loss", position_limits: { "equity:600001.SH": 0 },
      observations: [{ instrument_id: "equity:600001.SH", remaining_acquisition_cost_cny: "1e4",
        close_market_value_cny: "8900", holding_return: "-0.11", stop_loss_threshold: "0.1",
        execution_shares: 1000, holding_age: 1 }] },
  };
  const markup = renderToStaticMarkup(<FrameworkDecisionDetails row={row} />);
  for (const text of ["止损触发依据", "10000", "8900", "-11", "10", "下一开盘尝试退出", "实际成交或拒绝"]) {
    expect(markup).toContain(text);
  }
});
