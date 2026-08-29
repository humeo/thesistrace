# 12 — Real-model Eval and execution bounds

**What to build:** 建立与确定性工程测试分离的真实模型 Eval，用固定自然语言研究语料测量每个候选注册模型与推理强度完成 ResearchRun、Research Batch、DailyTrack 和结果解释的质量、成本、延迟与方差，并用实测证据固定可发布模型和 Agent 执行上限。

**Blocked by:** 07 — Research Batch through Chat; 08 — Safe DailyTrack flows through Chat; 11 — Content-free telemetry and runtime isolation

**Status:** ready-for-agent

- [ ] 建立版本化固定 Eval Corpus，覆盖清晰 Idea-to-Alpha、需要一次 Follow-up 的歧义请求、非法 Formula 修正、Strategy Backtest、Alpha 比较 Batch、DailyTrack Start/Refresh/Retry、长 Research Polling 和 Result Explanation。
- [ ] 每个 Case 定义可自动判定的任务 Outcome、必需/禁止 Tool Capability、Core Artifact、权限边界和最大成本/时间输入；不以模型回复逐字匹配作为成功条件。
- [ ] Eval 对每个候选 Model Key 与支持的 Reasoning Effort 执行固定且公开记录的重复次数，固定 Dataset、Clock Window、Corpus、Runtime Version 和配置，并计算多次运行方差。
- [ ] 报告至少包含 Task Success Rate、Invalid/Forbidden Tool Rate、Tool Retry/Error Rate、Admission Correction Success、Token Usage、Estimated Cost、P50/P95 Duration、Agent Step Count 和 Run-to-run Variance。
- [ ] Eval 使用真实 Provider、Auth Exchange、Core MCP 和 owned infrastructure，但由显式 Operator 命令启动；默认 Unit/Integration/E2E/Release Deterministic Gate 不访问付费 Provider 或把概率重试当成通过。
- [ ] Eval Report 只使用上一票批准的 Metadata 与 Core Artifact 判断，排除 Prompt、Message、Formula、MCP Payload、Credential 和 Provider Raw Body；报告可安全保留和比较。
- [ ] 根据第一轮基准为每个 Enabled Model/Reasoning Combination 固定最低成功率、最大 Tool Error、最大 P95、最大成本和可接受方差；未达门槛的组合从 Startup Registry 禁用而非增加自动 Fallback。
- [ ] 根据最差可接受成功轨迹与生产资源包络固定 Message Bytes、Context Tokens、Output Tokens、Tool Result Bytes、Tool Steps、Agent Run Wall Time、并发 Capacity 及 MCP Token Lifetime Margin。
- [ ] Provider-specific Reasoning Mapping 经过真实调用证明；不支持或语义不等价的 Effort 不出现在 Catalog，也不转换成未披露的 Provider 参数。
- [ ] Eval 能区分模型质量失败、Provider Failure、MCP Failure、Core Admission Rejection 和 Dataset/Worker Failure，避免把基础设施错误错误计算成模型能力。
- [ ] 重复 Eval 对同一 Runtime/Corpus 产生可比较的机器可读 Summary 和人类可读结论；阈值、模型启用状态和执行上限的变化需要显式 Review，不在运行时 Hot Reload。
- [ ] 至少一个系统配置的真实模型与一个支持的 Reasoning Effort 达到全部发布阈值；若没有候选组合达标，本票保持未完成且不得用 Scripted Fake Model 代替质量证据。
