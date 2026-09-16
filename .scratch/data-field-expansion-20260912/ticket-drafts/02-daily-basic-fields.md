# 02 — 接入 daily_basic 的 16 个 DSL 入口

**What to build:** Researcher 能在同一个 Market data 区块发现并使用估值、股本、换手和原始收盘价字段；这些值由 Market Refresh 持续采集，按正确交易日进入统一 Data 读取和研究执行。

**Blocked by:** 01 — 统一现有字段目录、准入和家族合同

**Status:** needs-triage

**Draft:** 拆分待确认，尚未发布。

- [ ] 按权威 226 清单接入 close_raw、total_mv、circ_mv、total_share、float_share、free_share、turnover_rate、turnover_rate_f、volume_ratio、pe、pe_ttm、pb、ps、ps_ttm、dv_ratio、dv_ttm，共 16 个作者入口。
- [ ] equity.daily_basic 承载 15 个新指标；close_raw 只绑定既有 price.close.raw 身份，使价格家族为 7 项、Market 总目标为 22 项。daily_basic.close 保存作来源核对；差异有证据，不逐行换源补价，不改变复权 close。
- [ ] 显式采集 daily_basic 的 19 个来源列，沿用历史证券身份和 Research Calendar，支持期间内退市股票。按交易日分片；达到 6000 行上限时继续拆分或验证受支持的取全方式，不能将可能截断的结果记为完成。
- [ ] 有界真实来源资格证明每列的金额、股数、比率或倍数单位。换手率、股息率按已核实比例转为 DSL 小数，已为小数的来源不重复缩放，PE/PB 不除以 100；原始响应与规范化证据保留。
- [ ] 按股票和交易日精确读取，缺日或缺值保持缺失，不前向填充；只用于收盘后的信号计算，不用于同日开盘决策。历史估值不宣称具有完整分母修订链。
- [ ] Market Refresh 同时维护价格与每日指标的独立来源完成度、覆盖和重试检查点。无权限、限流、超时、缺列或截断不能被价格刷新成功掩盖，也不能丢弃旧历史；在固定数据上证明中断恢复可收敛。
- [ ] 发布该家族及后续 Market Refresh 都保留非目标家族和各自真实覆盖，使用已有单一 Dataset Head、Operator 权限与生命周期保护，不新增独立发布入口或 Head。
- [ ] Data 页在现有 Market 区块显示实际可用数量、来源状态和字段说明；搜索、补全、HTTP/MCP、Agent 能查询这些字段。指标未就绪时依赖它们的公式被拒绝，仅依赖价格的研究仍可执行。
- [ ] 在同一冻结 Generation 上，从统一读取到 ResearchRun、Batch、DailyTrack 的值和日期对齐一致；研究执行禁用供应商网络仍可完成，仅读取所需列。
- [ ] 演示一次有界采集或 Replay、候选验证、隔离发布、混合价格/估值公式提交和下一次刷新，证明字段仍可用。完成本票相关的来源、公开模块、真实存储/Worker、合同和页面验证。

**Verification:** 母规格 T01、T02、T08、T09、T10、T11、T15。完整历史范围由 07 汇总验收；本票完成可运行采集与研究链路及有界来源资格，不单独上线。
