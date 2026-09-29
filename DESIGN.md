---
version: 6
name: Quantgrove
status: implementing
referenceImage: "docs/design/quantgrove-brand-reference.png"
pinnedAt: "2026-09-28"
referenceDesign: "docs/design/linear-designmd-source.md"
brand:
  name: "Quantgrove"
  tagline: "Ideas grow through evidence."
  taglineZh: "让想法，在证据中生长。"
  descriptor: "A quant lab for curious minds and agents."
  forest: "#0F3D2E"
  sage: "#A7B3A1"
  stone: "#D9D6CC"
  ivory: "#FAF9F4"
  charcoal: "#1F1F1F"
typography:
  display: "Inter, Noto Sans SC, -apple-system, BlinkMacSystemFont, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif"
  brand: "Inter, Noto Sans SC, -apple-system, BlinkMacSystemFont, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif"
  body: "Inter, Noto Sans SC, -apple-system, BlinkMacSystemFont, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif"
  mono: "Geist Mono, JetBrains Mono, SFMono-Regular, Consolas, Liberation Mono, monospace"
---

# Quantgrove design

The [user-supplied Linear DesignMD source](docs/design/linear-designmd-source.md) is the visual reference; its structure and formatting are preserved in that file. It describes a marketing site, so apply its near-black canvas, four-step dark surface ladder, lavender-blue accent, sans-serif hierarchy and compact controls to Quantgrove without copying Linear branding, features or marketing-scale whitespace into the research console. The source does not specify numeric values for each raised surface; the console defines these explicitly below. Existing content, routes, accessibility and functional contracts remain in force. Linear's proprietary fonts are not bundled; use locally hosted Inter / Noto Sans SC for display and interface text.

The [Quantgrove brand board](docs/design/quantgrove-brand-reference.png) defines the product identity and approved assets. The [Linear DesignMD source](docs/design/linear-designmd-source.md) defines the product's visual direction. Its product descriptions and measurements are reference material, not Quantgrove features or data. The brand board's sample navigation, people, models, research counts and returns are illustrative, not product requirements or claims.

## Approved scope

The Research editor and its sidebar established the first implementation slice. The approved next slice covers Data, Research Runs and batches, result details, Daily Tracks, MCP, and Operator pages. Chat messages and the composer share a compact, centered reading column; all routes share the approved Research sidebar appearance. The target rules below describe the shared system; `status: implementing` records that the migration is in progress.

The Research workspace uses a 600-weight sans-serif 28px page title, with natural Chinese spacing. Its research type and strategy authoring choices stay visible together in a quiet, grouped control area above the editor.

The remaining console pages follow the approved `console-redesign-v1` Data, Runs, Daily, MCP and Admin references. Their opt-in `console-workspace` surface uses the dark tokens. The shared sidebar follows the Research appearance across all routes, including New Chat and history. Page titles use 28px/1.2 and major section titles use 24px/1.25 at weight 600 in the locally hosted sans-serif stack. Desktop catalog rows use 44px and research/directory rows use 80px, with 16px tabular values and subtle dividers. Data pairs catalog controls/list with a definition pane; Daily pairs a 280px selection pane with observation metrics and a 216px plot. Explanations use accessible hover/click annotations or disclosure rows; errors, degraded coverage, dates and units stay visible. Reference dimensions guide hierarchy and spacing, never fabricated data or changes to the 240px sidebar.

The result detail follows the approved `docs/design/console-redesign-v1-result.png` composition. Its title uses a 600-weight 28px sans-serif display with inline type/status badges; dates and the folder share the metadata line. The six-metric band uses compact 13px labels and 24–28/36 sans-serif tabular values, with inset dividers. Tabs lead directly into this band. Keep 12px between the metric band, approximately 334px desktop return chart, three-column ending-state panel and shared-border disclosure rows. The strategy curve uses the lavender chart token and the benchmark is neutral gray and dashed. Help opens on hover, focus or click. Draft folder selection opens from the header and deletion stays in the secondary menu. The sidebar uses the shared 240px width and Chat history retains its content; reference values and curves remain illustrative.

**Dark, evidence-first research（深色、克制、以证据为中心的研究空间）**

| Surface | Required treatment |
| --- | --- |
| Public landing | Apply the dark typography, controls and surface ladder. Preserve its actual copy, approved botanical asset, interactive preview, anchors, destinations and English/Chinese switching. |
| Login, invitation, access and MCP consent states | Use the dark surface system and shared controls while preserving existing fields, validation and authentication behavior. |
| Console, including Chat, Data, Research, Research Runs, batches, Daily Tracks, MCP and Operator | Use one evidence-first workspace while preserving capabilities, navigation, URLs, resource identities and service contracts. |
| Email, browser title, metadata, accessible names and favicon | Use Quantgrove consistently. Email uses its own email-safe markup and system fonts. |

The public landing is the brand baseline. Its decorative layout and mock data must not replace production console pages. Shared changes must be checked against its current desktop rendering.

## Brand assets and naming

- The visible product name is **Quantgrove** in both languages. Do not introduce a Chinese transliteration or retain the old Chinese product name.
- Use the folded-leaf/open-book mark, sans-serif wordmark, inverse mark for dark surfaces, and white mark on a forest-green app icon. Master assets are SVG; email and favicon exports include PNG.
- Preserve proportions and check the mark at 16, 24 and 32px. Use real assets without blend modes, stretched dimensions or the whole reference board as a background.
- Reuse the Web brand component for marks and wordmarks. A linked brand has an accessible name; its decorative mark has empty alternative text.
- Update all public QuantTrace/ThesisTrace strings, including authentication-provider display name, email subjects and body, access states, MCP instructions and consent.
- Repository/package names, environment variables, routes, database identifiers, Cookie prefixes and saved MCP client aliases are technical contracts, not display branding. Keep them unchanged. Instructions must still reference the actual configured client alias when selecting or logging into it.
- Preserve the legacy image resource referenced by already-delivered email; new surfaces use the Quantgrove assets.

## Typography and Chinese

| Role | Latin | Chinese |
| --- | --- | --- |
| Brand wordmark | Inter | Noto Sans SC |
| Public and answer headings | Inter | Noto Sans SC |
| Console page and section headings | Inter | Noto Sans SC |
| Body, navigation, buttons, labels and tables | Inter | Noto Sans SC |
| Code, formulas and existing monospace data | Existing mono stack | Existing system fallback |

- Self-host licensed WOFF2 files. Use variable weights, `font-display: swap` and Unicode-range subsets; browsers request only the needed Chinese subsets. Keep license and source information with the assets.
- System stacks remain available while fonts load. Do not depend on third-party font requests at runtime.
- Page titles use 28px/1.2 and weight 600; section headings use 24px/1.25 and card titles use 20px/1.3 at weights 600 and 500 respectively in the display stack. Body copy remains 16px; compact console controls and secondary text use 14px. Dense catalog rows remain 44px for scanability. Chinese does not use negative letter spacing.
- Headings use Inter and Noto Sans SC. Body, navigation, buttons, data, assistant Markdown and tool output stay in locally hosted Inter and Noto Sans SC. Quantgrove's logo and navigation labels retain their identity; numeric alignment remains tabular where currently used.
- Chinese headings use natural spacing, not Latin negative tracking. Allow Chinese/English content to wrap without clipping or squeezing controls.
- The landing retains English as the initial default and `?lang=zh` for Chinese, with synchronized document language, title and description. The shared localization module extends language selection across the landing, authentication and console surfaces.
- Chinese hero copy: **让想法，在证据中生长。** English hero copy: **Ideas grow through evidence.** Supporting copy explains the actual Alpha, backtesting and daily-observation product.

## Dark visual tokens

Use these semantic roles on the landing, authentication and console. Explicit canvas, text, accent and divider values follow the supplied Linear DesignMD. The source names but does not numerically define four raised surfaces, so these are chosen for readable product depth. Product status colors remain distinct and labeled in words for accessibility; Quantgrove's existing green mark remains its brand asset.

| Token | Value | Purpose |
| --- | --- | --- |
| Canvas | `#010102` | Continuous near-black page background |
| Surface 1 | `#111216` | Cards and sidebar |
| Surface 2 | `#191B21` | Grouped content and hover |
| Surface 3 | `#22242C` | Menus and overlays |
| Surface 4 | `#2B2E39` | Strongly raised controls |
| Text | `#F7F8F8` | Primary copy and headings |
| Secondary text | `#D0D6E0` | Explanations and metadata |
| Subtle text | `#8A8F98` | Tertiary metadata |
| Primary | `#5E6AD2` | Primary actions, links and focus |
| Primary hover | `#828FFF` | Interactive hover |
| Divider | `#23252A` | Hairline structure on dark surfaces |
| Control boundary | `#393C46` | Form boundaries with visible contrast |
| Success | `#58C878` | Positive feedback, also labeled in words |
| Warning | `#E0B95E` | Caution, also labeled in words |
| Error | `#F07D86` | Validation errors, also labeled in words |

- Use a 4px rhythm with 4/8/12/16px for controls and 24/32/48px to separate substantial console sections. Keep 40px desktop buttons and inputs, 48px ordinary rows and 44px dense catalog rows; coarse-pointer targets remain at least 44px.
- Use 8px corners for buttons and inputs, 12px for content cards, and hairline borders. Cards have no default shadow; use layering only where focus and overlap demand it.
- Hover and press feedback is brief (about 120–150ms). Ordinary open/close transitions are at most 300ms, with reduced-motion support.
- Data content is at most 1280px wide. Chat messages, header and composer share a centered 768px reading boundary. On desktop the empty composer is about 90px high, with the input above the model and send controls; it grows as text wraps. Settings content is at most 960px and authentication forms at most 440px. Desktop gutters are 32px, narrow gutters 24px and mobile gutters 16px.
- Use lines, typographic hierarchy and whitespace to separate information. Cards contain genuinely grouped controls or evidence; avoid card wrappers around every paragraph or metric.
- Define normal, hover, focus, disabled, pending, error and long-text states for controls and overlays. Fold secondary information instead of shrinking important text.
- Preserve landing copy, approved imagery and its three-stage preview while adapting typography, spacing and surfaces to the dark system. Clearly label the preview as a demonstration. No invented results, pricing, navigation or feature claims.
- Authentication retains its fields and interaction states. Keep errors, resend countdowns, invitation details, consent scopes and recovery actions legible.
- All product surfaces use `color-scheme: dark`. Do not introduce a parallel legacy theme or theme toggle.

## Console layout and behavior contract

- Preserve navigation order, capability gating, session history, new Chat, account menu, sidebar resizing/collapse, mobile drawer and keyboard/focus behavior.
- All workspace routes use the approved Research sidebar presentation from the shared stylesheet: dark surface, 64px brand row, consistent navigation inset and history spacing. Route changes must not alter this presentation. Chat messages and the composer retain their existing behavior. Session history is one Recent list in descending activity order without calendar groups; its header has a new Chat icon linking to `/chat`. Keep the primary New Chat row and per-session actions.
- The shared sidebar uses Linear-inspired dark surfaces and lavender accents with compact navigation spacing based on the approved sidebar reference: New Chat and workspace links share 40px rows, 8px vertical and 12px horizontal padding, 8px icon gaps, and the same hover and active treatment. Their outer inset is 4px. History text aligns with the navigation icons; section and history spacing use the 4px scale.
- Preserve the sidebar defaults of 240px expanded and 56px collapsed, and the existing resize bounds and persistence. Brand and main navigation remain above the independently scrolling history; management and account remain at the bottom.
- Research editing shares an outer shell for factor, framework and direct Python modes. Use a clear title, quiet mode switch, editor first, and a grouped configuration panel. At 840px of content width, factor editing uses a main editor and a 300px configuration column; strategy editing uses a 320px column at 960px of content width. Factor formulas start at 180px, framework formulas at 280px, and Python source editors at 480px. Field browsing is a temporary drawer. Keep run actions reachable without covering content.
- Run details lead with name, type, status and primary actions. Success leads with metrics and chart; running and failure lead with progress or reason. Frozen inputs and organization controls are secondary. Factor and strategy results retain their distinct evidence, holdings, events and input views.
- Runs, batches, Data, Daily Tracks, Chat, MCP and Operator share headers, controls, async states and surfaces while each module retains its current filters, permissions, actions, requests and transitions. A missing metric displays an em dash and any existing unavailable explanation remains accessible.
- Formula and Python CodeMirror editors use the dark surface theme, including selection, cursor, gutters, completion and diagnostics. Charts use legible, distinguishable semantic series colors; success and failure retain their own meanings. Markdown, A2UI, portals and Shadow DOM use scoped dark styling.
- Keep the approved Quantgrove mark and wordmark. In expanded and mobile sidebars, pair a 24px mark with a 20px sans-serif wordmark and an 8px gap. The collapsed rail keeps its expand control.

## Chinese/English interface localization

- Use one interface-language module for the landing, authentication and console, with `en` and `zh-CN`. Start in English when no explicit choice exists; remember the user's choice in the current browser. The landing's explicit language query takes precedence for that page. Cross-device preference synchronization is outside this increment.
- Put `English / 简体中文` in the existing account menu. Keep it reachable in expanded, collapsed and mobile navigation, including keyboard access. Changing language updates text in place without changing console URLs, remounting authenticated pages or refetching research data.
- Keep both languages' interface resources bundled and ready before display. Organize resources by product module using i18next/react-i18next. Check translation keys, interpolation parameters and current Catalog coverage during validation; missing translations must not silently produce a partially translated release.
- Translate application-owned navigation, controls, empty/loading/error states, dialogs, help, charts, editor assistance and accessible labels. Preserve user-authored names and notes, stored chat messages and model-authored A2UI content. Interface language does not alter Agent instructions or reply-language policy; replies continue to follow the conversation and the user's explicit requests.
- Use stable field IDs, builtin identifiers, industry codes, benchmark IDs and system-folder identities for translated display. Data and the Research Kernel remain authoritative for field/operator meaning, units, availability and calculation semantics. Display dictionaries cannot add allowed fields or redefine those facts. Field search includes both languages and formula identifiers while preserving selected values and filters.
- Keep translated text out of protocol values, business conditions, React keys and persistence. In particular, preserve `Untitled`, session activity timestamps and ordering, raw Research Purpose filter values, formula identifiers and system-folder stored names; translate their presentation only.
- Store error/status identities and parameters rather than already translated strings. Existing visible errors update when the language changes. Supplement necessary public error codes and Alpha Diagnostic details where the current UI lacks a structured reason, preserving specific causes, HTTP status, authorization and successful results. Do not parse English sentences to recover error identity or change business rules, persistence schemas or resource identities.
- Preserve CodeMirror and chart instances, editor selection/undo history, chart zoom, Chat drafts and active turns, Research form state, filters, open dialogs and focus. Use the libraries' supported in-place localization configuration rather than making locale a lifecycle identity.
- Centralize displayed numbers and timestamps while preserving precision, currency, signs and each value's time semantics. A Research Session date remains a date; changing language does not change timezone or the Research Calendar. Browser-owned date-picker chrome remains governed by the browser; application labels and accessibility text follow the interface language.
- Validate both languages in initial, pending, failure and completed states, including switching during active editing and streaming. Reuse the existing local fonts; verify the new workspace layout at desktop widths.

## Accessibility and interaction

- Product text and controls meet WCAG AA on their actual backgrounds: 4.5:1 for ordinary text and 3:1 for large text and necessary control indicators. Status also uses words or icons.
- Keep visible focus indicators, keyboard access, semantic links/buttons and text labels for status. Touch targets remain at least 44px in public/mobile surfaces.
- Respect `prefers-reduced-motion`. Use short, purposeful hover/focus transitions; no automatic decorative motion.
- Check desktop widths, expanded/collapsed sidebar, mixed scripts and long content. Font loading must not obscure content or controls.

## Implementation and acceptance

Reuse React/Vite, Phosphor, i18next, CodeMirror, Lightweight Charts and CopilotKit. The selected foundation is repository-owned **shadcn/ui + Base UI + Tailwind**, as recorded in [ADR-0251](docs/adr/0251-own-console-components-through-shadcn-base-ui.md). This specification records the confirmed target, not implementation completion. Do not add a page framework, global state store, form engine, table engine or runtime theme switch.

- Basic controls, tables, feedback and overlays come from `components/ui`; only that foundation imports Base UI. Pages compose shared layout and product components instead of restyling basic controls. Enforce this ownership in automated checks, with explicit boundaries for the preserved landing and specialized renderers.
- Centralize semantic shadcn tokens and font/base rules in the shared style entry. Use Tailwind composition and centrally defined component variants. Remove each module's legacy rules and superseded CSS Modules as it moves; do not accumulate override layers or parallel implementations.
- Keep the public landing independent of Tailwind Preflight. Update its scoped stylesheet for this visual direction and verify its actual copy, links and interaction in both languages at desktop widths.
- Omit global Tailwind Preflight in this existing application. Repository-owned base components normalize their own browser defaults; the landing retains its established CSS reset and layout.
- Business modules continue to own drafts, validation, requests and state transitions. Shared components own layout, interaction semantics and display. Shared metric groups preserve domain-specific units, precision and unavailable-value explanations.
- Use a shared shadcn date selection composition with keyboard/manual entry and localization, preserving ISO date values and existing validation. Lightweight feedback uses the official Base UI Toast; important errors and progress remain inline.
- Specialized CodeMirror, chart and A2UI surfaces use the same semantic tokens and shared outer controls while retaining their supported editing, rendering and protocol behavior.

Follow [AGENTS.md testing guidance](AGENTS.md#testing). Verify affected type checks and browser tests during each stage, and run the complete frontend build within the unchanged bundle budget at the end. Select broader test suites according to the delivery's authorized scope. Compare the landing at desktop widths in both languages to the baseline. Accept representative console flows in a browser served from this implementation worktree. Record verified and unverified boundaries separately.
