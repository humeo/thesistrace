# Quantgrove 工作区设计 v1 生成提示词

使用内置 `image_gen`。每张主稿的实际提示词为“共享前缀 + 换行 + 对应页面提示词”；参考图均为 `research-workbench-v3-rules.png`，仅作为现有外框与品牌的编辑目标，`transparent_background: false`。

## 共享前缀

```text
Use case: ui-mockup.
Asset type: high-fidelity Chinese DESKTOP application screen, approximately 1600 x 1000, straight-on interface, no device frame.
Input image 1: edit target and established Quantgrove shell/style reference. Preserve its left sidebar proportions, folded-leaf/open-book logo, serif Quantgrove wordmark, thin-line Phosphor-style icons and warm neutral visual identity. Redesign only main workspace content and selected navigation state for the requested page. The output is a coherent usable product design, not a poster.
Style: canvas #FCFCF9, surfaces #FDFBFA, selected rows #F3F2EE, text/primary buttons #27251E, secondary text #5B5952, borders #DEDDD6; green #0F3D2E only for existing logo or semantic success. White/light throughout. 24px weight-500 main heading, Inter/Noto Sans SC-like sans serif for UI, monospace tabular numerals and code, 14-16px body, secondary text 12px minimum. 32px content gutters, 36px buttons, 40px inputs, 48px rows; 6px control corners, 12px grouped panels. Precise alignment and generous purposeful breathing room.
Sidebar: width 224px at 1440px equivalent. Preserve navigation order: 新建对话, 数据, 研究, 研究记录, 每日跟踪, MCP, history sections 过去 7 天 / 更早 with generic research conversation titles, 管理 and bottom 研究者 account. No personal email, no fake photos. Use actual folded-leaf identity from input, not a substitute.
Across the screen: cut redundant paragraphs; necessary explanations use small circled-i buttons; status, errors, units and critical constraints stay visible. Every control has readable contrast, labels never clip or wrap awkwardly. No marketing hero, gradients, decorative graphics, giant metric cards or invented capabilities. Add a small plain “示例数据” beside the page title for any illustrative data. Output one full interface screen with crisp correctly spelled Chinese, no design annotation outside the app. Do not use em dashes.
```

## 数据

```text
Page: 数据. Select 数据 in sidebar.
Design goal: users should immediately search the existing field catalog and read a selected field definition, with data readiness visible but compact.
Header: 数据 with subtle 示例数据, right action 刷新状态.
Below header: a single shallow full-width coverage band with four compact columns 行情 / 财务 / 行业 / 基准, each labeled 可用 and a coverage date; show “2010-01-04 至 2026-09-16”. Small inline info icon after “数据覆盖”. No description paragraph per dataset, no huge statistics.
Main area begins with 研究字段 and count “226”, a wide search input labeled 搜索字段 with placeholder “名称、含义或公式标识”, followed by compact existing category controls “全部 226”, “行情 22”, “财务 204” and dropdown “全部用途”.
Two-pane catalog below: broad table left (about 65%), quiet selected-field detail panel right (35%, only this content is grouped). Table columns 字段 / 公式名称 / 单位. Show 8 precise rows: 复权开盘价 open 元/股; 复权最高价 high 元/股; 复权最低价 low 元/股; 复权收盘价 close 元/股; 成交股数 volume 股; 成交金额 amount 元; 总市值 total_mv 元; 流通市值 circ_mv 元. Select 复权收盘价 with soft row background. Table text left aligned; code identifiers monospace. No row checkboxes implying multiselect.
Detail pane title 复权收盘价, code close with small 复制 action. Clear concise description “按复权口径计算的收盘价。” Labeled values 单位 元/股, 类型 日频序列. Existing definition detail in collapsible rows: “计算口径”, “缺失值”, “字段标识”. A small quiet formula example block “ts_mean(close, 20)” with label 公式示例, not an execute button.
Bottom compact pagination “1 / 10” with previous/next arrows, and collapsed “公共市场输入” with count “4 个表达式”. Footer metadata “行情截至 2026-09-16” and small information icon.
Do not invent export, upload, dataset editing or trading actions.
```

## 研究记录

```text
Page: 研究记录 list. Select 研究记录 in sidebar.
Main heading “研究运行”, subtle “示例数据”. A slim text-tab bar below: “运行” selected, “批次”. Keep existing routes and functions.
Replace the large full-width filter form with a compact aligned toolbar: label 文件夹 above dropdown 所有文件夹, label 类型 above dropdown 策略回测, and a right-aligned outline button “指标筛选” with a filter icon. Show an applied criterion “夏普 > 0” as a removable compact chip immediately below toolbar, with “清除” action. Do not add a search box or a status filter since those are not existing capabilities.
Main content is a flat readable research table, taking the wide space. Columns: 研究 / 创建时间 UTC (descending) / 状态 / 年化超额 ⓘ / 夏普 ⓘ / 最大回撤 ⓘ. Keep table headers short, numbers consistently aligned in columns, no stacked miniature metric clusters. Put research name boldish and research date range underneath in subdued text. Each research name is a link.
Five successful illustrative rows: “20 日动量轮动” | 09-28 08:36 | 成功 | +8.40% | 1.120 | 7.60%; “低波动组合” | 09-27 10:12 | 成功 | +5.72% | 0.940 | 5.18%; “成交额反转” | 09-26 14:08 | 成功 | +3.26% | 0.680 | 9.42%; “质量与动量” | 09-25 09:41 | 成功 | +6.18% | 1.030 | 6.84%; “估值均衡组合” | 09-24 16:22 | 成功 | +2.74% | 0.570 | 8.16%. All results are sample numbers, not actual claims.
First row has gentle hover/selected background, no checkboxes, no compare or export buttons. Keep “成功” neutral low-ink badges; negative metrics if present are clear numeric text, avoid decorative green everywhere.
A modest bottom pagination row “共 5 条”, “1 / 1”, disabled 上一页 and 下一页. Large remaining canvas stays calm.
At most one small tooltip open near 年化超额 heading: title “年化超额”, text “策略年化收益与基准年化收益之差。” Keep tooltip from covering first row values. No extra prose or performance KPI banners.
```

## 策略结果详情

```text
Page: research result detail for a successful strategy backtest. Select 研究记录 in sidebar.
Goal: evidence first, clear primary action, metric meanings on demand, frozen settings secondary.
Top breadcrumb is just “研究记录 / 20 日动量轮动”, not a folder selector. Header “20 日动量轮动” with small “策略回测”, neutral success badge “成功”, and visible “示例数据”. On right primary “开始每日跟踪”, secondary “用作草稿”, then a quiet three-dot more menu containing destructive management rather than a huge delete button.
Below compact metadata “2025-09-16 至 2026-09-16” and “默认文件夹”, without technical IDs crowding the header.
Text tabs in exactly this order: “概览” selected / “持仓历史” / “交易事件” / “公共输入” / “配置”.
Six concise aligned metrics in one flat band, no six card boxes. Each label has a small info icon: “累计净收益 +12.80%”, “沪深300累计 +4.40%”, “年化超额 +8.40%”, “最大回撤 7.60%”, “夏普 1.120”, “费用占比 0.42%”. All values illustrative.
Main chart full width below, heading “累计收益”, legend “策略净收益” in near-black solid line, “沪深300” in desaturated muted bronze/slate line with distinguishable dashes. Right compact range controls “1 年 / 3 年 / 5 年 / 全部”, 全部 selected. Chart x-axis 2025-09, 12, 2026-03, 06, 09; y-axis percentage 0%, 5%, 10%, 15%. Curves begin at 0%, have realistic varying rises and pullbacks, finish near 12.8% and 4.4%. No extra imaginary chart types, no drawdown subchart or export unless already available. This is a visual mock chart, not a claimed dataset.
Below chart a compact subsection “期末状态” with “目标股票仓位 100%”, “实际股票仓位 88.3%”, and “期末账户 2026-09-16”. Then collapsed evidence rows “选股资格”, “收盘风险口径”, “框架状态”, “计算口径”, ensuring all secondary evidence remains reachable.
Necessary contextual help appears only through info buttons; preserve error/progress blocks for corresponding states in implementation, but this screenshot shows success. No recommendation language or congratulatory returns.
```

## 每日跟踪

```text
Page: 每日跟踪. Select 每日跟踪 in sidebar.
Redesign the existing list and observation detail into one desktop master/detail composition, preserving every underlying resource identity. Do not invent strategy names; use readable short track identifiers with full identifiers accessible through a nearby info/copy entry. List and detail still represent existing routes.
Header “每日跟踪” and “示例数据”, action “重新加载状态”. No marketing subtitle.
Under header two panels with a real content hierarchy, not floating cards: a slim 250px track list on the left within main content, and a wide observation workspace on the right. Three track entries: “跟踪 A17C29” status “运行中”; “跟踪 B83F06” status “已阻塞”; “跟踪 C61E42” status “已停止”. Each entry has a quiet last-observation date; selected first entry warm-gray fill and a thin dark left edge. The list has heading “全部跟踪” count 3. No invented filter tabs or search.
Detail header “跟踪 A17C29” with precise badge “等待更新”. Actions “刷新至最新数据” (primary) and “管理” (quiet menu). An inline amber notice “有 2 个新交易日可更新” remains visible because it requires action; do not hide it in tooltip.
Compact three-column facts: “跟踪起点 2026-08-17”, “最近观察 2026-09-14”, “数据截至 2026-09-16”.
Four restrained inline metric values with small info icons and no individual cards: “跟踪收益 +2.34%”, “账户净值 ¥102,340”, “现金 ¥12,000”, “持仓 10 只”. Label units and numbers accurately.
Text tabs “表现” selected / “当前持仓 10” / “调仓计划”. Chart heading “跟踪表现” and a small segmented choice “跟踪以来” selected / “完整策略”. One fine near-black line chart from 08-17 to 09-14 with visible fluctuations and an ending value +2.34%; sparse labeled axes, no shaded area, no embellished upward-only arrow.
Bottom compact collapsed sections “持仓历史”, “交易事件”, “公共输入”, “更新详情”, “跟踪来源”. Fit key summary and chart without crowding; secondary evidence may continue below viewport.
Do not show auto-run toggles, brokerage trading, buy/sell controls, invented alerts or bulk actions. Tracking only advances after the existing explicit refresh action.
```

## MCP

```text
Page: MCP. Select MCP in sidebar.
Goal: make connection setup short and immediately actionable, retaining real service verification, tool groups, and authorization boundaries.
Header “MCP” and subtle “示例数据”, right status “服务可用” with a small meaningful check icon, timestamp “检查于 10:42”, and outline action “检查服务”. Do not repeat a giant Quantgrove MCP card or logo in the main area.
Main area two columns: broad connection panel 65%, narrower authorized-app panel 35%, one quiet vertical divider.
Connection heading “连接 AI 助手” with info button; text tabs “Codex” selected, “Claude Code”, “其他客户端”. A single sentence “复制设置提示，在客户端对话中完成连接。” and near-black primary button “复制设置提示”. A short flat flow line with three plain labels “添加服务器 → 批准访问 → 验证工具”; no giant numbered cards, no paragraphs under every step.
Collapsible “查看设置提示” is closed. “使用命令添加” is open, showing a neat monochrome terminal code block, no colored syntax clutter, with “复制命令” action:
codex mcp add quantgrove --url 'https://example.com/mcp'
Label above code “服务器地址仅为示例”. Below a second compact labeled command “登录授权”:
codex mcp login quantgrove
Keep the technical alias quantgrove exact. No secret keys or tokens. A short visible constraint “登录后核对请求的权限。”.
Right panel “已授权应用” count 1. One row “Codex” with neutral “已授权”. Show existing permission names in a concise readable list “读取研究”, “执行研究”, “读取跟踪”, “执行跟踪”, “离线访问”. Small timestamp “授权于 2026-09-28”. A subdued outlined “撤销授权” action with caution treatment, not the primary page action. The exact visible sentence “已授权不代表当前在线。” stays visible below, because it clarifies status.
Lower main section “工具列表” count “16 个工具”. Four accordion groups in flat 2x2 grouping or tidy full-width rows: “研究准备 3”, “研究运行 4”, “研究批次 3”, “每日跟踪 6”. Descriptive details are collapsed. Show small side-effect labels only inside expanded tool details, not as new buttons.
No app store gallery, no unsupported one-click integration, no sign-up, no extra clients, no claims of an online app when only authorization is known.
```

## 对话

```text
Page: 对话 empty state. This is a quiet working surface, not a marketing page. Select only 新建对话 in sidebar and do not add a new primary nav item. Keep the existing sidebar history.
Header top left main content “新对话” in restrained 24px size, a tiny information button nearby labeled visually with circled i. No folder breadcrumb or sample-data badge; this is an empty UI, not made-up results.
The center of the main workspace is a 720px-wide reading/composer column, positioned around the upper-middle (not too low). Left-aligned heading “想研究什么信号？” at about 26-28px, weight 500. Beneath it one modest line “从一个投资想法或一段公式开始。”
Directly below: one large calm message composer with a continuous light surface, thin border, radius 16px, approx 150px high. Placeholder “描述你的研究想法…”. No attachment button, microphone, web mode, example prompt cards, agent gallery or other invented tools.
Composer bottom row: left model dropdown “GPT-6 Luna” and compact reasoning choice “高”; right a 36px dark rounded send-arrow button in its disabled muted state because text is empty. A small information icon beside the model control opens explanatory help; help remains closed in the default screen.
Below composer only short keyboard hint “Enter 发送，Shift+Enter 换行”, soft but readable 12px.
No decorative alpha glyph, no “Research Agent” eyebrow, no signup CTA, no model-registration jargon or session-memory paragraph in the default view. Necessary model and current-chat scope explanation belongs behind the information entry. Keep unfilled space intentionally calm, focused on writing.
```

## 管理

```text
Page: 管理 / 研究员访问权限. Select 管理 at bottom of sidebar. Keep existing two top navigation tabs “研究员” selected and “数据”.
Header “研究员访问权限” with subtle “示例数据”. Primary near-black action at top right “邀请研究员”. No repeated page heading. Below slim tab line.
A compact toolbar for the researchers table: label “搜索研究员”, input placeholder “邮箱或显示名称”, adjacent “搜索” button. No irrelevant KPI cards, no permission toggles, role editing, account deletion or unsupported operations.
Wide flat table with 5 columns: “研究员”, “访问权限”, “最近登录”, “当前会话”, “操作”. The person cell uses name on first line, reserved example.com email on second line. Four illustrative rows:
周映川 / yingchuan@example.com / 启用 / 09-28 10:42 / 2 / 当前 Operator;
许书宁 / shuning@example.com / 启用 / 09-27 16:18 / 1 / 撤销会话;
孟知远 / zhiyuan@example.com / 启用 / 09-26 09:35 / 0 / 无活动会话;
陆晓棠 / xiaotang@example.com / 停用 / 09-22 14:06 / 0 / 无活动会话.
Current Operator label is protected, no revocation action for that row. The “撤销会话” action is quiet destructive text, with later confirmation implied, never a giant red button.
Show the second row expanded via a small chevron to reveal a compact two-column detail strip: “研究员 ID user_sample_shuning” / “创建时间 2026-09-14 14:07” / “有效邀请 无”. These facts remain accessible without forcing the main table to scroll horizontally. Keep full IDs as copyable detail, not as primary columns.
Pagination below “第 1 页” with previous/next arrows.
Lower section “邀请”, two compact rows with columns “邮箱 / 状态 / 到期时间 / 操作”: “ruoqing@example.com / 已投递 / 2026-10-05 18:00 / 重新签发”; “wenshu@example.com / 已过期 / 2026-09-26 18:00 / 重新签发”. Keep terminal status details available via row disclosure.
A single small circled-i next to 会话 explains the effect when activated, but consequences in a destructive confirmation must remain explicit; do not hide required approval text. Use no invented role management features.
```

## 每日跟踪定向修订

以对应主稿为编辑目标，替换最终交付图。

```text
Use case: ui-mockup.
Input image: edit target, the Quantgrove Daily Tracks design just generated.
Make a small correctness pass ONLY, keep all existing layout, sidebar, branding, typography, labels, chart and other content unchanged.
1. Restore the existing maximum-drawdown metric: change the four-metric summary band to five compact aligned metrics in this exact order: 跟踪收益 +2.34%, 最大回撤 2.85%, 账户净值 ¥102,340, 现金 ¥12,000, 持仓 10 只. Each has a small information icon, no individual cards. All five must fit neatly in the same band.
2. The header “重新加载状态” is a secondary action: make this button light background with thin border and near-black text. Keep “刷新至最新数据” as the only dark primary action.
3. In the left list, the blocked track B83F06's last observation must be “2026-09-11” (a trading day), replacing “2026-09-12”.
4. Next to the detail title “跟踪 A17C29” add one small quiet information icon to reveal the full identifier. Do not add any paragraph.
Keep the top visible 示例数据 label. Return the same full desktop screen with only these corrections.
```

## 研究记录定向修订

以对应主稿为编辑目标，替换最终交付图。

```text
Use case: ui-mockup.
Input image: edit target, Quantgrove research runs list.
Make ONLY a precise header/data consistency correction; preserve every other element, layout, table values, typography, colors, sidebar, tooltip and control.
Remove the small “默认文件夹” breadcrumb/dropdown above the main title entirely, because the page already has its own 文件夹 filter. Keep the page title “研究运行” at its existing position, with 示例数据.
In the first row “20 日动量轮动”, replace only the date range with exactly “2025-09-16 至 2026-09-16” to match its companion result-detail design.
Do not change other rows or add any content. Return the complete same desktop screen.
```
