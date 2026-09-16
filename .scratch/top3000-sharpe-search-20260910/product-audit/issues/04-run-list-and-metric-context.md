# 研究列表需要可比较的结果与清晰收益口径

Status: needs-triage
Priority: P1
Type: product-research
Evidence class: 已复现的交互问题与能力缺失
Observed: 2026-09-10

## 复现与现状

2026-09-10审查时Research Runs有323条、每页20条、17页；只有Folder/Type筛选，Created排序。列表不列回测起止、本金和实际净收益。QS5近63日显示Excess+48.87%，详情说明是Annualized excess且实际Net cumulative为5.53%。当前约943px宽面板中Result summary被挤到右侧，仅能看见首项的一部分。

## 对研究的影响

大量实验难以找出同区间赢家，年化超额容易被读作账户实际盈利；窄面板同时看不到Sharpe和回撤。

## 建议方向

可按实验/批次、状态、公式与日期查找，按指标排序/比较；列表明确‘年化超额’及窗口/样本量，提供净累计收益；窄容器把关键指标保留可见或明确横向滚动入口。

## 验收建议

复用本次323条运行和不同日期的样本，能筛出同窗口候选；窄面板可读净收益/Sharpe/回撤且无标签歧义；比较不把不同区间当同一排行榜。

## 证据

screenshots/02-research-runs.png；screenshots/03-strategy-result.png；apps/web/src/research-runs/ResearchRunsPage.tsx:1156

以上路径以研究目录/仓库为参照。UI证据见同目录上一层截图；产品代码只读核查，尚未实施修复。

## Comments

2026-09-10续查：当前列表为484条、每页20条、25页。943×949的嵌入面板、侧栏展开时，QS20长名称直接挤入Type列；Result summary仍只显示首项片段，Sharpe/Drawdown在右侧不可同时读到。完整无障碍树确有这些数值，故这是当前容器布局/可见性问题，不能说后端没有指标。新截图`screenshots/05-round20-research-runs.jpg`、完整树`round20-runs-ax.txt`与`round20-screenshot-manifest.json`。名称使用本次真实agent研究名称；应在可用宽度内换行/截断且保留完整名称查看方式，并让关键指标可读。未测试更宽桌面或移动端，不外推。

2026-09-10：在持续量化探索中记录；优先级针对用户当前的近期/状态切换/10万元20%回撤目标，不表示产品所有用户的统一优先级。
