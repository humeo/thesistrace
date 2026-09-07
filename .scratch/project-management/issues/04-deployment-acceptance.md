# 04 部署与最终验收
**Status:** complete

需求及验收见 [spec](../spec.md) 的 04 节。

## Comments
- 基线 f2550e89b52f6fb93ff272c2bbe3efa5d8c4400d；独立工作树 codex/project-management。
- Watch、配置与部署文档、真实验收发现的测试入口/时序/镜像环境问题均已修复并提交；双轴审查无未解决项。
- 快速检查、真实集成、全量 E2E 加失败项修复后的隔离复验、完整镜像冒烟及 5180 应用内浏览器验收完成。原 pnpm check 的失败与后续修复证据如实记录在 [验收报告](../review-04.md)。
- Development 13 个容器的 ID、镜像、状态、挂载和 Dataset Head 均未改变；本任务测试资源清理核对通过。
