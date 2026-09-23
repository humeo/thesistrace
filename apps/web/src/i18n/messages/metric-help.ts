export const metricHelpEn = {
  "strategy": {
    "netCumulative": {
      "description": "Account return from initial capital to the end of the backtest, after trading costs.",
      "formula": "Ending net account value ÷ initial capital − 1, displayed as a percentage.",
      "range": "From −100%, with no fixed upper bound.",
      "direction": "Higher is better. Positive means profit and negative means loss; compare alongside risk and backtest duration."
    },
    "benchmarkCumulative": {
      "description": "Cumulative change in the CSI 300 price index over the same investment period, using opening levels on the first entry and final sessions.",
      "formula": "Final-session index opening level ÷ entry-session index opening level − 1, displayed as a percentage.",
      "range": "Above −100%, with no fixed upper bound.",
      "direction": "Higher means stronger benchmark performance over the period; use it as a reference for the strategy.",
      "note": "Price-index basis; dividends are not reinvested."
    },
    "annualizedExcess": {
      "description": "Geometric annualized excess return from the strategy’s wealth growth relative to CSI 300, using 252 trading days per year.",
      "formula": "[(1 + net strategy cumulative return) ÷ (1 + benchmark cumulative return)]^(252 ÷ N) − 1. N is the number of trading-day intervals from first entry to the end.",
      "range": "Above −100%, with no fixed upper bound; unavailable when there are no trading-day intervals.",
      "direction": "Higher is better. Above 0 means outperforming the benchmark; below 0 means underperforming.",
      "note": "Strategy return is after trading costs. Returns in the formula are decimals."
    },
    "maximumDrawdown": {
      "description": "The largest decline in net account value from a previous peak to a subsequent trough during the backtest.",
      "formula": "Maximum across trading days of: 1 − net account value ÷ highest net account value up to that day.",
      "range": "0% to 100%, expressed as a positive decline.",
      "direction": "Lower is better. 0% means no drawdown; values closer to 100% indicate more severe losses during the period."
    },
    "sharpe": {
      "description": "Return per unit of return volatility, using net account returns between consecutive trading days. The current risk-free rate is 0.",
      "formula": "Mean daily net return ÷ sample standard deviation of daily net returns × √252.",
      "range": "No fixed bounds; unavailable with insufficient samples or zero standard deviation.",
      "direction": "Higher is better. A positive value means positive average daily net return; a negative value means negative average daily net return."
    },
    "cumulativeCostRatio": {
      "description": "Total trading costs over the backtest as a fraction of initial capital, including commissions, transfer fees and sell-side stamp duty.",
      "formula": "Cumulative trading costs ÷ initial capital, displayed as a percentage.",
      "range": "From 0%, with no fixed upper bound. Repeated trading over a long period can exceed 100%.",
      "direction": "Lower is better when duration, return and risk are comparable.",
      "note": "A cumulative ratio for the full period, not annualized."
    }
  },
  "factor": {
    "rankIc": {
      "description": "Measures whether factor ranks agree with the ranks of returns over the next {{horizon}} Research Sessions, measured from the Open of the next Research Session after the signal. Compute daily Spearman rank correlations, then average across valid dates.",
      "formula": "Sum of daily Rank IC on valid dates ÷ number of valid dates.",
      "range": "−1 to +1.",
      "direction": "The current strategy buys high-scoring stocks, so closer to +1 is better. Near 0 means a weak relationship; a negative value means the opposite direction and may suggest inverting the factor."
    },
    "rankIcir": {
      "description": "Measures how consistently the factor predicts the ranking of returns over the next {{horizon}} Research Sessions across dates.",
      "formula": "Mean daily Rank IC ÷ sample standard deviation of daily Rank IC.",
      "range": "No fixed bounds; unavailable with fewer than 2 valid dates or zero standard deviation.",
      "direction": "Higher is better for positive-direction selection. Greater absolute values indicate a more stable correlation direction; negative values indicate an inverse relationship.",
      "note": "Not annualized: no multiplication by √252. Includes valid dates only."
    },
    "ic": {
      "description": "Measures the linear relationship between factor values and returns over the next {{horizon}} Research Sessions, measured from the Open of the next Research Session after the signal. Compute daily Pearson correlations, then average across valid dates.",
      "formula": "Sum of daily IC on valid dates ÷ number of valid dates.",
      "range": "−1 to +1.",
      "direction": "The current strategy buys high-scoring stocks, so closer to +1 is better. Near 0 means a weak relationship; a negative value means the opposite direction and may suggest inverting the factor."
    },
    "icir": {
      "description": "Measures the stability across dates of the linear relationship between the factor and returns over the next {{horizon}} Research Sessions.",
      "formula": "Mean daily IC ÷ sample standard deviation of daily IC.",
      "range": "No fixed bounds; unavailable with fewer than 2 valid dates or zero standard deviation.",
      "direction": "Higher is better for positive-direction selection. Greater absolute values indicate a more stable correlation direction; negative values indicate an inverse relationship.",
      "note": "Not annualized: no multiplication by √252. Includes valid dates only."
    }
  }
} as const;

export const metricHelpZh = {
  "strategy": {
    "netCumulative": {
      "description": "从初始资金到回测结束的资产收益，已扣除交易费用。",
      "formula": "期末净资产 ÷ 初始资金 − 1，以百分比显示。",
      "range": "−100% 起，无固定上限。",
      "direction": "越大越好。正值表示盈利，负值表示亏损；比较策略时还需结合风险与回测时长。"
    },
    "benchmarkCumulative": {
      "description": "沪深 300 价格指数在同一投资区间的累计涨跌幅，使用首次建仓日与结束日的开盘点位。",
      "formula": "结束日指数开盘点位 ÷ 建仓日指数开盘点位 − 1，以百分比显示。",
      "range": "大于 −100%，无固定上限。",
      "direction": "越大表示同期基准表现越好；用于参照策略表现。",
      "note": "采用价格指数口径，不含股息再投资。"
    },
    "annualizedExcess": {
      "description": "策略相对沪深 300 的财富增长倍数，按每年 252 个交易日折算的几何年化超额收益。",
      "formula": "[(1 + 策略净累计收益率) ÷ (1 + 基准累计收益率)]^(252 ÷ N) − 1。N 为首次建仓至结束的交易日间隔数。",
      "range": "大于 −100%，无固定上限；没有交易日间隔时不可计算。",
      "direction": "越大越好。大于 0 表示跑赢基准，小于 0 表示跑输基准。",
      "note": "策略收益已扣除交易费用；公式中的收益率使用小数。"
    },
    "maximumDrawdown": {
      "description": "回测中净资产从历史高点到随后低点的最大跌幅，反映期间经历的最大回撤。",
      "formula": "各交易日的「1 − 当日净资产 ÷ 截至当日最高净资产」取最大值。",
      "range": "0% 至 100%，以正数表示跌幅。",
      "direction": "越小越好。0% 表示未发生回撤，越接近 100% 表示期间损失越严重。"
    },
    "sharpe": {
      "description": "每承担一单位收益波动，获得多少收益。使用相邻交易日的净资产收益率，当前无风险利率为 0。",
      "formula": "每日净收益率均值 ÷ 每日净收益率样本标准差 × √252。",
      "range": "无固定上下限；样本不足或标准差为 0 时不可计算。",
      "direction": "越大越好。正值表示日均净收益为正，负值表示日均净收益为负。"
    },
    "cumulativeCostRatio": {
      "description": "整个回测期间累计交易费用占初始资金的比例，包括佣金、过户费和卖出印花税。",
      "formula": "累计交易费用 ÷ 初始资金，以百分比显示。",
      "range": "0% 起，无固定上限，长时间反复交易可能超过 100%。",
      "direction": "在回测时长、收益与风险相近时，越小越好。",
      "note": "这是全期累计比例，未做年化。"
    }
  },
  "factor": {
    "rankIc": {
      "description": "衡量因子排序与未来 {{horizon}} 个研究交易日的收益（从信号后的下一研究交易日开盘起算）的排序是否一致。逐日计算 Spearman 秩相关，再对有效日期取平均。",
      "formula": "有效日期的每日 Rank IC 之和 ÷ 有效日期数。",
      "range": "−1 至 +1。",
      "direction": "当前策略买入高分股票，因此越接近 +1 越好。接近 0 表示关系较弱；负值表示方向相反，可考虑对因子取反。"
    },
    "rankIcir": {
      "description": "衡量因子对未来 {{horizon}} 个研究交易日收益的排序预测，在不同日期是否稳定。",
      "formula": "每日 Rank IC 的均值 ÷ 每日 Rank IC 的样本标准差。",
      "range": "无固定上下限；有效日期少于 2 个或标准差为 0 时不可计算。",
      "direction": "正向选股时越大越好。绝对值越大，相关方向越稳定；负值表示反向关系。",
      "note": "当前口径未年化，不乘 √252。只统计有效日期。"
    },
    "ic": {
      "description": "衡量因子数值与未来 {{horizon}} 个研究交易日的收益（从信号后的下一研究交易日开盘起算）的线性关系。逐日计算 Pearson 相关，再对有效日期取平均。",
      "formula": "有效日期的每日 IC 之和 ÷ 有效日期数。",
      "range": "−1 至 +1。",
      "direction": "当前策略买入高分股票，因此越接近 +1 越好。接近 0 表示关系较弱；负值表示方向相反，可考虑对因子取反。"
    },
    "icir": {
      "description": "衡量因子与未来 {{horizon}} 个研究交易日收益的线性关系，在不同日期是否稳定。",
      "formula": "每日 IC 的均值 ÷ 每日 IC 的样本标准差。",
      "range": "无固定上下限；有效日期少于 2 个或标准差为 0 时不可计算。",
      "direction": "正向选股时越大越好。绝对值越大，相关方向越稳定；负值表示反向关系。",
      "note": "当前口径未年化，不乘 √252。只统计有效日期。"
    }
  }
} as const;
