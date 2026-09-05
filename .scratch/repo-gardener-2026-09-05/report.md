# Repository Gardener — 2026-09-05

## Scope

- 按用户“从 0 开始”的修正，重新全仓扫描；旧 Gardener tag 不作为增量边界。
- 起点：本地 `main` 的 `4ae52244f7fa14c13703a8677b435cb5e6fd9f9f`。
- 分支：`codex/repo-gardener-full-20260905-0925`。
- 独立且已锁定的 Worktree：`/private/tmp/thesistrace-repo-gardener-full-20260905-0925`。
- 全量盘点 1011 个 tracked 文件，覆盖源码、测试、文档、部署/构建配置、依赖、脚本、技能、历史记录和二进制/生成文件。对候选继续核对入口、注册、引用与 Git 历史；并非逐行证明全部代码无缺陷。
- 分布：根目录 13，`.agents` 108，`.scratch` 60，Agent 113，Auth 93，benchmarks 5，contracts 8，deploy 13，docs 125，patches 3，scripts 14，src 146，tests 168，Web 142。

## Removed

| 类别 | 本次处理 |
| --- | --- |
| Production Code | 删除 8 个无调用的 Python 函数/方法/property；47 处仅内部使用的 TS/JS 声明取消导出；删除 1 个无用类型、1 个无用转导出及 2 条对应声明文件导出；清理 1 个无用局部 import；删除 3 组无消费者 CSS。 |
| Tests | 删除 2 个 Python 和 1 个 Web 测试 helper、1 个无用测试 import；另有 1 个 helper 取消导出，生产与测试合计 48 处。没有删除测试用例。文档数量断言由两个初始化器同步为三个，检查强度不变。 |
| Documentation | 局部修正 README、架构文档、运行手册中旧服务拓扑、入口、权限边界和 2 处失效锚点；没有删除文档或 ADR 正文。 |
| Configuration | 0；入口、部署、构建和包级测试配置仍有消费者。 |
| Project Files | 0；没有以文件年龄或名称为删除依据。 |
| Dependencies | 0；项目 manifest、lockfile 和依赖版本均未改动。 |
| Miscellaneous | 没有发现应删除的 tracked cache/log/build dump；测试资源按本次独立 Compose 身份清理，扫描日志留在已忽略的 `.local/repo-gardener/`。 |

## Evidence

| 删除对象 | 证据与保留的现用路径 |
| --- | --- |
| `alpha_builtins.py` 的 `_add_centered`、`_remove_centered`、`_recenter`、`_centered_state` | Vulture 报告；全仓仅定义；核对 `BUILTIN_DEFINITIONS`，标准差仍使用当前 `_population_std`/Fraction 实现。 |
| `DailyTrackService._current_strategy_summary` | 最后消费者已在 `9587e15` 被替换；当前详情和摘要路径有实现与测试。 |
| `Publication.stage_bytes` | `141594d` 将最后消费者切换为 streaming `stage_file`；生产调用及真实存储集成测试均使用后者，无动态注册入口。 |
| `strategy_sweep_encoded_outcome_cell_count` | 旧全历史容量 helper 已无调用；当前 admission 使用受限窗口及会话并集的容量计算。 |
| `PrivateAlphaFactorArtifactWriter.partial_path` | 无外部访问；内部 `_partial_path` 字段仍参与真实文件生命周期，保留。 |
| `extend_fixture_sessions`、`_batch_attempt_status`、`revealAllToolActivity` | 扫描、全仓引用、测试入口检查一致；保留正在使用的 append、状态查询和定向 tool helper。 |
| 内部 TS/JS 导出 | Knip 加真实 package/CLI/Docker/test/eval 入口检查、引用搜索及三包 typecheck；实现保留，仅缩小私有包内部模块的无消费者导出。 |
| `.chat-tool-resource`、`.hero-copy`、`.research-folder-load-failure` CSS | TSX/HTML 与动态 class 插值检查；旧 tool renderer 已由 `d5411ef` 替换。动态状态类和当前 ToolGroup 样式保留。 |
| 文档旧拓扑/路由 | 对照当前 Compose、Caddy、Auth routing 和 Operator runbook；三个初始化器为 `initialize`、`auth-initialize`、`agent-initialize`。 |

Knip 6.34.0 在相同入口配置下由 60 项降至 9 项：2 个 dependency、5 个 export、2 个 type 发现均复核保留。Vulture 2.16（最低置信度 60%）由 524 项降至 514 项，减少的恰为上述 10 个 Python 定义，无新增发现。工具临时运行，未加入项目依赖。

## Kept / Uncertain

- `QuestionOption` 与 `ChatAnswer`：Knip 漏掉 inline `import("...").Type` 引用。类型检查与 Spec 审查发现后已恢复导出，消费者不变。
- 5 个 eval 导出：运行脚本从 `dist` 引用，属于扫描盲区；保留。
- Agent 的 `ai`、`@ag-ui/encoder`：栈版本契约及传递消费者仍存在，不能证明可安全删除。
- Pydantic 字段/validators、FastAPI routes、pytest fixtures、HTTP handler、`__exit__` 参数：由协议或框架使用，保留。Vulture 剩余提示不等于确认 dead code。
- Agent/Auth 三组内容相同的 tsconfig/Vitest 配置：各自 package 入口需要，保留；没有为消重引入共享抽象。
- CNINFO probe JSONL、数据修复 SQL、benchmark、fixtures、generated parser、依赖 patches：有历史说明、具体数据身份、测试或构建消费者，保留。
- ADR-0224 至 ADR-0230 索引仍指向缺失正文，两个 CrewAI 技能交叉链接仍指向旧文件名；已记录现状。本轮保留 ADR 历史索引和已安装技能资料，未推断其作者的替代/归档意图。

## Verification

命令均在上述 Worktree 中运行；Node/pnpm 通过 `MISE_TRUSTED_CONFIG_PATHS="$PWD" mise exec --` 使用仓库版本，Python 使用 `uv`。

| 实际命令 | 结果 |
| --- | --- |
| `pnpm install --offline --frozen-lockfile`；`uv sync --frozen --offline` | 通过，锁文件不变。 |
| `pnpm test`（清理前/最终） | 两次均 Ruff 通过，Python **1079 passed / 8 failed**；失败集合完全相同。命令因 Python 失败停止，后续 JS 检查单独执行。 |
| `uv run --no-sync pytest -q tests/unit` | 3 passed。 |
| `pnpm --dir agent typecheck`、`test`、`test:eval-preflight` | 通过：531 项测试、11 项离线 preflight；preflight 包含 Agent build。 |
| `pnpm --dir auth typecheck`、`test`、`build` | 通过：191 项测试。 |
| `pnpm --dir web typecheck`、`build` | 通过，product bundle budget 通过；保留现有 bundle size warning。 |
| `pnpm --dir web exec vitest run src --maxWorkers=2 --minWorkers=1` | 36 文件、316 项通过。清理前默认并发执行同一全量集合时有 1 项 5 秒超时；降低并发后的通过不代表该不稳定性已修复。 |
| `uv run ruff format --check`（7 个代码文件及 1 个文档断言测试分别检查） | 清理前后均 3 个已有格式差异、5 个已格式化；未进行无关重排。原始快照分别检查。 |
| `pnpm test:integration` | exit 0；Core 421 项加 6 项数据库/RustFS 重启恢复、Auth 136 项、Agent 67 项，共 630 项通过。真实 PostgreSQL/RustFS 依赖，Agent 使用确定性模型。 |
| `pnpm test:e2e` | exit 1；完整镜像构建、初始化与服务健康启动完成，随后被现有 `mcp_resource: unbound variable` 阻断，Playwright 未启动。未宣称浏览器验收通过。 |
| `pnpm --package=knip@6.34.0 dlx knip --config .local/repo-gardener/knip.json --reporter json --no-progress` | exit 1，9 项剩余发现均复核保留；Playwright 配置读取使用本地占位 origin，不调用浏览器。 |
| `uvx --offline vulture src tests scripts --min-confidence 60` | exit 3，514 项保守提示；重要删除经过独立引用与注册检查。 |
| `git diff --check`；修改文档的本地链接/锚点检查 | 通过；17 个引用均可解析。 |

原有 8 项快速检查失败：

- `test_internal_import_graph_is_layered_and_acyclic`：当前 `operational_events` import 与架构白名单不一致。
- `test_web_shell_declares_only_the_four_product_resources`：当前导航源码与旧字面断言不一致。
- `test_e2e_runtime_starts_full_topology_and_runs_only_host_playwright`
- `test_production_image_smoke_builds_once_and_reuses_the_images`
- `test_failed_image_smoke_persists_runner_diagnostics_before_cleanup`
- `test_failed_mcp_image_smoke_sanitizes_preserved_protocol_evidence`
- `test_failed_evidence_sanitization_discards_all_text_evidence`
- `test_failed_e2e_groups_playwright_and_compose_evidence_before_cleanup`

后六项涉及现有 `scripts/test-runtime:525` 的 `mcp_resource: unbound variable` 及提前退出后的证据检查。脚本和这些断言均未改动，未为变绿顺便修复。清理中发现的两处误删导出已恢复；新增文档检查失败通过同步过时数量解决，最终失败集合回到原有 8 项。

初始 Worktree 在首次集成运行中被外部动作移除，具体来源未核实；当时尚无 tracked 清理修改。该次运行无效，原日志随目录丢失。已从同一 `main` commit 重建并锁定 Worktree，重新执行基线/验证。通过原生 `test:cleanup` 清理了已核对身份的中断项目 `thesistrace-test-20260905t091213z-85620-92965cc0`，未操作开发数据。

原始日志、扫描配置、文件哈希、候选清单、失败集合对比和两次审查快照位于 `.local/repo-gardener/`，该目录不进入 Git。

收尾独立核验：本轮五个精确测试 Compose 身份的容器、卷、网络、镜像均为零；开始时记录的六个运行中 `thesistrace-dev` 容器 ID 全部相同。没有重置或删除开发数据。最终差异与复审源码快照 SHA-256 `07e8329440a86f095a7765bdb73e20c4c39df3a886abfba4e3682c5c36eb76d8` 一致。

## Standards

最终 47 文件快照增量复审：0 项发现。恢复的导出有消费者；三个初始化器的文档数量断言与 Compose 一致，未放宽检查。未发现新增规范违例或 Fowler smell。此结论是静态审查，不代替测试。

## Spec

初审发现 2 处误删类型导出；恢复后复审剩余 0 项发现。文档数量同步属于修改过时部分。运行报告另做增量复核，未发现实质问题；末次集成结果与统计由主代理核验。成功 baseline 没有推进。

审查计数：Standards 0；Spec 2 项已关闭、剩余 0，各轴无未解决问题。

## Diff Summary / Baseline

- 清理本体：修改 47 个文件，新增 97 行、删除 301 行；整文件删除 0，依赖删除 0。
- 含本报告：修改 47 个文件、新增 1 个文件、删除 0 个文件；新增 200 行、删除 301 行，净减少 101 行。
- 已完成本轮清理、测试结果对比及最终差异审查，保存在本地 Gardener 分支。由于既有快速检查和 E2E 失败，不创建新的 Gardener 成功 tag；旧成功基线保持不变。本轮不合并或推送。
