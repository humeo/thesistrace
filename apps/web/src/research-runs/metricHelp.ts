import type { MetricHelpContent } from "../analysis/MetricHelp";

export const strategyMetricHelp = {
  netCumulative: {
    description: "从初始资金到回测结束的资产收益，已扣除交易费用。",
    formula: "期末净资产 ÷ 初始资金 − 1，以百分比显示。",
    range: "−100% 起，无固定上限。",
    direction: "越大越好。正值表示盈利，负值表示亏损；比较策略时还需结合风险与回测时长。",
  },
  benchmarkCumulative: {
    description: "沪深 300 价格指数在同一投资区间的累计涨跌幅，使用首次建仓日与结束日的开盘点位。",
    formula: "结束日指数开盘点位 ÷ 建仓日指数开盘点位 − 1，以百分比显示。",
    range: "大于 −100%，无固定上限。",
    direction: "越大表示同期基准表现越好；用于参照策略表现。",
    note: "采用价格指数口径，不含股息再投资。",
  },
  annualizedExcess: {
    description: "策略相对沪深 300 的财富增长倍数，按每年 252 个交易日折算的几何年化超额收益。",
    formula: "[(1 + 策略净累计收益率) ÷ (1 + 基准累计收益率)]^(252 ÷ N) − 1。N 为首次建仓至结束的交易日间隔数。",
    range: "大于 −100%，无固定上限；没有交易日间隔时不可计算。",
    direction: "越大越好。大于 0 表示跑赢基准，小于 0 表示跑输基准。",
    note: "策略收益已扣除交易费用；公式中的收益率使用小数。",
  },
  maximumDrawdown: {
    description: "回测中净资产从历史高点到随后低点的最大跌幅，反映期间经历的最大回撤。",
    formula: "各交易日的「1 − 当日净资产 ÷ 截至当日最高净资产」取最大值。",
    range: "0% 至 100%，以正数表示跌幅。",
    direction: "越小越好。0% 表示未发生回撤，越接近 100% 表示期间损失越严重。",
  },
  sharpe: {
    description: "每承担一单位收益波动，获得多少收益。使用相邻交易日的净资产收益率，当前无风险利率为 0。",
    formula: "每日净收益率均值 ÷ 每日净收益率样本标准差 × √252。",
    range: "无固定上下限；样本不足或标准差为 0 时不可计算。",
    direction: "越大越好。正值表示日均净收益为正，负值表示日均净收益为负。",
  },
  cumulativeCostRatio: {
    description: "整个回测期间累计交易费用占初始资金的比例，包括佣金、过户费和卖出印花税。",
    formula: "累计交易费用 ÷ 初始资金，以百分比显示。",
    range: "0% 起，无固定上限，长时间反复交易可能超过 100%。",
    direction: "在回测时长、收益与风险相近时，越小越好。",
    note: "这是全期累计比例，未做年化。",
  },
} satisfies Record<string, MetricHelpContent>;

export function factorMetricHelp(horizon: number) {
  const futureReturn = `未来 ${horizon} 个研究交易日的收益（从信号后的下一研究交易日开盘起算）`;
  const correlationDirection = "当前策略买入高分股票，因此越接近 +1 越好。接近 0 表示关系较弱；负值表示方向相反，可考虑对因子取反。";
  const stabilityDirection = "正向选股时越大越好。绝对值越大，相关方向越稳定；负值表示反向关系。";
  const stabilityRange = "无固定上下限；有效日期少于 2 个或标准差为 0 时不可计算。";
  return {
    rankIc: {
      description: `衡量因子排序与${futureReturn}的排序是否一致。逐日计算 Spearman 秩相关，再对有效日期取平均。`,
      formula: "有效日期的每日 Rank IC 之和 ÷ 有效日期数。",
      range: "−1 至 +1。",
      direction: correlationDirection,
    },
    rankIcir: {
      description: `衡量因子对未来 ${horizon} 个研究交易日收益的排序预测，在不同日期是否稳定。`,
      formula: "每日 Rank IC 的均值 ÷ 每日 Rank IC 的样本标准差。",
      range: stabilityRange,
      direction: stabilityDirection,
      note: "当前口径未年化，不乘 √252。只统计有效日期。",
    },
    ic: {
      description: `衡量因子数值与${futureReturn}的线性关系。逐日计算 Pearson 相关，再对有效日期取平均。`,
      formula: "有效日期的每日 IC 之和 ÷ 有效日期数。",
      range: "−1 至 +1。",
      direction: correlationDirection,
    },
    icir: {
      description: `衡量因子与未来 ${horizon} 个研究交易日收益的线性关系，在不同日期是否稳定。`,
      formula: "每日 IC 的均值 ÷ 每日 IC 的样本标准差。",
      range: stabilityRange,
      direction: stabilityDirection,
      note: "当前口径未年化，不乘 √252。只统计有效日期。",
    },
  } satisfies Record<string, MetricHelpContent>;
}
