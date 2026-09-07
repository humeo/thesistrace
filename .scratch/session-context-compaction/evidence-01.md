# Issue 01 验收记录

工作区：`.worktrees/session-context-compaction`，分支 `codex/session-context-compaction`。
实现基线：`3d75080`（原工作区既有改动快照）。本票未触及原 checkout 或开发数据库。

## 行为与红绿证据

- 必填 `max_output_tokens` 与 `min_compaction_context_window`；实际 Responses HTTP 请求以完整模型输入计算输出额度。
- 去除 8192 tokens / 累计生成 256 KiB 终止限制，保留计量和超时、取消、协议保护。
- `CONTEXT_TOO_LARGE` / `OUTPUT_LIMIT` 携带结构化请求预算；页面保留已有正文和成功工具回执，并给出明确解释。
- 截断响应即使带有完整工具参数也不释放业务操作。初始回归证实旧实现执行了操作，现已通过。
- 连续两个被暂存的工具调用曾使流停住；两个成功/长度停止回归先超时失败，改为循环读取后通过。
- 结构化输出 Schema / toolChoice 纳入完整输入；超大 Schema 拒绝用例先失败后通过。
- Run 内按规范化消息/工具哈希缓存 tokenx 估算，只保存有界哈希和计数，不改变或复制保留原文。
- 小窗口关闭 OM 后原生默认只读取50条：72条回归先丢失前22条，完整读取处理器修复后通过。恢复中的更新优先于旧存储版本。

## 验证

- `pnpm --dir agent test`：39 files，561 tests passed。
- `pnpm --dir agent typecheck`：通过。
- Agent isolated PostgreSQL `research-runtime.integration.test.ts`：既有63项通过；新增小窗口用例第一次因 Fixture 使用了无效适配器名而失败，修正为当前 `openai` 契约后定向运行1 passed / 63 skipped，退出0。证明重启后72条事实完整传入且没有辅助模型调用。
- `pnpm --dir agent test:eval-preflight`：11项通过。
- Web ChatTimeline / chatProtocol / agentTransport：30项通过；Web typecheck通过。
- `uv run --frozen pytest -q tests/architecture/test_caddy_compose_contract.py tests/architecture/test_local_lifecycle.py`：98项通过。
- `git diff --check`：通过。
- PostgreSQL 使用独立 `thesistrace-agent-test-*` 项目；测试入口清理自建资源，未重置 `thesistrace-dev`。

## Review

按用户要求串行执行 Standards、Spec 及修复复审。

- Standards 首轮：连续暂存工具调用可能停流，已红绿修复。
- Spec 首轮：小窗口历史50条裁剪、缺少结构化输出计量、缺少 token 估算缓存，均已修复并验证。
- Standards 复审：新增 PostgreSQL Fixture 适配器名不合法，已修正并实测通过。
- Standards 最终复审：无未关闭发现。
- Spec 最终复审：无本票范围内的缺失、错误或越界，前次三项均关闭。

## 交付边界

本票只交付预算、停止与页面错误闭环。统一 M/S 原子快照、90% 调度和一次恢复由03—05实现；最终浏览器、镜像、产品回归和真实模型摘要保真度评估由06验收。本记录不表示整项功能已完成。
