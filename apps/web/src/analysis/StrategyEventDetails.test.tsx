// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
import { StrategyEventTable } from "./StrategyEventDetails";

test("expands a fill into exact prices and separate fees without charging slippage twice", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<StrategyEventTable section="strategy_fills" navigate={() => undefined} rows={[{
      fill_id: "fill-1", session: "2026-08-04", instrument_id: "equity:600000",
      side: "buy", quantity: 100, raw_open: "100", execution_price: "100.10",
      price_slippage: "0.10", research_settlement: "10010", commission_cny: "5",
      stamp_duty_cny: "0", transfer_fee_cny: "0.1001", cost: "5.1001", cash_rounding_delta: "0",
    }]} />));
    expect(host.textContent).toContain("原始开盘价（元）");
    expect(host.textContent).toContain("模拟成交价（元）");
    await act(async () => host.querySelector<HTMLButtonElement>("button")!.click());
    const detail = host.querySelector('[aria-label="成交价格与费用明细"]')!;
    const values = Object.fromEntries(Array.from(detail.querySelectorAll("dl > div"), item => [
      item.querySelector("dt")!.textContent, item.querySelector("dd")!.textContent,
    ]));
    expect(values).toEqual({
      "原始 Open（元）": "100", "模拟成交价（元）": "100.1", "每股滑点价差（元）": "0.1",
      "研究结算金额（元）": "10010", "佣金（元）": "5", "卖出印花税（元）": "0",
      "过户费（元）": "0.1001", "显式费用合计（元）": "5.1001", "现金舍入残差（元）": "0",
    });
    expect(detail.textContent).toContain("滑点已计入模拟成交价");
  } finally {
    await act(async () => root.unmount());
    host.remove();
    vi.unstubAllGlobals();
  }
});
