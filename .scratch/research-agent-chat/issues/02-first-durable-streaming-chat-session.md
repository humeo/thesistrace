# 02 — First durable streaming Chat Session

**What to build:** 让 Researcher 在 New Chat 中提交第一条文本后创建一个真实、持久的 Agent Chat Session，并通过 CopilotKit React Core、AG-UI、CopilotKit Runtime、AgentRunner、Mastra Agent 和当前 Thread Memory 获得流式回复；刷新页面后重放同一 Session，而不是重新提交消息。

**Blocked by:** 01 — Authenticated Chat shell and model catalog

**Status:** ready-for-agent

- [ ] 引入并精确锁定 CopilotKit React Core v2、CopilotKit Runtime、AG-UI、`@ag-ui/mastra`、Mastra、Provider Adapter 和 PostgreSQL Storage 的稳定版本；不得增加 AI SDK UI 或自定义平行流协议。
- [ ] Agent Host 获得独立 PostgreSQL Schema、Initializer、Owner 和 Runtime Role；Runtime 只验证精确 Schema，不执行自动 Migration，也不能读取 Auth 或 Core Schema。
- [ ] 未发送消息的 New Chat 只存在于浏览器状态；第一条合法文本被接受时才创建 Mastra Thread、持久 User Message 和 Agent Run，并将 URL 替换为该 Researcher 拥有的 opaque Session ID。
- [ ] Agent 使用部署中的 Mastra `instructions`、用户选定的注册模型和推理强度、当前 Thread Memory 生成回复；不存在第二个 Prompt Registry、Prompt 表或 ThesisTrace Planner。
- [ ] CopilotKit/AG-UI 流式传递 Run 开始、Assistant 内容、终态和安全错误；浏览器不根据纯 Token 文本反推 Agent 状态，也不维护第二套 Run 状态机。
- [ ] 当前 Thread 的 User/Assistant Messages 和 Run Metadata 在真实 PostgreSQL 中持久化；刷新或重新打开 URL 会重放已有内容且不会再次执行模型。
- [ ] 每个 Run 记录实际 Model Key、Provider Model ID、Reasoning Effort、Agent Build Revision、Token Usage 和 Terminal Status；改变 Thread 当前选择只影响下一次 Run。
- [ ] Mastra 只接收当前 Thread Memory；跨 Thread Recall、全账号语义 Memory、Global Working Memory 和其他 Researcher 内容保持关闭。
- [ ] V1 Composer 只接受有上限的文本，不显示上传、图片、音频、代码文件或外部 URL 附件入口；消息过大在模型调用前得到明确错误。
- [ ] 同一 Thread 的基本单活动 Run 约束由 AgentRunner 执行；此票不增加 Queue、Lease、`session_busy` Product State 或可恢复 Agent Job 表。
- [ ] Scripted Fake Model 可完全确定事件和回复，使协议、持久化、重放及 Model Metadata 测试不访问公网或付费 Provider；真实模型调用不进入默认测试。
- [ ] 使用真实 Agent PostgreSQL 覆盖首次创建、事务失败、重复请求、刷新重放、Agent Host 进程重启后的已完成 Session 读取、跨 Researcher Not Found 和清理隔离。
