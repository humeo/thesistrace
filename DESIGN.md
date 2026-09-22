---
version: 2
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
| Public landing | Ivory canvas, forest-green actions, editorial serif headings, botanical/stone photograph; preserve real product content, research preview and English/Chinese switching. |
| Login, invitation, password recovery and access states | Light brand treatment; preserve form structure, field order, validation, authentication behavior and recovery paths. |
| Console, including Chat, Data, Research, Research Runs, batches, Daily Tracks, MCP and Operator | **Fonts, logo and visible product name only.** Preserve the current dark palette, layout, component styling, navigation and interactions. |
| Email, browser title, metadata, accessible names and favicon | Use Quantgrove consistently. Email uses its own email-safe markup and system fonts. |

The public landing prototype is a visual reference. Its console layouts and mock data must not replace production console pages.

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
| Brand and page main headings | Source Serif 4 | Noto Serif SC |
| Body, navigation, buttons, labels, tables and section headings | Inter | Noto Sans SC |
| Code, formulas and existing monospace data | Existing mono stack | Existing system fallback |

- Self-host licensed WOFF2 files. Use variable weights, `font-display: swap` and Unicode-range subsets; browsers request only the needed Chinese subsets. Keep license and source information with the assets.
- System stacks remain available while fonts load. Do not depend on third-party font requests at runtime.
- In console content and controls, change font families only. Keep existing font sizes, weights, line heights, letter spacing, component dimensions and responsive rules. The sidebar brand lockup has its own optical sizing below.
- Serif styling applies to page main headings, not every heading inside assistant Markdown, tool output, charts or data cards. Body content stays sans-serif; numeric alignment remains tabular where currently used.
- Chinese headings use natural spacing, not Latin negative tracking. Allow Chinese/English content to wrap without clipping or squeezing controls.
- The landing retains its existing language contract: English by default, `?lang=zh` for Chinese, synchronized URL, document language, title and description. This change does not add console or authentication-page translation/settings.
- Chinese hero copy: **让想法，在证据中生长。** English hero copy: **Ideas grow through evidence.** Supporting copy explains the actual Alpha, backtesting and daily-observation product.

## Public-page visual tokens

These tokens apply only inside the landing and authentication surfaces. They do not replace the console root palette.

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
| Control boundary | `#878F80` | Inputs and controls |
| Success | `#276749` | Positive feedback |
| Error | `#A33A32` | Validation errors |

- Public spacing uses a 4/8px rhythm with generous reading space. Buttons and fields use 6–8px radii; preview panels use up to 12px. Avoid heavy shadows, gradients, glass or decorative metric cards.
- The landing hero is left-aligned text with a botanical/stone image on the right, stacked on mobile. Use the approved photograph as decoration, with explicit dimensions and empty alt text.
- Maintain the existing page anchors, three-stage research interaction, keyboard tab behavior, login and community destinations. Clearly label the research preview as a demonstration. No invented results, pricing, navigation or feature claims.
- Authentication retains its current DOM/form structure and interaction states. Apply a scoped light palette and serif main headings. Keep errors, resend countdowns and recovery actions legible.
- The public surface uses `color-scheme: light`, including its page canvas. Controls inside the console remain dark. Never switch the global root variables to the public palette.

## Console preservation contract

- Preserve navigation order, capability gating, session history, new Chat, account menu, sidebar resizing/collapse, mobile drawer and keyboard/focus behavior.
- Preserve the sidebar defaults: 224px expanded, 56px collapsed, 48px header; existing resize bounds and persistence remain authoritative.
- Preserve all current page layouts, content widths, spacing, form structure, table density, dialogs, popovers and responsive breakpoints.
- Preserve chart colors/grid, CodeMirror dark syntax and selection theme, button/status colors, A2UI and Markdown presentation. Font-family updates do not authorize a component restyle.
- Use the inverse logo on dark surfaces. In the expanded sidebar and mobile drawer, pair a 24px mark with a 20px serif wordmark (24px line height, 600 weight, -0.02em tracking) and an 8px gap. Preserve the brand link's 30px minimum height and the existing header geometry. The collapsed desktop rail retains its existing expand control and hides the full brand link.
- Any broader console redesign or localization requires a separate product decision.

## Accessibility and interaction

- Public text and controls meet WCAG AA on their actual backgrounds. Reference-board microcopy is not a reason to reproduce low contrast.
- Keep visible focus indicators, keyboard access, semantic links/buttons and text labels for status. Touch targets remain at least 44px in public/mobile surfaces.
- Respect `prefers-reduced-motion`. Use short, purposeful hover/focus transitions; no automatic decorative motion.
- Check 320px and 390px mobile widths, desktop, expanded/collapsed sidebar, mixed scripts and long content. Font loading must not obscure content or controls.

## Implementation and acceptance

Reuse React/Vite, native CSS, Phosphor icons, CodeMirror and Lightweight Charts. No new component framework, runtime theme switch or localization framework is required. Keep public styles scoped; change console rules only for font families and branding.

Implementation order: this specification → brand and font assets → landing/authentication → console branding → verification. Preserve unrelated working-tree changes.

Follow [AGENTS.md testing guidance](AGENTS.md#testing). Verify affected type checks/builds, existing landing/sidebar/composer/login browser scenarios and relevant authentication/email tests. Compare real desktop/mobile rendering with the console baseline. Check local font/image loading, both landing languages, metadata, old public names and existing MCP configuration instructions. Record actual results and unverified boundaries; do not claim deployment or full backend qualification from visual checks.
