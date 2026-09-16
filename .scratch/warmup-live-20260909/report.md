# 预热块修复线上复测

已提交、推送 main 和 codex/contabo-deployment，并部署 d3595d9。部署分支 pnpm test:image-smoke 通过。服务器五个 Worker 的 execution.py 哈希与提交一致。

复测原始失败参数：T3000，rank(volume / ts_mean(volume, 60))，2010-04-06 至 2026-08-27，H50、每5交易日调仓、无中性化。

- run_1e53649503fe49d9b230: succeeded，385.105 秒，59 个预热交易日、3984 个研究交易日、80 个块。
- run_240dd66cbbfe403d919c: succeeded，380.567 秒，59 个预热交易日、3984 个研究交易日、80 个块。

两次 factor 与 strategy_summary 除 run_id 外完全一致。五个 Worker 无 OOM、无重启。采样最低可用内存 7.60 GiB，网关元数据探针失败 0 次。3普通+2Batch配置保持生效。

本轮未创建新的252日线上任务；252日及恢复行为已在隔离真实依赖测试验证。旧的两条失败记录保留，本次是新的复测任务。
