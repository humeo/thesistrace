# 01 配置与生命周期
**Status:** complete

需求及验收见 [spec](../spec.md) 的 01 节。

## Comments
- 基线 f2550e89b52f6fb93ff272c2bbe3efa5d8c4400d；独立工作树 codex/project-management。
- Node 配置回归 10/10；开发/生产校验及生命周期 56/56；生产 CLI 与停用流程 33/33。真实 Compose config:check 通过，未启动容器。
- 全组工具测试需要隔离回环端口，沙箱阻止绑定；记录失败日志后改用允许本地端口的执行环境复验。
- 完整相关 Python 工具测试 138 passed；审查后复验 60 passed；Node 配置回归 13 passed，原有工具回归 7 passed；测试归属检查通过。
- 双轴发现已关闭，复审 Standards 0 未解决 / Spec 0 未解决，详见 ../review-01.md。
- 已提交 1487bed；后续单元保持当前入口并更新目录引用。
