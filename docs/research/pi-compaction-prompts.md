# Pi 会话压缩流程与提示词

Date checked: 2026-09-06

## 核对范围与版本

本笔记核对官方仓库 [earendil-works/pi](https://github.com/earendil-works/pi) 的提交
`9767ba275f3e9a5ee0f5c5342249b629ab1b2282`。该值由本次只读
`git ls-remote https://github.com/earendil-works/pi.git refs/heads/main` 取得；该提交的
[coding-agent package.json](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/package.json#L1-L4)
版本为 0.85.1。源码采用 [MIT 许可](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/LICENSE)。

本地 `/Users/koltenluca/code-github/pi-mono` 位于 `main`，HEAD 为
`086c32e74530564922d011ade23ff582c9d63116`；其 `origin` 仍指向会重定向的
`badlogic/pi-mono`。本次没有切换、拉取或修改该工作树。远程固定提交的文件读取到临时目录后核对，
避免把本地较旧源码或浮动 `main` 的缓存当成同一版本。

本笔记是研究记录，未修改 ThesisTrace 运行时代码。以下提示词内容为中文释义和结构示意，
完整英文原文通过固定提交、准确行号链接查看。

2026-09-07 的最终实施范围：M 和 S 均仅属于当前 Session，取消用户级共享。
统一调度、模型预算和工具输出的完整实施计划见
[Session 上下文压缩 spec](../../.scratch/session-context-compaction/spec.md)。

## 记忆与摘要是不同的层

用户要求的上下文结构是：

```text
固定指令和工具 + 固定记忆 M + 固定会话摘要 S + 保留消息 R + 后续追加消息
```

其中 M 是仅属于本 Session 的独立记忆块，S 是本会话压缩得到的交接摘要；两者不供其他 Session 使用。Pi 核心的 compaction 对应 S：
`buildContextEntries` 选出最新 compaction、从 `firstKeptEntryId` 起的保留项和之后新增项；
compactionSummary 在转换给模型时成为包含 `<summary>` 的 user 消息。
这不能证明 Pi 原生还有一条 Mastra Observer/Reflector 式自动记忆管线。
见 [上下文重建](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/session-manager.ts#L357-L439)、
[摘要消息转换](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/messages.ts)。

Pi 另有独立的 system/contextFiles 装配：资源加载器自动发现的上下文文件候选包括
`AGENTS.override.md`、`AGENTS.md`、`CLAUDE.md`；这不是自动生成独立长期记忆的压缩算法，
也不能把社区的 pi-memory 扩展算作核心能力。
见 [system prompt](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/system-prompt.ts)、
[ResourceLoader](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/resource-loader.ts)。

对 ThesisTrace 的设计含义：如果采用用户要求的 M + S 两块，就应明确保存两份产物并各自定义职责。
Mastra 记忆不能仅改名为 Pi 摘要，也不能把 Pi 摘要误当成已经实现了独立记忆。
两块在同一次压缩周期内更新、周期结束后固定，是本项目的调度选择，不是 Pi 原生提供的双层管线。

## Pi 的压缩过程

1. **选保留区。** 从最新消息向前累计 token 估计，寻找约 `keepRecentTokens` 的保留区，默认 20,000。
   切点可以落在用户类消息或 assistant 消息上，不能落在 tool result 上；保留工具结果时要保留对应调用。
   见 [默认设置](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L126-L136)、
   [切点规则](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L308-L461)。
2. **选待摘要区。** 首次从会话起点选到本次切点之前；后续从上次 `firstKeptEntryId` 开始，
   因此上次保留、这次已变旧的消息也进入本次摘要。上一版摘要通过 `previousSummary` 单独提供。
   见 [待摘要区间](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L758-L803)。
3. **调用摘要模型。** 本次移出的消息序列化为文本，与上一版摘要一起送入专门的摘要请求，
   生成可供另一个模型继续工作的结构化摘要。
   见 [摘要请求](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L642-L726)。
4. **处理长轮次。** 切点落在一个长轮次中时，更早的完整历史与这个轮次的前半段分别摘要，
   后半段保留原文。当前实现先生成历史摘要，再生成轮次前缀摘要，最后拼接成一份摘要。
   见 [长轮次处理](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L887-L947)。
5. **保存检查点。** 代码累计 read/write/edit 文件操作并追加文件列表，会话层追加 `CompactionEntry`，
   保存 summary、firstKeptEntryId、token/usage 信息及 details，然后重建模型上下文。
   压缩前原始记录仍留在会话存储中。
   见 [文件记录累计](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L42-L69)、
   [压缩结果](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L949-L963)、
   [官方 CompactionEntry 说明](https://pi.dev/docs/latest/compaction#compactionentry-structure)。

## 摘要请求与消息处理

`buildSummarizationContext` 单独构造摘要 system prompt，messages 中只有一条 user 文本消息，
不挂载 coding-agent 工具。下图是结构示意，不是原文提示词：

```text
system: 专门的摘要指令

user:
<conversation>
本次待摘要消息的序列化文本
</conversation>

<previous-summary>
上一版摘要；首次压缩时没有这一段
</previous-summary>

首次或更新摘要指令
可选的用户指定摘要重点
```

见 [独立摘要上下文](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L641-L653)、
[动态内容装配](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L677-L713)。

消息序列化保留用户文本、assistant 文本、可用的 thinking 文本、工具名称和参数、工具结果文本，
并附上角色标签。图片等非文本内容不会作为原始图像输入该纯文本摘要请求。
**每条工具结果在摘要输入中只保留前 2,000 个字符，后接截断标记。** 单位是字符，不是 tokens；
它不是主模型工具结果的输出上限。用户文本、assistant 文本和工具调用参数没有同一条 2,000 字符限制。
见 [序列化与工具结果限制](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/utils.ts#L88-L150)。

## 当前实际使用的提示词

| 提示词 | 中文释义 | 完整原文与调用位置 |
| --- | --- | --- |
| `SUMMARIZATION_SYSTEM_PROMPT` | 读取用户与助手的对话，严格按指定格式输出结构化摘要；不得继续对话，不得回答被总结对话中的问题。普通摘要与长轮次前缀摘要共用。 | [原文 utils.ts:156–158](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/utils.ts#L156-L158)、[装配](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L641-L653) |
| `SUMMARIZATION_PROMPT` | 为另一个模型生成可接着工作的交接摘要，写清目标、约束、进展、决策、下一步和关键上下文；保留准确路径、函数名和错误信息。 | [原文 compaction.ts:467–498](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L467-L498) |
| `UPDATE_SUMMARIZATION_PROMPT` | 将新消息合并进旧摘要；保留仍相关的已有信息，补充新增事实，更新完成状态、阻塞和下一步，删除已失效内容。`UPDATE_SUMMARIZATION_INSTRUCTIONS` 被插值到此提示词中，并非另一轮模型调用。 | [原文 compaction.ts:500–539](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L500-L539)、[实际选用](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L677-L693) |
| `TURN_PREFIX_SUMMARIZATION_PROMPT` | 为被保留的长轮次后半段补充前情，写清本轮原始请求、前半段做了什么、理解后半段还需要什么。 | [原文 compaction.ts:835–848](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L835-L848)、[实际选用](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L983-L998) |

普通会话摘要的结构，以下为中文释义：

```text
目标
约束与偏好
进展
  已完成
  正在进行
  阻塞
关键决策及原因
下一步，按顺序列出
继续任务所需的关键上下文
```

这是一份当前会话的交接状态，并不是一份只保存长期用户事实的记忆清单。
来源为上表首次和更新摘要提示词。

## 预算、完成校验与缓存边界

Pi 原生正常触发条件为 `contextTokens > contextWindow - reserveTokens`，默认 reserveTokens 为 16,384。
**用户为 ThesisTrace 指定的 90% 阈值属于本项目方案，不是 Pi 默认设置。**
见 [默认设置](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L132-L136)、
[触发公式](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L235-L238)。

普通摘要输出上限为 `min(floor(0.8 × reserveTokens), model.maxTokens)`；长轮次前缀摘要为
`min(floor(0.5 × reserveTokens), model.maxTokens)`。在默认 reserveTokens 下分别为 13,107 和 8,192，
若模型输出上限更小再取较小值。这些是摘要请求的生成上限，不能拿来解释主模型通用输出限制。
见 [普通摘要预算](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L672-L675)、
[前缀摘要预算](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L983-L986)。

模型返回 error 或 length 时，摘要失败，不能把到达 token 上限的残缺文本当作会话检查点；
摘要模型尝试调用工具也会报错。
见 [失败判定](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L541-L553)、
[普通摘要校验](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L715-L721)、
[前缀摘要校验](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L1000-L1006)。

摘要请求和主模型请求的缓存需要分开：`completeSummarization` 为摘要请求设置 `cacheRetention: "none"`，
使用调用方提供的 routing session ID，没有时生成一个新的 ID。官方文档说明 compaction/branch summary
使用新的 routing ID，并在 provider 支持时禁用缓存写入；这不等同于关闭普通主模型请求的 prompt cache。
见 [摘要调用选项](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/src/core/compaction/compaction.ts#L579-L599)、
[官方缓存说明](https://pi.dev/docs/latest/compaction#overview)。
