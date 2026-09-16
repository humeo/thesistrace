# QS28 策略结果页复核

2026-09-10；Codex内置浏览器现有标签；943×949视窗，侧栏展开。仅检查[已完成的ROE策略](https://thesistrace.com/research-runs/run_e409850d95a343dfaacd)，没有修改账户、参数、草稿或启动跟踪。

1. **打开策略详情——可用，首屏信息优先级需改进。** 冻结公式、区间、股票池与持仓参数清楚；名称编辑和Factor Summary占据首屏。20日Rank IC显示0.040，但该账户的负收益和高回撤尚未进入视窗。建议Strategy Backtest优先展示账户收益、风险和本金假设；不能把正因子指标视为账户已达标。

![步骤1：首屏](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/product-audit/screenshots/08-round28-roe-first-screen.jpg)

2. **下滚到账户摘要——可用，数值与MCP一致。** 净收益−41.31%、回撤51.89%、Sharpe−1.799可读，具有CSI300对比、指标帮助及按日期悬停查看功能。截图悬停为2026-08-28，悬停值与顶部全年累计值有不同日期，不能混用。该步骤证明账户指标实际存在，问题是首屏优先级，不是页面没有策略结果。

![步骤2：账户指标与曲线](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/product-audit/screenshots/09-round28-roe-account-metrics.jpg)

指标帮助按钮具有可读的无障碍名称。图表与小字的对比度数值、全键盘和屏幕阅读器行为尚未实测，不给出合规结论。一次AX根节点滚动失败后，刷新页面结构并按截图坐标滚动成功；这是代理操作层现象，不记为ThesisTrace缺陷。

两张截图保存原始字节后重新打开本地文件检查；首屏整体内容和第二步目标指标完整。最初第二步标题略超出顶部，已重新定位截图，未据那张中间截图形成结论。[截图尺寸与哈希](round28-screenshot-manifest.json)、[完整无障碍树](round28-roe-ax.txt)。本次补充到既有[问题08](issues/08-page-priority-and-feedback.md)，不重复新增问题。

后续研究元数据整理：本轮代理曾把旧实验标题中的H100/R5等字样带入10条补测标题，造成名称同时出现两组持仓参数。这是代理命名问题；已通过页面Name and folder逐条保存纠正，并从MCP重新读取全部10个名称确认。冻结公式、日期、持仓和调仓输入核对未变，原始提交记录保留。[名称修正与核验账本](../round28-name-corrections.json)。这项操作发生在上述只读截图走查之后，不属于产品代码修复；未编辑用户原有草稿。
