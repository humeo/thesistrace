---
version: alpha
name: Linear Dashboard
description: "A dense, dark product workbench built on Linear's near-black surface ladder, restrained lavender-blue accent, compact typography, hairline borders, and collapsible application sidebar."
sourceUrl: "https://linear.app"
catalogUrl: "https://www.designmd.co/d/linear.app"
blockUrl: "https://www.designmd.co/blocks/catalog/linear-dashboard"
pinnedAt: "2026-08-23"

colors:
  primary: "#5e6ad2"
  on-primary: "#ffffff"
  primary-hover: "#828fff"
  primary-focus: "#5e69d1"
  ink: "#f7f8f8"
  ink-muted: "#d0d6e0"
  ink-subtle: "#8a8f98"
  ink-tertiary: "#62666d"
  canvas: "#010102"
  surface-1: "#0f1011"
  surface-2: "#141516"
  surface-3: "#18191a"
  surface-4: "#191a1b"
  hairline: "#23252a"
  hairline-strong: "#34343a"
  hairline-tertiary: "#3e3e44"
  semantic-success: "#27a644"
  semantic-warning: "#c69026"
  semantic-danger: "#d14d41"
  semantic-overlay: "#000000"

typography:
  page-title:
    fontFamily: "Inter, SF Pro Display, -apple-system, BlinkMacSystemFont, system-ui, Segoe UI, sans-serif"
    fontSize: 28px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: -0.6px
  section-title:
    fontFamily: "Inter, SF Pro Display, -apple-system, BlinkMacSystemFont, system-ui, Segoe UI, sans-serif"
    fontSize: 20px
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: -0.3px
  body:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, system-ui, Segoe UI, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0
  body-small:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, system-ui, Segoe UI, sans-serif"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: 0
  label:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, system-ui, Segoe UI, sans-serif"
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: 0.2px
  button:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, system-ui, Segoe UI, sans-serif"
    fontSize: 13px
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: 0
  mono:
    fontFamily: "Geist Mono, JetBrains Mono, SFMono-Regular, Consolas, Liberation Mono, monospace"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: 0

spacing:
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
  xxl: 48px

radius:
  xs: 4px
  sm: 6px
  md: 8px
  lg: 12px
  pill: 9999px

motion:
  duration-fast: 120ms
  duration-base: 180ms
  duration-slow: 240ms
  easing: "cubic-bezier(0.2, 0, 0, 1)"

layout:
  content-max: 1440px
  sidebar-expanded: 224px
  sidebar-collapsed: 56px
  context-bar-height: 48px
  desktop-breakpoint: 1024px
  mobile-breakpoint: 768px
---

> Adapted from [DesignMD's Linear design analysis](https://www.designmd.co/d/linear.app) and [Linear Dashboard block](https://www.designmd.co/blocks/catalog/linear-dashboard). These are third-party design references, not an official Linear specification.

## Design Direction

**Linear Product Workbench（Linear 式产品工作台）**

深色、紧凑、数据优先、层级克制。使用近黑画布和逐级抬升的炭灰表面组织复杂信息；薰衣草蓝只用于主操作、焦点和少量链接强调。界面应像长期使用的研究工具，而不是营销网站、通用管理后台或指标大屏。

This direction replaces the previous OpenAI light theme. Do not keep a legacy light palette, compatibility theme, fallback styling, or parallel component path. A light mode may only be introduced by a future explicit product requirement.

## Product Principles

1. **The research object is the protagonist.** Formulae, datasets, runs, results, and daily observations receive the strongest hierarchy; application chrome stays quiet.
2. **Dense does not mean crowded.** Prefer compact rows, aligned columns, and clear grouping over oversized cards or excessive whitespace.
3. **One accent is enough.** Lavender-blue indicates action or focus. Status meaning uses semantic colors sparingly and always includes text or an icon.
4. **Hierarchy comes from surfaces and hairlines.** Do not use drop shadows, gradients, glass effects, or decorative glow.
5. **The shell scales with the domain.** Navigation must support the current four resources without turning every page into an unrelated dashboard.
6. **Behavior stays visible.** Loading, validation, saved state, execution state, retries, and failures must have explicit text—not color-only hints.

## Application Shell

### Desktop

- Use a persistent, collapsible left sidebar. It is 224px expanded and 56px collapsed.
- Place the ThesisTrace wordmark at the top of the sidebar. It may use the product sans stack; do not introduce a decorative display face.
- The primary resource order is fixed: **Data**, **Research**, **Research Runs**, **Daily Tracks**.
- Use icons plus labels in the expanded state and icons with accessible tooltips in the collapsed state.
- Keep a 48px context bar above page content for the current folder, canonical data state, data-through date, breadcrumbs, and page-level actions.
- Do not duplicate the same navigation or context controls in both the sidebar and context bar.
- The main canvas fills the remaining viewport. Apply a max width only to reading-heavy overview pages; editors, charts, and result tables may use the full available width.

### Resource Structure

- **Data** is a dataset status and coverage surface, not a generic analytics homepage.
- **Research** is a workbench. Research Folders form one nested level beneath Research; the editor remains the dominant surface.
- **Research Runs** is an execution history and result-inspection surface.
- **Daily Tracks** is a monitoring list and observation-detail surface.
- Do not add generic items such as Overview, Analytics, Team, Settings, Inbox, or Quick Create unless the product actually gains those domains.

### Research Workspace

- Default to the expanded sidebar on every resource so navigation behavior stays consistent. Users may collapse it manually when they need more editor or result width.
- Keep Draft identity, validation state, saved state, dataset context, and Run action in a compact workbench header.
- The formula editor uses `{colors.canvas}` or `{colors.surface-1}` with a single hairline boundary; it must not sit inside stacked ornamental cards.
- Run parameters open in a focused panel or drawer with a clear title, close action, validation summary, and one primary Run action.
- Preserve the one-level Folder model. Do not imply arbitrary project trees.

### Mobile and Narrow Screens

- Below 1024px, collapse the sidebar by default.
- Below 768px, replace it with an off-canvas navigation drawer; do not leave a 56px rail consuming mobile width.
- Context-bar metadata may wrap into a second row, but the page title and primary action remain visible.
- Dense data rows may switch to labeled stacked rows. Preserve every field and its meaning; do not hide critical provenance.

## Color and Surface Rules

### Surface Ladder

| Level | Token | Use |
|---|---|---|
| 0 | `{colors.canvas}` | App background, editor canvas, uninterrupted reading areas |
| 1 | `{colors.surface-1}` | Sidebar, context bar, cards, drawers |
| 2 | `{colors.surface-2}` | Selected rows, hover states, nested panels |
| 3 | `{colors.surface-3}` | Menus, popovers, elevated controls |
| 4 | `{colors.surface-4}` | Rare nested emphasis; never a default page background |

- Separate adjacent surfaces with 1px `{colors.hairline}` borders.
- Use `{colors.hairline-strong}` for active boundaries and `{colors.hairline-tertiary}` only inside elevated overlays.
- Avoid shadows. A modal may use `{colors.semantic-overlay}` as its scrim.
- Do not use true black `#000000` as the default canvas; reserve it for overlays.

### Accent and Semantics

- `{colors.primary}` is reserved for the primary action, focus ring, active navigation indicator, and intentional links.
- Hover may move to `{colors.primary-hover}`; pressed or focused emphasis may use `{colors.primary-focus}`.
- Success, warning, and danger colors are reserved for actual state. Never use them as decoration or category branding.
- A selected navigation row primarily uses a surface lift and stronger text. Do not fill the whole sidebar with lavender.

## Typography

- Use the documented system fallback stack. Linear's proprietary fonts are not a project dependency.
- Product pages do not use the 56–80px marketing display scale. Page titles are 28px; section titles are 20px.
- Default interface text is 14px. Use 13px for dense metadata and 12px for labels, timestamps, and compact status text.
- Use weight 600 sparingly for page titles and decisive values. Most interface text stays at 400 or 500.
- Use negative letter spacing only on titles. Body and table text remain neutral.
- Use the mono stack for formulae, IDs, dates, numeric metrics, logs, and machine-authored provenance—not for ordinary navigation.

## Components

### Navigation

- Sidebar rows are 36–40px high on pointer devices and at least 44px on touch devices.
- Active rows use `{colors.surface-2}`, `{colors.ink}`, and a restrained primary indicator.
- Group labels use `{typography.label}` and `{colors.ink-subtle}`.
- Collapsing the sidebar changes presentation, not the available destinations or current selection.

### Buttons

- Primary buttons: `{colors.primary}` background, white text, 8px radius, 8px × 14px padding.
- Secondary buttons: `{colors.surface-2}` background, `{colors.ink}` text, 1px hairline border.
- Tertiary buttons: transparent background and muted text; hover lifts to `{colors.surface-2}`.
- Destructive actions use danger styling only at the decision point.
- Do not use pill-shaped primary CTAs.

### Inputs and Selectors

- Inputs use `{colors.surface-1}`, `{colors.ink}`, an 8px radius, and a 1px `{colors.hairline-strong}` border.
- Focus uses a visible 2px `{colors.primary-focus}` outline with offset; hover alone is never the only affordance.
- Labels remain visible. Placeholder text does not replace a label.
- Validation messages sit next to the affected control and remain after focus changes.

### Data Lists and Tables

- Prefer aligned list rows or tables over card grids for Research Runs and Daily Tracks.
- Default row height is 44–52px. Use hairline separators and surface lift on hover/selection.
- Keep the primary identifier or title leftmost, followed by status, dates, research kind, and provenance.
- Numeric columns align right and use tabular or mono figures.
- Row click targets and inline actions must be distinguishable; avoid hidden hover-only actions for essential tasks.
- Empty, loading, error, and partial-result states occupy the same structural region as the eventual data.

### Metrics and Status

- Use compact metric strips or small surface-1 panels. Avoid oversized KPI cards.
- A metric includes a label, value, unit or time window where relevant, and provenance when ambiguity is possible.
- Status badges may use a pill radius because they are labels, not actions.
- Status always includes text. Never encode `active`, `blocked`, `failed`, or `complete` by color alone.

### Charts and Results

- Charts sit directly on the page or on a single surface-1 panel; avoid nesting a chart inside multiple cards.
- Use the lavender accent for the primary series and neutral grays for comparison/reference series.
- Semantic red or green may communicate loss/gain only when accompanied by labels and accessible descriptions.
- Tooltips use `{colors.surface-3}`, a strong hairline border, and mono/tabular figures.

### Drawers, Dialogs, and Menus

- Drawers and dialogs use `{colors.surface-1}` over a black scrim. Menus use `{colors.surface-3}`.
- Every overlay has a visible title, accessible close path, focus containment, Escape behavior, and focus restoration.
- Use dialogs for short decisions and drawers/panels for parameter-heavy workflows.

## Page Mapping

### Data

- Lead with dataset identity and readiness, then coverage ranges, freshness, and reconciliation.
- Present market and financial coverage as aligned sections rather than unrelated cards.
- Keep explanations secondary but visible; provenance and missing-value semantics are never hidden behind decoration.

### Research

- Prioritize editor height and width.
- Keep Run available without making every secondary control equally prominent.
- Validation, Draft persistence, and selected dataset context stay visible while editing.

### Research Runs

- The list is dense and scannable. Result detail promotes the performance chart, key metrics, execution timing, and provenance in that order.
- Tabs or segmented controls are appropriate only when the content is genuinely exclusive, not to conceal a long page.

### Daily Tracks

- The list emphasizes current status, origin session, strategy session, seed ResearchRun, and latest observation.
- Detail pages distinguish immutable lineage from daily mutable observations.

## Accessibility

- Normal text must meet WCAG AA contrast. `{colors.ink-subtle}` is for secondary metadata, not long-form body text.
- All focusable controls receive the 2px primary focus ring.
- Touch targets are at least 44 × 44px; compact pointer-only controls may be 36px high when their touch presentation expands.
- Sidebar collapse, drawers, menus, dialogs, tabs, tables, and editor controls must be fully keyboard operable.
- Icons require accessible names when they stand alone.
- Motion respects `prefers-reduced-motion`; state changes may not depend on animation.

## Motion

- Use 120ms for hover/focus transitions, 180ms for menus and small state changes, and 240ms for sidebar or drawer movement.
- Motion communicates continuity; it never delays a result or masks loading.
- Avoid bounce, spring overshoot, parallax, animated gradients, and decorative ambient motion.

## Do

- Use the near-black canvas as the anchor surface.
- Let tables, editors, charts, and provenance carry the visual interest.
- Use one surface step at a time and hairlines to clarify ownership.
- Keep navigation compact and predictable.
- Make the Research workspace feel purpose-built rather than assembled from generic cards.
- Preserve full information and actions when the sidebar collapses or the viewport narrows.

## Don't

- Don't preserve or silently fall back to the previous OpenAI light theme.
- Don't copy Linear's issue-tracker vocabulary, sample content, team switcher, or sprint cards into ThesisTrace.
- Don't turn every page into a KPI dashboard.
- Don't introduce gradients, glass, glow, thick shadows, or multiple bright accents.
- Don't use marketing-scale typography inside the product.
- Don't wrap every section in a rounded card.
- Don't hide important state or provenance behind hover, color, or icon-only controls.

## Implementation Order

1. Replace the application shell and tokens as one coherent hard cut.
2. Establish shared navigation, buttons, inputs, overlays, status, rows, and focus behavior.
3. Adapt Data and the list pages to the new density and surface hierarchy.
4. Adapt the Research workspace without sacrificing editor space.
5. Adapt result detail charts, metrics, execution timing, and provenance.
6. Verify desktop, collapsed-sidebar, tablet, and mobile behavior in a real browser.
7. Run accessibility checks for contrast, keyboard navigation, focus, reduced motion, and touch targets.
