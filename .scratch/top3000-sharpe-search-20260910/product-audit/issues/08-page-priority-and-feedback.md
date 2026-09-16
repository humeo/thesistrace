# 研究结果与参数页面的信息优先级需要调整

Status: needs-triage
Latest supporting walkthrough: [QS28 切换策略与三个指标帮助](../ROUND28_METRIC_HELP_AUDIT.md)
Priority: P2
Type: product-research
Evidence class: 截图支持的设计建议
Observed: 2026-09-10

## 复现与现状

策略结果首屏先显示冻结参数，再是大块Name and folder编辑和Factor Summary，Strategy Summary在首屏之外。本金、执行价时点和费率未在冻结条件区域展示。Research当前已有草稿的Holdings/Rebalance空白，按钮disabled仅提示Complete the formula and research parameters，没有直接点出缺哪项。Data首屏SHA/ISO时间等工程信息占较大空间。

## 对研究的影响

研究者先要知道赚多少、承担什么风险、在什么假设下成立；需要滚动和读源代码才能确认默认资金，缺参反馈增加试探。

## 建议方向

Strategy Backtest优先展示净收益/回撤/Sharpe、区间/样本量/本金/费用与执行时点，详细Factor诊断和名称编辑后置；缺参就地提示；Data把能研究到哪日及阻塞原因放前，哈希等证据保留在详情。

## 验收建议

保持当前有价值的字段释义、指标帮助和数据就绪拆分；截图中首屏可回答关键问题；键盘/屏幕阅读器专项测试另行做，不能从本次截图直接宣称WCAG合规或不合规。

## 证据

screenshots/01-data-overview.png；screenshots/03-strategy-result.png；screenshots/04-research-authoring.png；apps/web/src/research-runs/ResearchRunsPage.tsx:1440

以上路径以研究目录/仓库为参照。UI证据见同目录上一层截图；产品代码只读核查，尚未实施修复。

## Comments

2026-09-10：在持续量化探索中记录；优先级针对用户当前的近期/状态切换/10万元20%回撤目标，不表示产品所有用户的统一优先级。

2026-09-10，QS28新增两步真实走查：打开已完成的ROE H10/R20一年期策略，943×949、侧栏展开时首屏主要显示名称编辑和因子摘要（20日Rank IC显示0.040）；账户摘要需要下滚。下滚后可清楚读到净收益−41.31%、最大回撤51.89%、Sharpe−1.799，并有CSI300对比曲线、指标帮助与悬停日期。页面数值与MCP一致，不属于漏算账户指标；问题是策略页的首屏信息优先级。未实施改版，未修改草稿或启动DailyTrack。

步骤1健康度：可用，账户结论在首屏外。步骤2健康度：可用，指标与曲线可读；截图中的悬停日期2026-08-28不是全年结束日。标签与帮助按钮有无障碍名称，但全键盘、屏幕阅读器与对比度数值未测；不据截图声明WCAG通过或失败。CUA一次使用AX根节点滚动报detached element，刷新结构后按截图坐标滚动成功，这是工具交互现象，不归责产品。

新证据：[首屏](../screenshots/08-round28-roe-first-screen.jpg)、[账户区域](../screenshots/09-round28-roe-account-metrics.jpg)、[完整页面文本](../round28-roe-ax.txt)、[截图清单](../round28-screenshot-manifest.json)、[两步报告](../ROUND28_UI_AUDIT.md)。
