# Research 指标过滤

本地已实现。在列表选择 Type 后，可添加最多 12 条条件，支持 >、>=、<、<=，所有条件 AND 组合，也支持同一指标上下界。策略：Annualized excess、Sharpe、Max drawdown；因子：1/5/20-session Rank IC。收益/回撤输入百分数（10 -> 0.1），其他指标输入原值。

Apply filters 提交；编辑草稿时明确提示尚未应用。Clear filters 清空并重新加载；切换 Type 清空条件。条件变化回到第一页，后端对当前用户全部筛选范围应用参数化 SQL 谓词，再全局排序/分页，并返回过滤后的总数。NULL 指标不满足比较。字段和比较符用白名单，阈值要求有限数值；最多 12 条、URL 参数最多 4096 字符。

验证：8 项 PostgreSQL/HTTP 定向检查通过，覆盖 6 个指标、严格/包含边界、同字段范围、NULL、用户隔离、分页总数、非法参数和正确 HTTP 传递。Web 24 项单元测试、TypeScript 检查、Python lint 通过。浏览器 4 项检查通过，覆盖排序、手机布局、条件组合、百分数换算、因子类型切换及清空；截图 metric-filters-mobile.png 已人工检查。

过程中修复了 FastAPI 对复杂 Json Query 声明的拒绝、过滤面板挂载位置错误、以及过滤面板与列表重复 React key 导致类型切换残留的问题。最终复测通过。PostgreSQL 使用仓库 TestRun 独立项目并已清理，没有访问 dev 数据。

本次仅本地实现，未提交或部署。没有新增指标索引，没有进行几万条数据压测。
