import Decimal from "decimal.js";

export type PortfolioDrawdownObservation = {
  reason: "portfolio_drawdown";
  status: "observing" | "threshold_reached" | "cooldown" | "awaiting_new_portfolio" | "new_portfolio_recovery";
  cycle_started_session: string; peak_close_nav_cny: string; close_risk_nav_cny: string;
  drawdown: string; drawdown_threshold: number; maximum_stock_exposure: number | null;
  cooldown_sessions: number; completed_cooldown_sessions: number; triggered_session: string | null;
};
const statuses: Record<PortfolioDrawdownObservation["status"], string> = {
  observing: "观察中", threshold_reached: "回撤达到阈值", cooldown: "冷却中",
  awaiting_new_portfolio: "冷却结束，等待新的组合决策", new_portfolio_recovery: "新的组合决策解除回撤限制",
};
export function PortfolioDrawdownFacts({ item }: { item: PortfolioDrawdownObservation }) {
  return <>
    <strong>组合回撤 · {statuses[item.status]}</strong>
    <p>风险周期始于 {item.cycle_started_session}；收盘风险净值 {new Decimal(item.close_risk_nav_cny).toString()} 元，周期峰值 {new Decimal(item.peak_close_nav_cny).toString()} 元。</p>
    <p>周期回撤 {new Decimal(item.drawdown).mul(100).toString()}%；触发阈值 {new Decimal(item.drawdown_threshold).mul(100).toString()}%。</p>
    {item.triggered_session && <p>触发日 {item.triggered_session}；其后已完成 {item.completed_cooldown_sessions} / {item.cooldown_sessions} 个冷却交易日。</p>}
    <p>{item.maximum_stock_exposure === null ? "当前无组合回撤仓位限制。" : `股票目标上限 ${new Decimal(item.maximum_stock_exposure).mul(100).toString()}%；低于上限的目标不会被提高。`}</p>
    <p>解除限制只允许新组合目标参与执行，不表示实际仓位已恢复。下一开盘的成交、拒绝和持仓记录说明实际结果。主报告仍使用开盘净值，历史最大回撤不重置。</p>
  </>;
}
