# Issue 02 实现计划

状态：complete。依次串行，第01票已完成并提交为 `99e16db`；本票基于该提交，仍在隔离 worktree。

## 当前边界

- `research_agent/registry.py` 是 MCP 领域工具入口；已有列表入参多为默认20、最大50，但目录与文件夹尚不分页。
- ResearchRun/Batch/DailyTrack 服务与 Result 分节已有游标，ResearchRun 使用 Fernet 绑定身份、查询以及 Result manifest；复用既有机制，不能在 Agent 层先截掉完整页而保留原下一页游标。
- `get_alpha_catalog` 当前返回全部 fields/builtins 或 identifier 过滤结果；文件夹领域接口返回完整列表，浏览器 authoring 也使用该接口，MCP 需要明确自己的分页投影。
- DailyTrack 多数写回执已小型化；逐项核对 ResearchRun/Batch 提交、取消和拒绝回执，避免包含可增长明细。

## 实施步骤

1. 完整盘点工具输入/输出及调用方，明确每种页的记录、稳定排序键、版本、长字段上界和详情读取方式；先补公开契约失败测试。
2. 提取 Core 业务页 UTF-8 计量与完整记录装页规则，预算包括元数据/next_cursor。默认20最多50；单条不能装入时使用明确的领域字段契约或详情分节，禁止无进展空页和静默裁剪。
3. 为目录与 ResearchContext folders 增加分页 Schema、稳定排序/身份/查询/版本校验。复用项目既有认证游标算法与配置来源，不增加临时存储或旧接口兼容。
4. 将已有列表和 Result 分节的页大小保护接到生成游标的领域边界；保留精确指标摘要及不可变 Result。核对并缩小写回执，保留资源/请求身份、状态及查询方式。
5. 同步 MCP 描述、权限与错误契约、Scripted 工具调用、Fixture、浏览器安全投影及示例。完整 canonical 业务结果只向模型注入一次，历史不在工具层重新截断。
6. 使用公开 Core/MCP 测试覆盖默认/上限、中文字节、超长单条、全部页遍历、游标篡改/身份/版本错误与成功操作后结果读取。使用现有隔离 PostgreSQL/Result 运行入口验证真实约束；保留 wire256KiB / decoded512KiB 独立传输边界。
7. 跑受影响 Python/Agent/Web 验证与类型检查，记录页大小等安全元数据。按 Standards→Spec 串行审查，修复复审后更新 tracker 并独立提交；通过前不开始03。

## 不在本票交付

全批工具结果驱动的压缩由03/04、恢复由05、分页与压缩完整闭环及最终镜像由06汇合。本票不启动真实模型摘要评估，也不改变开发容器、数据卷或 Dataset Head。

## 2026-09-07 进度

- 已增加共享完整记录 UTF-8 装页函数，并接入 ResearchRun/Batch/DailyTrack 列表的原游标生成边界；缩页后游标由实际保留尾项生成。
- 分页基础回归与现有 MCP 契约41项通过。测试由 `tests/unit/test_bounded_page.py` 移到快速检查覆盖的 `tests/architecture/test_bounded_page.py`；迁移路径时旧命令后续ruff阶段报文件不存在，改用新路径检查。
- 目录/文件夹认证游标尚未实施。现有领域游标签名密钥由 PostgreSQL 对应 `cursor_secrets` 表持久化；CoreSettings 没有合适的共享游标签名密钥。后续应明确领域所属及持久化密钥来源，不借用 S3 凭证或临时进程密钥。
- Result 分节、单条长字段契约、写回执、调用方与真实存储验证仍待完成，本票没有完成或提交。

## 目录 / 文件夹与 Result 接入进度

- `ResearchAgentPagination` 使用 Fernet，密钥由当前 PostgreSQL `research_agent.cursor_secrets` 持久化；已纳入当前 Schema 初始化和 Core 角色授权。游标绑定研究者、查询与集合内容/排序哈希，集合变化明确拒绝继续，不跳项。
- `get_alpha_catalog` 支持 combined limit/cursor/next_cursor；`get_research_context` 支持 folder_limit/folder_cursor 与 folders.next_cursor。同步 HTTP/stdio 注入、Schema、MCP 描述、轨迹 Fixture 和当前契约指纹。
- 回归覆盖跨 fields/builtins 合计条数、55个文件夹全页遍历、集合变更拒绝；底层覆盖 Unicode 字节预算、身份/查询/版本/篡改拒绝及同密钥重建续读。
- ResearchRun strategy_observations/terminal_positions、DailyTrack strategy_observations/origin 已接入完整记录装页，游标由实际保留记录生成，金融数值不改写。尚需真实 Result 存储链路验证。
- 最新直接相关 `test_research_agent_mcp_contract.py`、`test_research_agent_pagination.py`、`test_research_agent_trajectories.py`、`test_bounded_page.py` 共56项通过；受影响 Python 静态检查通过。
- 扩展架构检查发现两个基线既有问题：adapters/cninfo_financial_announcements.py 已依赖 operational_events，但依赖图清单缺该边；Web route 字符串检查连 import 一起扫描，误判既有 handleWorkspaceNavigation。HEAD内容已核实，两项需在最终验收前修正，不声明全套通过。
- 历史 ingress benchmark 文件只同步 deterministic payload 指纹并标注原 measured timings 日期；本票最后需重新测量该固定用例。

## 小回执、长字段与隔离验收进度

- 取消 Run/Batch 仅返回资源 ID、status/replayed/retry interval；全部成功写回执增加 next_tool。去除轨迹校验器对旧嵌套 batch 回执的读取，同步当前测试。超大附带 Run 明细回归证实取消回执仍小于1KiB且成功。
- Alpha catalog 的文字/参数/示例声明明确上限；最大合法多字节 Builtin 记录带50项 unknown 元数据仍可完整读取，超长字段拒绝。ResearchFolder 输出名称复用120字符域契约；Run 列表名称/公式摘要/失败原因声明当前边界。
- MCP 事件新增 business_response_bytes，只记录业务 JSON 字节数，与原 response_bytes 传输指标分离，不输出原文。
- Agent safe-result 与 Scripted 工具4个文件97项通过。最新MCP行为测试40项通过（精确指纹两项另跑）；分页与轨迹16项通过；本票Python静态检查通过。
- 固定 ingress 重新测量：4 passed /38 deselected；pytest1.03s、wall1.40s、RSS163774464 bytes。已更新当前文档测量，非沿用历史值。
- 正在运行 `./scripts/test-runtime integration`：exec session95903，项目 `thesistrace-test-20260906t174732z-31865-ad178069`。约68%之后开始出现失败，等待完整失败报告；不得根据阶段超时重启。新建真实持久化密钥/文件夹重连测试已包含在此轮收集中。
- 本轮收集后又把现有 Run 分页验收加强为200字符 Unicode 名称、请求50条实际缩页并续读；此变化需要后续重新运行对应验收，不能引用当前正在跑的旧收集结果声称通过。

## 复验与审查

- 首轮隔离 integration：418 passed、4 failed、8 deselected（629.90s）；失败为 stdio Run/DailyTrack 与 HTTP 的旧回执断言，以及新游标重建测试重复打开已关闭 pool。没有作为通过证据；测试项目已由 runner 清理。
- 已同步完整小回执断言，包括幂等重放时除 replayed 外的全部字段；重连测试改为新建 PostgresDatabase 和领域服务，不改动生产连接池行为。
- 复验正在独立项目 `thesistrace-test-20260906t180554z-39276-4d5eee5c` 中执行，结果待定。保持 dev 数据不变。
- 当前快速验证：分页/目录/MCP/轨迹58项通过；Web 安全投影和时间线18项通过；`uv run --frozen ruff check src tests` 全部通过。
- 固定审查快照 `/tmp/thesistrace-ticket02-review`：Standards 审查0项发现，Spec 审查进行中。尚未完成本票，未开始03。


## 收口

本票实现、针对性验证、真实隔离集成和Standards/Spec复审完成。最终备注1024字符、Catalog文字384字符，覆盖JSON转义最坏组合。详细失败诊断及最终证据见 [evidence-02](evidence-02.md)。已独立提交并更新tracker，可以串行进入03。
