---
version: 4
name: Quantgrove
status: implementing
referenceImage: "docs/design/quantgrove-brand-reference.png"
pinnedAt: "2026-09-28"
referenceDesign: "docs/design/perplexity-designmd-reference.md"
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
  brand: "Source Serif 4, Noto Serif SC, Georgia, Songti SC, STSong, serif"
  body: "Inter, Noto Sans SC, -apple-system, BlinkMacSystemFont, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif"
  mono: "Geist Mono, JetBrains Mono, SFMono-Regular, Consolas, Liberation Mono, monospace"
---

# Quantgrove design

The [Quantgrove brand board](docs/design/quantgrove-brand-reference.png) defines the product identity and approved assets. The [user-supplied Perplexity DesignMD reference](docs/design/perplexity-designmd-reference.md) defines this redesign's warm neutral interface direction. Its alpha measurements describe a reference product, not a copy of Quantgrove's workflows or an instruction to use its proprietary font. The brand board's sample navigation, people, models, research counts and returns are illustrative, not product requirements or claims.

## Approved scope

The Research editor and its sidebar established the first implementation slice. The approved next slice covers Data, Research Runs and batches, result details, Daily Tracks, MCP, and Operator pages. Chat and its conversation list retain their current layout. The target rules below describe the shared system; `status: implementing` records that the migration is in progress.

The Research preview uses weight 500 for its 24/32 page title, with regular-weight body copy, to soften the Chinese heading. Its research type and strategy authoring choices stay visible together in a quiet, grouped control area above the editor.

The remaining console pages follow the approved `console-redesign-v1` Data, Runs, Daily, MCP and Admin references. Their opt-in `console-workspace` surface uses the warm tokens without changing Chat, New Chat or history/sidebar styling. Page titles use 36/44; major section titles use 24–28/32–36. Desktop catalog rows use 44px and research/directory rows use 80px, with 16px tabular values and subtle dividers. Data pairs catalog controls/list with a definition pane; Daily pairs a 280px selection pane with observation metrics and a 216px plot. Explanations use accessible hover/click annotations or disclosure rows; errors, degraded coverage, dates and units stay visible. Reference dimensions guide hierarchy and spacing, never fabricated data or changes to the preserved 224px sidebar.

The result detail follows the approved `docs/design/console-redesign-v1-result.png` composition. Its title uses 36/44 sans-serif with inline type/status badges; dates and the folder share the metadata line. The six-metric band uses 16px labels and 24–28/36 sans-serif tabular values, with inset dividers. Tabs lead directly into this band. Keep 12px between the metric band, approximately 334px desktop return chart, three-column ending-state panel and shared-border disclosure rows. The strategy curve is near-black and the benchmark is taupe and dashed. Help opens on hover, focus or click. Draft folder selection opens from the header and deletion stays in the secondary menu. The sidebar and Chat history retain their existing dimensions; reference values and curves remain illustrative.

**Warm, reading-first research（温和、克制、以阅读和证据为中心的研究空间）**

| Surface | Required treatment |
| --- | --- |
| Public landing | Apply the warm neutral typography, controls and surface system. Preserve its actual copy, approved botanical asset, interactive preview, anchors, destinations and English/Chinese switching. |
| Login, invitation, access and MCP consent states | Use the warm neutral system and shared controls while preserving existing fields, validation and authentication behavior. |
| Console, including Chat, Data, Research, Research Runs, batches, Daily Tracks, MCP and Operator | Use one reading-first workspace while preserving capabilities, navigation, URLs, resource identities and service contracts. |
| Email, browser title, metadata, accessible names and favicon | Use Quantgrove consistently. Email uses its own email-safe markup and system fonts. |

The public landing is the brand baseline. Its decorative layout and mock data must not replace production console pages. Shared changes must be checked against its current desktop rendering.

## Brand assets and naming

- The visible product name is **Quantgrove** in both languages. Do not introduce a Chinese transliteration or retain the old Chinese product name.
- Use the folded-leaf/open-book mark, serif wordmark, inverse mark for dark surfaces, and white mark on a forest-green app icon. Master assets are SVG; email and favicon exports include PNG.
- Preserve proportions and check the mark at 16, 24 and 32px. Use real assets without blend modes, stretched dimensions or the whole reference board as a background.
- Reuse the Web brand component for marks and wordmarks. A linked brand has an accessible name; its decorative mark has empty alternative text.
- Update all public QuantTrace/ThesisTrace strings, including authentication-provider display name, email subjects and body, access states, MCP instructions and consent.
- Repository/package names, environment variables, routes, database identifiers, Cookie prefixes and saved MCP client aliases are technical contracts, not display branding. Keep them unchanged. Instructions must still reference the actual configured client alias when selecting or logging into it.
- Preserve the legacy image resource referenced by already-delivered email; new surfaces use the Quantgrove assets.

## Typography and Chinese

| Role | Latin | Chinese |
| --- | --- | --- |
| Brand wordmark | Source Serif 4 | Noto Serif SC |
| Public and answer headings | Inter | Noto Sans SC |
| Console page and section headings | Inter | Noto Sans SC |
| Body, navigation, buttons, labels, tables and section headings | Inter | Noto Sans SC |
| Code, formulas and existing monospace data | Existing mono stack | Existing system fallback |

- Self-host licensed WOFF2 files. Use variable weights, `font-display: swap` and Unicode-range subsets; browsers request only the needed Chinese subsets. Keep license and source information with the assets.
- System stacks remain available while fonts load. Do not depend on third-party font requests at runtime.
- Page and answer headings use 24/32 and weight 600. Assistant answer prose uses 20/30 and weight 400 within the reading column; ordinary product prose uses 16/24. Dense forms, tables and controls use 14/22, and supporting text uses at least 12/18. The reference measures 24px for its sampled body text; applying that size to every data cell would obscure research evidence. Chinese does not use negative letter spacing.
- Serif styling is reserved for the Quantgrove wordmark. Public headings, workspace headings, assistant Markdown, tool output, charts and data cards use the same locally hosted sans-serif family. Do not fetch or impersonate the unavailable `pplxSans` font; numeric alignment remains tabular where currently used.
- Chinese headings use natural spacing, not Latin negative tracking. Allow Chinese/English content to wrap without clipping or squeezing controls.
- The landing retains English as the initial default and `?lang=zh` for Chinese, with synchronized document language, title and description. The shared localization module extends language selection across the landing, authentication and console surfaces.
- Chinese hero copy: **让想法，在证据中生长。** English hero copy: **Ideas grow through evidence.** Supporting copy explains the actual Alpha, backtesting and daily-observation product.

## Warm neutral visual tokens

Use these semantic roles on the landing, authentication and console. The values follow the supplied DesignMD where usable; derived text and control colors preserve contrast on real product surfaces. Quantgrove's existing green mark remains its brand asset, while interactive emphasis uses near-black.

| Token | Value | Purpose |
| --- | --- | --- |
| Canvas | `#FCFCF9` | Continuous warm page background |
| Surface | `#FDFBFA` | Cards, forms and reading surfaces |
| Raised surface | `#FFFFFF` | Menus and focused overlays |
| Surface soft | `#F3F2EE` | Selected rows and quiet grouping |
| Text | `#27251E` | Primary copy and headings |
| Secondary text | `#5B5952` | Explanations and metadata |
| Primary | `#27251E` | Primary actions, citations and focus |
| Primary hover | `#403D35` | Interactive hover |
| Divider | `#DEDDD6` | Subtle structure on warm surfaces |
| Control boundary | `#8A8880` | Form boundaries with visible contrast |
| Success | `#276749` | Positive feedback, also labeled in words |
| Warning | `#80551E` | Caution, also labeled in words |
| Error | `#A33A32` | Validation errors, also labeled in words |

- Use a 4px rhythm with 4/8/12/16px for controls and 24/32/48px to separate substantial sections. Keep 36px desktop buttons, 40px inputs, 48px ordinary rows and 40px dense catalog rows; mobile touch targets remain at least 44px.
- Use 6px small control corners, 12px medium panels and 16px large reading surfaces. Primary calls to action may be pill shaped. The only standard elevation is `0 1px 2px rgb(0 0 0 / 8%)`; use stronger layering only where focus and overlap demand it.
- Hover and press feedback completes in about 75ms. Ordinary open/close transitions are at most 300ms, with reduced-motion support. The reference's 1200ms tier is excluded from routine research operations.
- Data content is at most 1440px wide. Chat messages and the composer share a centered 720px reading boundary; settings content is at most 960px and authentication forms at most 440px. Desktop gutters are 32px, narrow gutters 24px and mobile gutters 16px.
- Use lines, typographic hierarchy and whitespace to separate information. Cards contain genuinely grouped controls or evidence; avoid card wrappers around every paragraph or metric.
- Define normal, hover, focus, disabled, pending, error and long-text states for controls and overlays. Fold secondary information instead of shrinking important text.
- Preserve landing copy, approved imagery and its three-stage preview while adapting typography, spacing and surfaces to the warm neutral system. Clearly label the preview as a demonstration. No invented results, pricing, navigation or feature claims.
- Authentication retains its fields and interaction states. Keep errors, resend countdowns, invitation details, consent scopes and recovery actions legible.
- All product surfaces use `color-scheme: light`. Do not introduce a parallel legacy theme or theme toggle.

## Console layout and behavior contract

- Preserve navigation order, capability gating, session history, new Chat, account menu, sidebar resizing/collapse, mobile drawer and keyboard/focus behavior.
- Preserve the sidebar defaults of 224px expanded and 56px collapsed, and the existing resize bounds and persistence. Brand and main navigation remain above the independently scrolling history; management and account remain at the bottom.
- Research editing shares an outer shell for factor, framework and direct Python modes. Use a clear title, quiet mode switch, editor first, and a grouped configuration panel. At 840px of content width, factor editing uses a main editor and a 300px configuration column; strategy editing uses a 320px column at 960px of content width. Factor formulas start at 180px, framework formulas at 280px, and Python source editors at 480px. Field browsing is a temporary drawer. Keep run actions reachable without covering content.
- Run details lead with name, type, status and primary actions. Success leads with metrics and chart; running and failure lead with progress or reason. Frozen inputs and organization controls are secondary. Factor and strategy results retain their distinct evidence, holdings, events and input views.
- Runs, batches, Data, Daily Tracks, Chat, MCP and Operator share headers, controls, async states and surfaces while each module retains its current filters, permissions, actions, requests and transitions. A missing metric displays an em dash and any existing unavailable explanation remains accessible.
- Formula and Python CodeMirror editors use the warm neutral light theme, including selection, cursor, gutters, completion and diagnostics. Charts use legible, distinguishable semantic series colors; success and failure retain their own meanings. Markdown, A2UI, portals and Shadow DOM use scoped light styling.
- Keep the approved Quantgrove mark and wordmark. In expanded and mobile sidebars, pair a 24px mark with a 20px serif wordmark and an 8px gap. The collapsed rail keeps its expand control.

## Chinese/English interface localization

- Use one interface-language module for the landing, authentication and console, with `en` and `zh-CN`. Start in English when no explicit choice exists; remember the user's choice in the current browser. The landing's explicit language query takes precedence for that page. Cross-device preference synchronization is outside this increment.
- Put `English / 简体中文` in the existing account menu. Keep it reachable in expanded, collapsed and mobile navigation, including keyboard access. Changing language updates text in place without changing console URLs, remounting authenticated pages or refetching research data.
- Keep both languages' interface resources bundled and ready before display. Organize resources by product module using i18next/react-i18next. Check translation keys, interpolation parameters and current Catalog coverage during validation; missing translations must not silently produce a partially translated release.
- Translate application-owned navigation, controls, empty/loading/error states, dialogs, help, charts, editor assistance and accessible labels. Preserve user-authored names and notes, stored chat messages and model-authored A2UI content. Interface language does not alter Agent instructions or reply-language policy; replies continue to follow the conversation and the user's explicit requests.
- Use stable field IDs, builtin identifiers, industry codes, benchmark IDs and system-folder identities for translated display. Data and the Research Kernel remain authoritative for field/operator meaning, units, availability and calculation semantics. Display dictionaries cannot add allowed fields or redefine those facts. Field search includes both languages and formula identifiers while preserving selected values and filters.
- Keep translated text out of protocol values, business conditions, React keys and persistence. In particular, preserve `Untitled`, session-recency identities, raw Research Purpose filter values, formula identifiers and system-folder stored names; translate their presentation only.
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
