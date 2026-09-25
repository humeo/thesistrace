---
version: 3
name: Quantgrove
status: implemented
referenceImage: "docs/design/quantgrove-brand-reference.png"
pinnedAt: "2026-09-22"
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
  display: "Source Serif 4, Noto Serif SC, Georgia, Songti SC, STSong, serif"
  body: "Inter, Noto Sans SC, -apple-system, BlinkMacSystemFont, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif"
  mono: "Geist Mono, JetBrains Mono, SFMono-Regular, Consolas, Liberation Mono, monospace"
---

# Quantgrove design

The [user-provided brand board](docs/design/quantgrove-brand-reference.png) defines the brand direction. Its five colors are reference values; the interface tokens below are our implementation choices. The board's sample navigation, people, models, research counts and returns are illustrative, not product requirements or claims.

## Approved scope

**Calm, evidence-led research（安静、清晰、以证据为中心的研究空间）**

| Surface | Required treatment |
| --- | --- |
| Public landing | Keep its current layout, copy, botanical and stone assets, interactive preview, and English/Chinese switching unchanged. |
| Login, invitation, access and MCP consent states | Use the Classic light palette and shared controls while preserving existing fields, validation and authentication behavior. |
| Console, including Chat, Data, Research, Research Runs, batches, Daily Tracks, MCP and Operator | Rebuild as one Classic light research workspace while preserving capabilities, navigation, URLs, resource identities and service contracts. |
| Email, browser title, metadata, accessible names and favicon | Use Quantgrove consistently. Email uses its own email-safe markup and system fonts. |

The public landing is the brand baseline. Its decorative layout and mock data must not replace production console pages. Shared changes must be checked against its current desktop and mobile rendering.

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
| Brand and public editorial headings | Source Serif 4 | Noto Serif SC |
| Console page and section headings | Inter | Noto Sans SC |
| Body, navigation, buttons, labels, tables and section headings | Inter | Noto Sans SC |
| Code, formulas and existing monospace data | Existing mono stack | Existing system fallback |

- Self-host licensed WOFF2 files. Use variable weights, `font-display: swap` and Unicode-range subsets; browsers request only the needed Chinese subsets. Keep license and source information with the assets.
- System stacks remain available while fonts load. Do not depend on third-party font requests at runtime.
- Console page headings use 24/32, section headings 16/24, body and controls 14/22, supporting text 12/18, and chat body 16/26. Chinese does not use negative letter spacing.
- Serif styling applies to the brand and public editorial headings. Workspace headings, assistant Markdown, tool output, charts and data cards use the workspace sans-serif family; numeric alignment remains tabular where currently used.
- Chinese headings use natural spacing, not Latin negative tracking. Allow Chinese/English content to wrap without clipping or squeezing controls.
- The landing retains English as the initial default and `?lang=zh` for Chinese, with synchronized document language, title and description. The shared localization module extends language selection across the landing, authentication and console surfaces.
- Chinese hero copy: **让想法，在证据中生长。** English hero copy: **Ideas grow through evidence.** Supporting copy explains the actual Alpha, backtesting and daily-observation product.

## Classic light visual tokens

The console and authentication use these tokens. Keep the landing's existing scoped styling unchanged.

| Token | Value | Purpose |
| --- | --- | --- |
| Canvas | `#FAF9F4` | Ivory background |
| Surface | `#FFFFFF` | Forms and research preview |
| Surface soft | `#F1F3EC` | Subtle emphasis |
| Text | `#1F1F1F` | Primary content |
| Muted text | `#50594F` | Supporting content |
| Secondary text | `#626B61` | Metadata |
| Primary | `#0F3D2E` | Actions and emphasis |
| Primary hover | `#164F3D` | Hover and active actions |
| Divider | `#E2E4DA` | Decorative separators |
| Control boundary | `#858D7E` | Inputs and controls; at least 3:1 on the soft surface |
| Success | `#276749` | Positive feedback |
| Error | `#A33A32` | Validation errors |

- Workspace spacing uses 4/8/12/16/24/32/48px. Desktop buttons are 36px high, inputs 40px, ordinary table rows 48px and dense catalog rows 40px; touch actions are at least 44px high. Controls, panels and dialogs use 6/8/12px radii. Shadows are primarily for floating layers.
- Data content is at most 1440px wide, Chat message and input columns share an 800px outer boundary, settings content is at most 960px, and authentication forms are at most 440px. Desktop gutters are 32px, narrow gutters 24px and mobile gutters 16px.
- Define normal, hover, focus, disabled, pending, error and long-text states for controls and overlays. Fold secondary information instead of shrinking important text.
- The landing hero is left-aligned text with a botanical/stone image on the right, stacked on mobile. Use the approved photograph as decoration, with explicit dimensions and empty alt text.
- Maintain the existing page anchors, three-stage research interaction, keyboard tab behavior, login and community destinations. Clearly label the research preview as a demonstration. No invented results, pricing, navigation or feature claims.
- Authentication retains its fields and interaction states. Keep errors, resend countdowns, invitation details, consent scopes and recovery actions legible.
- All product surfaces use `color-scheme: light`. Do not introduce a parallel legacy theme or theme toggle.

## Console layout and behavior contract

- Preserve navigation order, capability gating, session history, new Chat, account menu, sidebar resizing/collapse, mobile drawer and keyboard/focus behavior.
- Preserve the sidebar defaults of 224px expanded and 56px collapsed, and the existing resize bounds and persistence. Brand and main navigation remain above the independently scrolling history; management and account remain at the bottom.
- Research editing shares an outer shell for factor, framework and direct Python modes. At 960px of content width, use a main editor and a 320px configuration column; stack them below that width. Formula and Python source editors start at 280px and 480px. Field browsing is a temporary drawer. Keep run actions reachable without covering content.
- Run details lead with name, type, status and primary actions. Success leads with metrics and chart; running and failure lead with progress or reason. Frozen inputs and organization controls are secondary. Factor and strategy results retain their distinct evidence, holdings, events and input views.
- Runs, batches, Data, Daily Tracks, Chat, MCP and Operator share headers, controls, async states and surfaces while each module retains its current filters, permissions, actions, requests and transitions. A missing metric displays an em dash and any existing unavailable explanation remains accessible.
- Formula and Python CodeMirror editors use a complete light theme, including selection, cursor, gutters, completion and diagnostics. Charts read the shared semantic palette. Markdown, A2UI, portals and Shadow DOM use scoped light styling.
- Use the light logo on light surfaces. In expanded and mobile sidebars, pair a 24px mark with a 20px serif wordmark and an 8px gap. The collapsed rail keeps its expand control.

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
- Validate both languages in initial, pending, failure and completed states, including switching during active editing and streaming. Reuse the existing local fonts; verify the new workspace layout at 320px, 390px, 768px and desktop widths.

## Accessibility and interaction

- Product text and controls meet WCAG AA on their actual backgrounds: 4.5:1 for ordinary text and 3:1 for large text and necessary control indicators. Status also uses words or icons.
- Keep visible focus indicators, keyboard access, semantic links/buttons and text labels for status. Touch targets remain at least 44px in public/mobile surfaces.
- Respect `prefers-reduced-motion`. Use short, purposeful hover/focus transitions; no automatic decorative motion.
- Check 320px and 390px mobile widths, desktop, expanded/collapsed sidebar, mixed scripts and long content. Font loading must not obscure content or controls.

## Implementation and acceptance

Reuse React/Vite, Phosphor, i18next, CodeMirror, Lightweight Charts and CopilotKit. The selected foundation is repository-owned **shadcn/ui + Base UI + Tailwind**, as recorded in [ADR-0251](docs/adr/0251-own-console-components-through-shadcn-base-ui.md). This specification records the confirmed target, not implementation completion. Do not add a page framework, global state store, form engine, table engine or runtime theme switch.

- Basic controls, tables, feedback and overlays come from `components/ui`; only that foundation imports Base UI. Pages compose shared layout and product components instead of restyling basic controls. Enforce this ownership in automated checks, with explicit boundaries for the preserved landing and specialized renderers.
- Centralize semantic shadcn tokens and font/base rules in the shared style entry. Use Tailwind composition and centrally defined component variants. Remove each module's legacy rules and superseded CSS Modules as it moves; do not accumulate override layers or parallel implementations.
- Preserve the public landing against Tailwind base-style changes, including Preflight. Keep its scoped stylesheet and compare both languages on desktop/mobile.
- Omit global Tailwind Preflight in this existing application. Repository-owned base components normalize their own browser defaults; the landing retains its established CSS reset and layout.
- Business modules continue to own drafts, validation, requests and state transitions. Shared components own layout, interaction semantics and display. Shared metric groups preserve domain-specific units, precision and unavailable-value explanations.
- Use a shared shadcn date selection composition with keyboard/manual entry and localization, preserving ISO date values and existing validation. Lightweight feedback uses the official Base UI Toast; important errors and progress remain inline.
- Specialized CodeMirror, chart and A2UI surfaces use the same semantic tokens and shared outer controls while retaining their supported editing, rendering and protocol behavior.

Follow [AGENTS.md testing guidance](AGENTS.md#testing). Verify affected type checks and browser tests during each stage, and run the complete frontend build within the unchanged bundle budget at the end. Select broader test suites according to the delivery's authorized scope. Compare the landing at desktop and mobile widths in both languages to the baseline. Accept representative console flows in a browser served from this implementation worktree. Record verified and unverified boundaries separately.
