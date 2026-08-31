# 05 — Session history and independent deletion

**What to build:** 让 Researcher 像使用成熟 Chat 产品一样从侧边栏创建、查找并管理自己的 Chat Sessions：空 New Chat 不落库，已有 Session 按时间分组和分页，可恢复、自动命名、手动重命名和删除；删除只清理 Chat，即使消息引用 Research 也不触碰 Core。

**Blocked by:** 02 — First durable streaming Chat Session

**Status:** ready-for-agent

- [ ] Session Sidebar 在 Workspace 链接下按最新活动时间和稳定 ID 排序，并以 Today、Previous 7 days 和 Older 等可理解分组展示；每页固定加载 30 条且不会一次读取全部历史。
- [ ] New Chat 始终是无持久 ID 的空状态；只有第一条消息成功被 Agent API 接受后才进入 Session 列表并更新 URL，放弃空状态不留下 Thread 或 Message。
- [ ] 第一次消息之后通过一个有界模型操作生成简短 Title 并存入 Thread Metadata；Title 失败不回滚主 Run，Session 保持清晰 Untitled 状态直到后续生成或手动重命名。
- [ ] Researcher 可通过键盘可操作的 Session Menu 重命名自己的 Session；空白、过长、错误 Owner、并发更新和持久化失败有明确结果且不产生第二份标题状态。
- [ ] 删除使用短而明确的不可逆 Chat 决策界面；它不是 MCP Approval，文案只说明 Thread、Messages、A2UI 和 Agent Run History，不暗示删除任何 Research。
- [ ] 当 AgentRunner 报告当前 Thread 有 Active Run 时不提供删除；V1 不把删除实现成隐式 Interrupt、Cancel 或等待中的删除任务。
- [ ] 删除事务只调用 Agent Store，清理该 Researcher 的 Thread、Messages、Run Metadata、Title 与关联生成 UI；不得调用 Core List/Delete/Cancel/Stop，也不得建立 Core Foreign Key 或 Cascade。
- [ ] 独立性测试在 Chat Message 中保存一个真实或 Fixture-backed Core ResearchRun ID，删除 Chat 后证明 Agent 记录消失，而 ResearchRun、Frozen Input、Result 和任何 DailyTrack 保持可读且未改变。
- [ ] Session URL 支持刷新、前进、后退和同源复制；Unknown、Deleted 或其他 Researcher 的 opaque ID 返回相同 Not Found 页面和 New Chat 入口，不泄露存在性。
- [ ] 切换两个 Researcher 账号不会显示、缓存或恢复另一账号的 Session、Title、Message 或当前 Model Preference。
- [ ] 桌面 Sidebar 折叠、移动 Drawer、Session Menu、Delete Decision、焦点恢复和状态文本满足现有设计系统及键盘/触控要求，不增加 Projects、Pins、Archive 或 Search。
- [ ] 使用真实 Agent PostgreSQL 覆盖稳定分页、边界时间分组、自动标题、重命名冲突、删除事务、Cross-Researcher Not Found、账号切换、刷新导航及 Research 独立性。
