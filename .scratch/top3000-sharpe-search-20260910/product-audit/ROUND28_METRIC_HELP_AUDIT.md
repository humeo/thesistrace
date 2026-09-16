# QS28 指标解释走查

2026-09-10；内置浏览器现有标签、943×949 视窗、侧栏展开。目标流程：打开已完成的 d036 H10/R20 切换策略，读取账户指标及其帮助。只读操作；没有编辑输入、名称、草稿或启动跟踪。

1. **打开策略详情——可用，首屏优先级仍需改进。** 状态、完整公式、日期、TOP3000、持仓与调仓参数可核对。约 200 字符的复合公式换行可读，历史参数没有混入本次名称。首屏随后显示名称编辑与 Factor Summary；账户收益、回撤和 Sharpe 在下方。对当前以 10 万元收益/风险为目标的任务，建议先呈现账户指标与本金假设。名称输入框中的长文字被可编辑字段宽度限制，但上方冻结名称完整呈现，不据此称名称丢失。没有通过截图测量对比度或完成全键盘验收。

![步骤1：当前切换策略首屏](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/product-audit/screenshots/10-round28-switch-first-screen.jpg)

2. **打开 Sharpe 帮助——可用，解释准确。** 点击具有明确无障碍名称的 About Sharpe 控件后，页面滚动到账户摘要，弹层完整可见，有标题和关闭按钮。说明写明相邻交易日净资产收益率、无风险利率 0、日收益样本标准差与 √252 年化，也明确“正值表示日均净收益为正”。该说明与本次 Result 及独立复算口径一致，值得保留；不能把这项功能写成缺失。弹层覆盖部分图表是本次展开状态，未观察到文本截断。

![步骤2：Sharpe 帮助](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/product-audit/screenshots/11-round28-sharpe-help.jpg)

3. **查看最大回撤帮助——可用，计算口径清楚。** 关闭 Sharpe 弹层后焦点回到原 About Sharpe 按钮。最大回撤说明给出历史峰值到后续低点的含义、逐日运行峰值公式及正数表示跌幅的范围，与本次独立净值复算一致。弹层正文与关闭控件完整可见；本次未验证连续键盘遍历或屏幕阅读器播报。

![步骤3：最大回撤帮助](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/product-audit/screenshots/12-round28-drawdown-help.jpg)

4. **查看累计费用帮助并关闭——可用，累计口径准确。** 说明列出佣金、过户费、卖出印花税，分母为初始资金，且明确全期累计比例未年化；正文和关闭按钮完整可见。关闭后焦点回到 About Cumulative cost ratio 控件。帮助未在这一弹层直接给出本账户的本金金额、逐项费率或最低收费，这些仍需要从契约/结果核对；不能因有费用比例便把原生 1000 万元账户按比例转换成 10 万元。

![步骤4：累计费用帮助](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/product-audit/screenshots/13-round28-cost-help.jpg)

四张截图均保存原始字节并重新打开确认。截图中年度净累计 8.00%、最大回撤 8.92%、Sharpe 0.598、累计费用比率 1.21% 与已保存 MCP Result 按页面精度一致；这是数值及说明的一致性检查，没有另外重建该账户订单。

本次实际检查了展开、关闭、展开状态属性与关闭后焦点返回；未测全键盘、屏幕阅读器、对比度数值、移动端或其他视窗。没有据截图给出正式无障碍合规结论。截图时弹层覆盖部分图表，未发现正文截断或关闭失败，不以正常覆盖视为缺陷。

入口：[d036 H10/R20](https://thesistrace.com/research-runs/run_761410df5edd4984868a)。建议补充到既有[账户约束问题](issues/01-capital-and-account-constraints.md)、[页面优先级问题](issues/08-page-priority-and-feedback.md)，不新增重复问题。[截图尺寸与哈希](round28-metric-help-screenshot-manifest.json)。
