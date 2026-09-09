# Research 全局排序修复

当前用户的所有 Research 先经 Folder/Type 过滤，在 PostgreSQL 按选定字段全局排序后 LIMIT/OFFSET 分页。Web 请求新增 sort_by、sort_direction；默认创建时间降序。支持三个策略指标、三个因子 Rank IC 指标及创建时间。数值按 double precision 排序，NULL 始终末尾，同值按创建时间降序和 ID 升序稳定排序。排序字段/方向由闭合白名单验证。

前端移除当前页数组排序。切换排序重置页码，下一页保留选定排序；改变 Type 重置为创建时间排序。保留工作区已有的分页总数改动和其他未提交修改。

验证：先确认请求参数回归失败，再实现；Web 24 项测试及 TypeScript 检查通过；真实隔离 PostgreSQL 与 HTTP 定向检查 7 项通过，覆盖所有 6 种指标、数值排序、空值、同值稳定性、跨页、用户隔离和筛选；实际页面组件浏览器检查 3 项通过，包含桌面/手机分页和从第二页选择收益排序回到第一页。Python lint、git diff --check 通过。独立 PostgreSQL 已清理，未触碰 dev 数据。

仅完成本地修改与验证，未提交、未部署。没有运行几万条数据压测。沿用现有页码/总数契约，未新增指标索引，不声称此 SQL 是 O(log N) 的指标分页查询。
