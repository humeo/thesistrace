# Research 工作区 v2 生成提示词

生成方式：内置 `image_gen`。选定交付物及交互说明见 [布局方案](research-workbench-v2.md)。

## 规则配置

参考输入：`docs/design/quantgrove-brand-reference.png`，仅用于品牌身份。

```text
Use case: ui-mockup
Asset type: a single polished high-fidelity desktop application design screen for Quantgrove, landscape 1600 x 1000 approximately. Crisp flat UI screenshot, edge to edge, no browser frame, no presentation labels.
Primary request: a substantial information-architecture and layout redesign of a Chinese quantitative-research strategy backtest workspace. It should feel like an intentional editing workbench, not a long settings form. This screen shows the "配置交易规则" mode with the "组合构建" stage selected. The layout below is the essential design change.
Reference image: BRAND REFERENCE ONLY. Reuse the small folded green book/leaf mark and Quantgrove serif wordmark. DO NOT copy the brand board composition, sample dashboards, English copy, serif headings, sample metrics, or green primary buttons.
Style: warm, precise, reading-first research software. Canvas #FCFCF9, subtle sidebar #F3F2EE, editor/panels #FDFBFA, ink and primary button #27251E, secondary copy #5B5952, separators #DEDDD6, inputs outlined #8A8880. Only the small logo is forest green #0F3D2E. No strong shadows, gradients, hero graphics, charts, fake performance, oversized rounded cards, or ornamental labels. Use Inter and Noto Sans SC-like sans serif for interface, serif ONLY for "Quantgrove". Main title 24/32 medium weight 500, ordinary labels 14-16px, secondary text 12-14px. Readable Chinese with natural spacing. 4px spacing rhythm, 6px controls, at most 12px editor corners. Excellent alignment and whitespace.
Composition:
A. A 224px full-height global sidebar at far left. At top the small Quantgrove mark and wordmark plus collapse control. "新建对话" quiet outlined button. Navigation in exact order with fine line icons: "数据", selected "研究", "研究记录", "每日跟踪", "MCP". Preserve chat history beneath: "过去 7 天", "Greeting", "更早", "未命名". Bottom "管理" and generic account "研究者" with avatar; no personal email.
B. Main header at top, about 96px high, spans remaining width. A compact folder selector "默认文件夹" sits just above an EDITABLE RESEARCH NAME "20 日动量轮动" with a tiny pencil icon. Use this name as the page title instead of a repetitive large generic heading. At the right of the same header: secondary "+ 新建研究", outlined "检查配置", near-black "运行回测" with play icon. This is the persistent command area; do NOT repeat run buttons at the bottom.
C. Directly underneath, a single restrained 60px mode strip. First group has label "研究类型" with horizontal text tabs "因子评估" and selected "策略回测", selected shown by dark underline. A fine vertical divider separates second group labeled "编写方式", followed by a small segmented choice "配置交易规则" selected and "完整 Python 策略" inactive. Both levels remain visible together, no big gray radio box.
D. Below that, split into a spacious central WORK CANVAS (roughly 850px) and a FIXED 320px full-height RIGHT INSPECTOR. Separate with one thin vertical line, NO standalone rounded card around the right inspector. Central canvas has 32px padding; right inspector 24px padding and a subtly distinct warm-white surface. The whole body uses the available height.
E. CENTRAL WORK CANVAS. At the top, a horizontal strategy-flow navigation ribbon: four connected stages in one coherent strip, separated by subtle rightward chevrons, NOT four floating cards and NOT a mandatory wizard. Each stage has a short title and a smaller current-value summary:
"股票池" / "流动性前 300 只"
"选股信号" / "20 日动量"
"组合构建" / "10 只 · 等权" (SELECTED with subtle warm-gray background and dark bottom rule)
"风险管理" / "未设置额外规则"
Use no validation checks, fabricated completion statuses or percentages. This is freely navigable editing, not a result.
F. Below the flow ribbon, generous 28px gap and one section title "买多少、什么时候换仓？" around 20px medium, with a quiet "</> 用 Python 自定义" action at far right. Subtitle "设置持仓数量、选股间隔，以及资金如何分配。"
Then a clean aligned 2-column form on the OPEN CANVAS, no container-card:
first row label "持仓数量" with a compact [- 10 +] stepper; second column label "选股间隔（交易日）" with [- 5 +].
second row left "组合权重" dropdown "等权重"; second row right "股票仓位如何确定？" dropdown "固定比例".
third row left "股票仓位（%）" input "100" with percent unit; right has a small regular explanation "剩余资金保留为现金。" with ample space, not a new card.
Below a fine separator, a disclosure row "最短持有期" with "可选 · 未设置" and chevron. Below another disclosure "研究备注" with "可选". These are existing controls, not new features.
G. Near the lower part of the central canvas, show the existing strategy summary as a quiet compact reading block introduced by "这套策略会怎样运行". One or two readable sentences: "从流动性最高的 300 只股票中，优先选择近 20 日涨幅高的股票。每 5 个交易日选股，最多持有 10 只，等权分配。" Then muted "未设置额外退出条件。" No performance metrics. Summaries describe example configuration only.
H. RIGHT INSPECTOR. Title "回测条件" 17px medium. Group "研究日期": labels "开始日期" and "结束日期" with inputs "2023-09-18" and "2026-09-16", calendar icons. Beneath a compact row "1 年" "3 年" "5 年" "全部". Fine divider. Label "初始资金（CNY）" field "100,000.00". Fine divider. Accordion row "费用与滑点" with chevron; muted summary underneath "佣金 0.03% · 滑点 0 bp". A second muted line "按当前回测设置模拟成交。" Keep field browsing and all programming parameters OUT of this common run inspector. No duplicated name field because the header title is editable.
At lower right a modest note "收盘后判断，下一交易日开盘模拟交易。交易限制可能导致无法成交。" It belongs in the inspector, readable but secondary.
I. A slim bottom status line across main area, no large buttons: left tiny document icon "草稿已保存到此浏览器", right "行情数据截至 2026-09-16".
Constraints: this is a desktop strategy-authoring workspace before running. No charts, results, success claims, cost estimates, extra navigation, AI suggestions, new backend features, pricing or decorative illustration. All stated values are illustrative draft inputs. Preserve the actual four strategy modules and both authoring modes. Each stage can be edited independently. The central form and entire right inspector should fit on one screen, balanced and calmly dense. Render the Chinese text faithfully. Make the editor/workbench hierarchy visibly different from a conventional stacked form.
```

## 完整 Python 策略

参考输入：本轮规则配置稿，保持共同外框。

```text
Use case: ui-mockup
Asset type: high-fidelity Quantgrove desktop application design, a companion screen to the provided redesigned strategy workbench.
Input image: approved new workbench layout reference. Keep its global sidebar, top command header, the fixed right inspector, the bottom status line, canvas dimensions, palette, typographic family and alignments. Create the COMPLETE PYTHON STRATEGY MODE of this same design. Not a new visual theme.
Changes:
1. Editable name in the header becomes "动量择优策略". Use noticeably calm 24px logical, medium weight 500; avoid heavy large bold. The header actions remain "+ 新建研究", "检查配置", "运行回测". Folder "默认文件夹" remains.
2. In mode strip, "策略回测" remains selected and "完整 Python 策略" becomes selected instead of "配置交易规则". The research type and authoring mode groups remain plainly separate.
3. Replace the CENTRAL four-stage ribbon, portfolio form, and rule summary with a focused code workspace. The complete Python program owns all strategy decisions, so DO NOT show the four-stage ribbon in this mode.
4. At the top of the central area a short explanation: "用 Python 定义完整的选股、仓位和退出决策。". Below that one horizontal editor tab bar: selected "Python 源码", inactive "数据声明", "外部参数", "研究备注". At the right a quiet "浏览字段" control. These reorganize existing inputs; no new capabilities.
5. A LARGE light-theme code editor is the dominant central area, with line numbers and tasteful syntax coloring (muted green strings, restrained plum keywords, charcoal names). White-warm #FDFBFA background. 14px logical monospace at legible density. It begins near y300 and extends near the bottom status bar. No dark IDE theme. Show the actual source below, preserve indentation and line numbers, long lines may wrap within the editor. A thin internal scrollbar indicates source editing; not a webpage cut off.
CODE EXACTLY:
def decide(context, state, parameters):
    history = context["history"]
    prices = history["fields"]["price.close.adjusted"]
    candidates = {row["instrument_id"] for row in context["candidates"]}
    scores = {}
    for instrument, closes in zip(history["instruments"], prices):
        if closes[0] is not None and closes[-1] is not None and closes[0] > 0:
            scores[instrument] = closes[-1] / closes[0] - 1
    eligible = [item for item in scores if item in candidates]
    output = None
    if eligible:
        best = max(eligible, key=lambda item: (scores[item], item))
        held = [row["instrument_id"] for row in context["account"]["positions"]]
        held_score = max((scores.get(item, -1) for item in held), default=-1)
        if best not in held and (not held or scores[best] > held_score + parameters["improvement"]):
            output = {
                "reason": "better_momentum_candidate",
                "allocation": {"mode": "rebalance", "instrument_ids": [best],
                               "relative_weights": {best: "1"}, "exposure": 1.0},
                "position_limits": {},
            }
    state["decisions"] = state.get("decisions", 0) + 1
    return {"output": output, "state": state}
END CODE.
6. Directly below the editor a slim metadata/footer row: "1 个声明字段 · 最近 6 个交易日" on left; "Python 使用说明" link on right. No fake successful validation. The tabs expose the existing declared fields/history and JSON parameters; don't expand those forms in this screenshot.
7. Preserve the fixed RIGHT INSPECTOR titled "回测条件". The date fields, shortcut ranges, initial capital 100,000.00 and collapsed "费用与滑点" remain. Add the EXISTING direct-mode "股票池" dropdown with "前 300 只" between dates and initial capital, with short essential helper "按流动性排序，非指数成分股。". Fit all groups with consistent spacing. Keep the bottom note "收盘后判断，下一交易日开盘模拟交易。交易限制可能导致无法成交。" Do not put code-specific data declarations or external parameters into this run inspector.
8. Keep the bottom status text "草稿已保存到此浏览器" and "行情数据截至 2026-09-16".
Invariants: same Quantgrove folded-book mark and wordmark, sidebar navigation, chat history, management and generic account. Same main header, research-mode hierarchy, no external browser chrome, no fake results/charts, no extra buttons, no AI assistant panel. Serif only for brand; Chinese headings and text use a clean sans serif with medium weight. This is an editable example draft, not an executed backtest. High-fidelity crisp screen, not a diagram.
```

## 因子评估

参考输入：本轮规则配置稿，保持共同外框。

```text
Use case: ui-mockup
Create the FACTOR EVALUATION companion screen to this newly redesigned Quantgrove workbench. Input image is the exact outer-shell and style reference. Preserve canvas size, global sidebar, brand mark, navigation, chat history, top command header, thin-divided full-height right inspector, bottom status line, warm palette and typography.
This is the same cohesive product, changing modes to "因子评估". It must not display strategy-only controls.
Top: folder "默认文件夹", editable research title "20 日动量检验" with tiny pencil icon. Title 24px logical medium weight 500, not huge or heavy. Right actions "+ 新建研究", outlined "检查配置", near-black primary "运行评估".
Mode strip: "研究类型" with "因子评估" selected by a dark underline and "策略回测" inactive. Omit the strategy-authoring mode group because it does not apply. Instead a quiet noninteractive sentence at right "检验评分公式与未来收益的关系。"
CENTRAL WORK CANVAS:
Remove the four-stage strategy ribbon, portfolio form and strategy summary completely.
At the top a quiet header row "Alpha 公式" with "浏览字段" at right.
Below, a generously wide light CodeMirror formula editor on a warm-white surface, about 280px logical high. Small line-number gutter, thin dividers, no card shadow. Three line numbers, exact code on line 1: rank(pct_change(close, 20)). Use restrained syntax color and comfortable monospace text. Footer helper "Ctrl + 空格显示补全建议". This editor is for writing a formula; do not show validation results.
Below the editor, separated with 24px of space and a fine rule, an open research notes area. Heading "研究备注" plus quiet "可选". Textarea or open lined note surface with exact sample text "检验过去 20 个交易日的价格动量，能否识别未来收益更高的股票。". About 120px height. Keep remaining whitespace purposeful, no metric cards or suggestions.
RIGHT INSPECTOR:
Title "运行设置". Date group with "开始日期" input "2023-09-18", "结束日期" input "2026-09-16", calendar icons and "1 年" "3 年" "5 年" "全部" shortcuts.
Fine divider. "股票池" dropdown "前 300 只". Helper "按最近 20 个交易日的平均成交额排序，成分随时间变化。非指数成分股。"
Fine divider. "中性化" dropdown "无".
Do NOT show initial capital, costs, slippage, holdings, selection intervals, risk management, or trading execution text in this factor mode. Keep empty space below the settings calm rather than filling it with invented functionality.
BOTTOM STATUS LINE:
Left "草稿已保存到此浏览器"; right "行情数据截至 2026-09-16".
Preserve the original research capability, formula, field browsing, notes, dates, universe and neutralization. The research name is edited in the header and is not duplicated as an inspector field. No fake metrics, charts, result labels, AI assistant, automatic recommendations, tool implementation jargon or new features. All Chinese text readable and correctly written. Global sidebar remains 224px logical; right inspector remains about 300-320px logical; remaining room belongs to the writing canvas. Canvas #FCFCF9, soft #F3F2EE, text and primary #27251E, separators #DEDDD6, control outline #8A8880. Green only for the existing brand mark. Serif only for the Quantgrove wordmark, all other interface text in Inter/Noto Sans SC-like sans serif. Crisp production-quality straight-on desktop UI with precise alignments and medium-weight headings.
```
