# 05 — Session history and independent deletion

**What to build:** 让 Researcher 像使用成熟 Chat 产品一样从侧边栏创建、查找并管理自己的 Chat Sessions：空 New Chat 不落库，已有 Session 按时间分组和分页，可恢复、自动命名、手动重命名和删除；删除只清理 Chat，即使消息引用 Research 也不触碰 Core。

**Blocked by:** 02 — First durable streaming Chat Session

**Status:** complete

## Implementation Plan

1. Keep `agent.chat_session.updated_at` as the sole Session activity clock and
   `agent.mastra_threads.title` as the sole title value. Replace the existing
   Session history index with the exact owner/activity/ID order needed for a
   30-row keyset query; update the hard-cut schema artifact and exact catalog,
   without adding a migration, compatibility path, duplicate title column, or
   Core identifier relationship.
2. Add a strict Session management contract beside the existing runtime API.
   List only the authenticated Researcher's Sessions in
   `updated_at DESC, id DESC` order with a versioned opaque cursor and one
   look-ahead row. Return bounded safe fields only: opaque ID, title, created
   and activity timestamps, Thread version, and whether deletion is currently
   unavailable because a Run is active.
3. Generate an initial title as a separate, no-Tool, no-Memory Mastra model
   operation using the model selected for the accepted Turn. Bound it to one
   step, a small output limit, and a short abort deadline; validate one compact
   plain-text title before storing it. Schedule it only after atomic first-message
   acceptance, retry on a later new Turn while the sole title is `Untitled`,
   never roll back the primary Run, and never overwrite a concurrent manual
   rename.
4. Add owner-scoped rename with strict blank/length validation and optimistic
   concurrency against the returned Thread version. Lock the Session and Thread
   together, update only Mastra's title and Thread timestamps, and map absent or
   foreign IDs to the same Not Found outcome, stale versions to one explicit
   conflict, and storage failure to a safe unavailable result.
5. Add an AgentRunner-owned idle gate for immediate same-host exclusion and make
   the shared Agent Store transaction the concurrency authority. Carry one
   strict `new`/`existing` Session intent in the accepted Turn, serialize Run
   admission and deletion under the same per-Thread advisory lock, reject an
   active persisted Run, and never recreate an `existing` Session after delete.
   Do not introduce a domain Busy state, queue, lease, interrupt, cancellation,
   wait job, or persisted deletion workflow. On the supported one-replica Agent
   Host restart, terminally fail every interrupted `running` Run before serving.
6. Delete one owned Session in a single Agent Store transaction under the same
   per-Thread advisory lock used by Run admission. Remove that Thread's Mastra
   Messages, observational/A2UI state present in the Agent schema, workflow
   snapshots, title, `agent_run` history, and `chat_session`; never list, join,
   cancel, stop, delete, or otherwise call Core, and never delete Researcher-wide
   Mastra resources shared by other Threads.
7. Add a typed browser Session client and state hook with fail-closed response
   validation, bounded append-only pagination, explicit loading/empty/error
   states, account-uncached ownership, deterministic Today/Previous 7 days/Older
   calendar grouping, and refresh after acceptance, terminal title generation,
   rename, and delete.
8. Make Chat URL state respond to same-origin Session links and `popstate` while
   preserving the existing no-reload `replaceState` on first acceptance. Treat
   any malformed, duplicate, unknown, deleted, or foreign `session` query as the
   same explicit Not Found surface with a New Chat action; a genuinely empty
   `/chat` still owns only a fresh browser ID and no database row.
9. Replace the placeholder current-chat row with the real paginated history,
   generated/manual title in the 48-pixel header, keyboard-operable row menus,
   an accessible rename dialog, and a short irreversible Chat delete decision.
   Omit Delete for active Runs; state that Thread, Messages, generated UI, and
   Agent history are removed while Research remains independent. Preserve focus,
   Escape, touch targets, desktop collapse, and the mobile drawer without adding
   Search, Projects, Pins, or Archive.
10. Add deterministic unit and HTTP contract tests for cursors, title validation,
    bounded title generation/failure, owner mapping, optimistic rename, Runner
    gating, client validation, grouping boundaries, URL history, menus, dialogs,
    focus, and responsive states. Assert behavior and stable outcomes rather
    than generated title prose. Keep the paid, probabilistic title check separate
    as an explicit Operator-run fixed-corpus Eval reporting success, estimated
    cost, P50/P95 latency, and repeated-run variance.
11. Add real Agent PostgreSQL tests for 30-row stable pagination, equal-time ID
    order, first-title success/failure/retry, concurrent manual rename, active
    Run rejection, complete transactional deletion, cross-Researcher Not Found,
    account isolation, and restart-readable history. Extend the real Caddy/browser
    seam to prove rename, refresh/back/forward/copy, deletion, Agent-record
    removal, and unchanged Core ResearchRun Frozen Input and Result.
12. Run affected suites first, then all repository unit, integration, browser,
    Compose, and production-image gates. Review the fixed-base diff separately
    for repository Standards and this ticket's Spec, fix every finding, re-run
    affected acceptance, re-review to zero findings, mark only Issue 05 complete,
    and create its independent conventional commit.

- [x] Session Sidebar 在 Workspace 链接下按最新活动时间和稳定 ID 排序，并以 Today、Previous 7 days 和 Older 等可理解分组展示；每页固定加载 30 条且不会一次读取全部历史。
- [x] New Chat 始终是无持久 ID 的空状态；只有第一条消息成功被 Agent API 接受后才进入 Session 列表并更新 URL，放弃空状态不留下 Thread 或 Message。
- [x] 第一次消息之后通过一个有界模型操作生成简短 Title 并存入 Thread Metadata；Title 失败不回滚主 Run，Session 保持清晰 Untitled 状态直到后续生成或手动重命名。
- [x] Researcher 可通过键盘可操作的 Session Menu 重命名自己的 Session；空白、过长、错误 Owner、并发更新和持久化失败有明确结果且不产生第二份标题状态。
- [x] 删除使用短而明确的不可逆 Chat 决策界面；它不是 MCP Approval，文案只说明 Thread、Messages、A2UI 和 Agent Run History，不暗示删除任何 Research。
- [x] 当 AgentRunner 报告当前 Thread 有 Active Run 时不提供删除；V1 不把删除实现成隐式 Interrupt、Cancel 或等待中的删除任务。
- [x] 删除事务只调用 Agent Store，清理该 Researcher 的 Thread、Messages、Run Metadata、Title 与关联生成 UI；不得调用 Core List/Delete/Cancel/Stop，也不得建立 Core Foreign Key 或 Cascade。
- [x] 独立性测试在 Chat Message 中保存一个真实或 Fixture-backed Core ResearchRun ID，删除 Chat 后证明 Agent 记录消失，而 ResearchRun、Frozen Input、Result 和任何 DailyTrack 保持可读且未改变。
- [x] Session URL 支持刷新、前进、后退和同源复制；Unknown、Deleted 或其他 Researcher 的 opaque ID 返回相同 Not Found 页面和 New Chat 入口，不泄露存在性。
- [x] 切换两个 Researcher 账号不会显示、缓存或恢复另一账号的 Session、Title、Message 或当前 Model Preference。
- [x] 桌面 Sidebar 折叠、移动 Drawer、Session Menu、Delete Decision、焦点恢复和状态文本满足现有设计系统及键盘/触控要求，不增加 Projects、Pins、Archive 或 Search。
- [x] 使用真实 Agent PostgreSQL 覆盖稳定分页、边界时间分组、自动标题、重命名冲突、删除事务、Cross-Researcher Not Found、账号切换、刷新导航及 Research 独立性。

## Verification and Review

- Standards and Spec independently re-reviewed the identical staged patch
  `480e4776244083bce96d9f93d67aaa9dcb2416fdf7e616038d3e3c1a210d6cda`
  from fixed base `7832df3`; both final reviews reported zero findings.
- Review fixes added real Hook unmount cancellation coverage, DESIGN-token
  alert colors, shared transaction setup, monotonic Thread versions across Run
  admission, and a real PostgreSQL regression proving a stale pre-admission
  rename cannot cross an ABA boundary.
- `pnpm test`: Ruff passed; Python `917 passed`; Agent `202 passed`; Auth
  `163 passed`; Web `151 passed`; every TypeScript typecheck passed.
- Final isolated Agent PostgreSQL acceptance: `26 passed` (19 runtime and 7
  physical-schema tests), including stable 30-row keyset pagination, title
  races and retry, optimistic rename, admission/delete serialization,
  ownership isolation, restart recovery, complete Agent-record deletion, and
  the monotonic-version regression. Evidence run:
  `20260830t170348z-81458-d78ab2d8`.
- Full repository integration passed before the final repository-only version
  fix: Core `370 passed, 8 deselected`, all six restart scenarios, Auth
  PostgreSQL `89 passed`, and Agent PostgreSQL `25 passed`; the affected Agent
  suite was then rerun at `26/26` after the fix.
- Production browser acceptance proved reload/back/forward/copied URLs,
  generated and manual titles, mobile and keyboard menus, focus restoration,
  active-Run deletion exclusion, visible retry after injected failure, and
  deletion of all Agent records. The independent-delete flow proved the linked
  Core ResearchRun, Frozen Input, Result, and DailyTrack remained readable and
  field-for-field unchanged.
- The production Web build and bundle budget passed with `11` assets,
  `1,537,433` total bytes, and `1,470,051` JavaScript bytes. `git diff --check`:
  passed.
