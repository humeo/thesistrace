# 02 接入独立维护 Worker 并移除业务轮询扫描

Status: ready-for-agent

依赖：01。按 [方案](../spec.md) 接入 `publication-maintenance-worker`、最小运行时、启动及 Compose 配置。移除 Research / Batch / Tracking 中的 Publication 清理调用，保留各自本地执行文件的清理。添加每步计数、耗时、退避及完整扫描年龄事件。

同步移除旧自动全量清理接口，将其有效安全测试迁移到当前维护接口；最终运行路径不保留旧版兼容分支。

验收：6 个业务 Worker 空闲时零自动 Publication LIST；两个维护副本仍受统一预算约束；持续明确删除不饿死扫描；失败、退出与恢复行为符合方案。完成对应快速/真实依赖检查、最终镜像 smoke 与恢复资格验收，审查后单独提交。
