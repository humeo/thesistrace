import Decimal from "decimal.js";

export type TakeProfitObservation = {
  reason: "take_profit"; instrument_id: string; cycle_ended: boolean;
  holding_return: string | null; profit_threshold: string; cumulative_reduction: string;
  baseline_execution_shares: number; baseline_adjusted_units: string; target_adjusted_units: string;
  executed_reduction_units: string; remaining_reduction_units: string;
  execution_shares: number; position_limit: number | null;
};
const number = (value: string) => new Decimal(value).toString();
const percent = (value: string) => new Decimal(value).mul(100).toString();

export function TakeProfitFacts({ item }: { item: TakeProfitObservation }) {
  return <>
    <p>止盈阈值 {percent(item.profit_threshold)}%；累计减仓 {percent(item.cumulative_reduction)}%。
      {item.holding_return !== null && ` 当前持仓收益 ${percent(item.holding_return)}%。`}</p>
    <p>首次基准 {item.baseline_execution_shares} 股（{number(item.baseline_adjusted_units)} 研究持仓单位）；累计目标保留 {number(item.target_adjusted_units)} 单位。</p>
    <p>实际卖出 {number(item.executed_reduction_units)} 单位；待减 {number(item.remaining_reduction_units)} 单位。研究持仓单位与执行股数分开计量，拒绝和取整未成交部分不算完成。</p>
    <p>{item.cycle_ended ? "本次持仓周期已结束；后续新决策可重新入场。" : `判断时持仓 ${item.execution_shares} 股；止盈周期内禁止普通补仓，直至完全退出。下一开盘尝试减仓，实际成交与拒绝见关联记录。`}</p>
  </>;
}
