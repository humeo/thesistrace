# 04 — 让 Signal 支持比较、布尔和条件表达式

**What to build:** Researcher 和 Agent 能用受限条件表达式组合股票评分，并通过同一目录、编辑器及诊断得到一致的可执行 Signal。

**Blocked by:** None — can start immediately

**Status:** complete

- [x] 单一表达式 Module 支持比较、布尔 and/or/not 与纯 if_else；数值/布尔类型和常量/股票序列作用域明确，不引入任意 Python、循环或有状态 trade_when。
- [x] Signal 最终输出每股每日数值；类型错误、布尔数值混用、资源超限及非法根节点由同一后端编译器定位诊断，客户端不能绕过。
- [x] and/or 任一操作数未知则未知，not 未知仍未知；if_else 已知条件只由选定分支决定该位置的值，未知条件输出缺失，两分支仍须静态合法并计入依赖。
- [x] 完整嵌套窗口、字段绑定及工作量进入准入；不只检查最终选中分支，不改变 Research Period 或让 Warm-up 进入绩效。
- [x] 目录、现有 Alpha 编辑器、草稿、diagnose_alpha_formula、提交及冻结 provenance 同步可用；本票先在 Signal 使用条件表达式，不提前展示尚不可执行的 Exposure 规则。
- [x] 普通 Factor/Strategy、Batch 与 DailyTrack 共享求值；用独立小样本验证条件分支、缺失、窗口和未来价格扰动，现有纯数值表达式保持原数值语义。
- [x] 跨 Chunk 及缓存恢复结果一致；语言、输入和持久身份采用单一当前合同，不用运行时多版本解释器。
- [x] 完成模块、HTTP/MCP 诊断成功/拒绝和编辑器交互验证；不另建一个只给网页或 Exposure 使用的求值器。

## Notes

规格：受限 DSL、类型与作用域、缺失语义、共享编译/诊断。

母规格：Agent Quant Research：信号评估、策略回测与前向追踪。遵循其当前合同与范围；每票直接交付当前合同，前端、MCP、验证随行为交付，不作为尾部补接工作。

## Comments

- 2026-09-12 最新执行约束：用户明确当前为开发阶段。本轮只实现单一当前合同，直接修改调用方与产物定义，不新增兼容分支、字段别名、旧合同读取适配、vXX 升级或版本迁移。先前所有存量转换、迁移备份/回滚/重复升级验收均撤回；其余产品功能和失败恢复验收保持。只操作新 worktree 与隔离测试资源，不删除或重置现有 dev/线上数据。严格按 01–14 串行：每票计划 → 实现 → 验证 → Standards 审查 → Spec 审查 → 修复复审 → tracker 更新 → 独立提交。

- 2026-09-12：用户确认 14 票拆分及阻塞关系，正式发布为 ready-for-agent；尚未开始实现。

- 2026-09-12：条件 Signal 已完成源码/冻结 IR 类型与资源校验、共享 Series 执行、目录/编辑器/HTTP/MCP。Kernel 369 项、HTTP/MCP 49 项、条件/因果/预算 22 项、Chunk 与冷缓存 Track 23 项、安全/Series Plan 8 项通过。真实 Run→Track 2 项、Factor/Strategy Batch 对普通 Run 4 项、浏览器条件编辑 1 项通过；网页类型、Ruff 与 diff check 通过。首次失败及修正记录见实施计划。Standards 与 Spec 均无未关闭发现，本记录随实现独立提交。
