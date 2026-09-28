<design-context>
---
version: alpha
name: Perplexity
description: "Perplexity is a free AI-powered answer engine that provides accurate, trusted, and real-time answers to any question."
sourceUrl: "https://perplexity.ai"

colors:
  primary: "#27251e"
  on-primary: "#ffffff"
  background: "#fcfcf9"
  surface: "#fdfbfa"
  text: "#000000"
  text-muted: "#27251e"

typography:
  display:
    fontFamily: "pplxSans, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, Noto Sans, Hiragino Sans, Yu Gothic, Meiryo, PingFang SC, Microsoft YaHei, PingFang TC, Microsoft JhengHei, PingFang HK, Microsoft JhengHei, PingFang MO, Microsoft JhengHei, Apple SD Gothic Neo, Malgun Gothic, sans-serif, Apple Color Emoji, Segoe UI Emoji, Segoe UI Symbol, Noto Color Emoji"
    fontSize: 24px
    fontWeight: 400
    lineHeight: 1.33
  heading:
    fontFamily: "pplxSans, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, Noto Sans, Hiragino Sans, Yu Gothic, Meiryo, PingFang SC, Microsoft YaHei, PingFang TC, Microsoft JhengHei, PingFang HK, Microsoft JhengHei, PingFang MO, Microsoft JhengHei, Apple SD Gothic Neo, Malgun Gothic, sans-serif, Apple Color Emoji, Segoe UI Emoji, Segoe UI Symbol, Noto Color Emoji"
    fontSize: 24px
    fontWeight: 600
    lineHeight: 1.33
  body:
    fontFamily: "pplxSans, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, Noto Sans, Hiragino Sans, Yu Gothic, Meiryo, PingFang SC, Microsoft YaHei, PingFang TC, Microsoft JhengHei, PingFang HK, Microsoft JhengHei, PingFang MO, Microsoft JhengHei, Apple SD Gothic Neo, Malgun Gothic, sans-serif, Apple Color Emoji, Segoe UI Emoji, Segoe UI Symbol, Noto Color Emoji"
    fontSize: 24px
    fontWeight: 400
    lineHeight: 1.33

spacing:
  base: 4px
  scale: [4, 8, 12, 16]

radius:
  sm: 6px
  md: 12px
  lg: 16px
  pill: 9999px

shadows:
  card: "rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.08) 0px 1px 2px 0px"
  elevated: "rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.08) 0px 1px 2px 0px"

motion:
  duration-fast: 75ms
  duration-base: 300ms
  duration-slow: 1200ms
  easing: "cubic-bezier(0.4, 0, 0.2, 1)"
---

## Rationale

Perplexity presents itself as a modern, approachable AI answer engine through a deliberately warm and minimal visual language. The color palette—anchored by a near-black primary (#27251e) against an off-white background (#fcfcf9)—creates sophisticated contrast without coldness, suggesting trustworthiness and clarity rather than corporate sterility. This warmth is reinforced by the surface color (#fdfbfa), which carries a subtle rose undertone, humanizing what could otherwise feel like a purely technical tool. The measured tokens reveal a system optimized for reading and sustained interaction: generous typography (24px base), generous line heights (1.33), and a custom typeface family (pplxSans) that prioritizes readability and personality. The spacing scale is deliberately modest (4, 8, 12, 16px increments), encouraging compact, scannable layouts that don't overwhelm users seeking quick answers.

The motion tokens (75ms fast, 300ms base, 1200ms slow) signal a design philosophy that respects user attention—rapid feedback for interactive elements, moderate timing for transitions, and slower sequences only for deliberate narrative moments. Shadows are exceptionally subtle (0.08 opacity, 1–2px blur), preventing the interface from feeling layered or heavy. Together, these choices reflect Perplexity's positioning: an answer engine that is fast, accessible, and human-centered, not intimidating or unnecessarily complex.

## 1. Visual Theme & Atmosphere

Perplexity employs a "warm minimalism" aesthetic. The combination of warm neutrals (near-black and off-white with rose undertones) creates an environment that feels simultaneously professional and inviting—suitable for both quick, transactional queries and deeper exploratory interactions. The absence of vibrant accent colors keeps visual noise low, directing attention toward content and the search input. Measured shadows are nearly imperceptible, reinforcing a flat, modern sensibility while maintaining subtle depth for interactive surfaces. This restraint signals confidence: the product doesn't need visual shouting to prove its value. The overall impression is a clean workspace, not a gaming interface or social platform.

## 2. Color System

**Primary & Contrast:** The primary color (#27251e)—a near-charcoal warm black—serves as both text and interactive element foundation. Its on-primary pairing (#ffffff, pure white) ensures maximum contrast and readability. This isn't pure black, which would feel harsh; the warm undertone softens the effect without compromising legibility.

**Neutrals & Depth:** Background (#fcfcf9) and surface (#fdfbfa) are nearly identical warm off-whites, separated only marginally. This minimal differentiation suggests a unified, non-hierarchical space—ideal for an answer engine where all information should feel equally accessible. The imperceptible separation prevents visual flatness while respecting the minimalist aesthetic.

**Text Hierarchy:** Text and text-muted both reference the primary color (#000000 and #27251e respectively), indicating that secondary text relies on opacity or weight reduction rather than color shifts. This constraint maintains tonal harmony and reduces cognitive load.

**Color Mode:** Light mode only. No dark mode tokens measured, suggesting either a deliberate design decision or current phase of deployment. The light mode is optimized for clarity and readability—appropriate for an answer engine where accuracy and trust are paramount.

## 3. Typography

**System Approach:** All measured styles (display, heading, body) share the same 24px size and 1.33 line height, indicating a typographic strategy based on weight differentiation rather than size hierarchy. Display and body are 400-weight (regular); headings are 600-weight (semibold). This flattened hierarchy reduces visual complexity and suggests that content distinction comes from structure and spacing rather than scale.

**Typeface:** pplxSans is a custom or platform-specific font family with extensive fallbacks (system fonts, sans-serif stack). The custom name suggests brand intentionality; the fallback chain ensures rendering consistency across browsers and devices. The pairings (ui-sans-serif, Segoe UI, Roboto, etc.) are modern, neutral choices, favoring legibility and web performance.

**Line Height:** 1.33 is notably generous for 24px text, resulting in ~32px line spacing. This improves readability in long-form answer passages and reduces eye strain during sustained reading—critical for a tool users may depend on for research or learning.

**Weight Strategy:** Minimal weights (400/600) reduce font-file overhead while still providing clear emphasis. 600-weight headings are visually distinct without feeling aggressive.

## 4. Components & Patterns

**Cards & Surfaces:** Shadows are consistent and minimal (rgba(0, 0, 0, 0.08) 0px 1px 2px 0px). This 1–2px blur with 8% opacity creates barely-perceptible depth—sufficient to distinguish interactive zones from flat backgrounds without creating visual clutter. Cards and elevated surfaces use identical shadows, suggesting a flattened hierarchy where most interactive elements coexist in a single visual plane.

**Border Radius:** Four tiers (6px small, 12px medium, 16px large, 9999px pill) support both subtle container definition and pronounced call-to-action buttons. The progressive scale allows flexible component design: small elements remain crisp, while buttons and large surfaces adopt warmer, more inviting rounded corners.

**Interactive States:** Motion tokens suggest rapid visual feedback: 75ms (fast) for hover/focus states ensures perceived instantaneity, while 300ms (base) governs modal transitions or multi-step interactions. The cubic-bezier easing (0.4, 0, 0.2, 1) is a standard ease-out curve, providing smooth deceleration that feels natural and not mechanical.

## 5. Spacing & Layout

**Spacing Scale:** A base unit of 4px with a scale [4, 8, 12, 16] provides five logical increments: 4px (tight, micro-spacing), 8px (comfortable padding), 12px (medium), 16px (generous). All multiples of 4 ensure pixel-perfect rendering and alignment. The constraint—limited scale depth—encourages discipline and consistency, preventing arbitrary spacing decisions.

**Application:** Most UI elements likely use 8px or 16px gaps, creating rhythm without excessive whitespace. Form inputs, buttons, and cards probably employ 12–16px internal padding. The modest scale suggests compact, information-dense layouts optimized for quick scanning rather than sprawling, spacious design.

**Grid Alignment:** No breakpoints measured, indicating either a single-column responsive strategy or measured values limited to desktop. Recommend 4px grid for all layouts to align with the spacing base.

## 6. Motion & Interaction

**Timing Hierarchy:**
- **Fast (75ms):** Micro-interactions—button presses, focus states, hover effects. Fast enough that users perceive immediacy without conscious delay.
- **Base (300ms):** Standard transitions—modals appearing, lists expanding, page-level changes. Noticeable but not slow; feels responsive and intentional.
- **Slow (1200ms):** Rare, deliberate sequences—onboarding flows, tutorial highlights, or long-form animations. The 1200ms value is unusual; suggests this is reserved for special, narrative moments, not routine interactions.

**Easing:** The cubic-bezier(0.4, 0, 0.2, 1) curve is a standard Material Design ease-out, decelerating smoothly. This creates natural, organic motion—not robotic or jarring. Appropriate for an AI product that wants to feel responsive but not artificial.

**Philosophy:** Motion is minimal and purposeful. No perpetual animations or decorative flourishes. Every motion transition should justify its timing and have a functional purpose (drawing attention, confirming state, or guiding focus).

## Accessibility

### Contrast Ratios

**Primary Text vs. Background:** #27251e on #fcfcf9.
- Hex #27251e approximates RGB(39, 37, 30); hex #fcfcf9 approximates RGB(252, 251, 249).
- Approximate contrast ratio: **15:1 or higher**, well exceeding WCAG AAA (7:1) and AA (4.5:1) thresholds.
- **Result:** Excellent contrast. Even users with moderate color blindness or low-vision conditions will reliably distinguish text from background.

**Secondary Text (text-muted):** Both primary and muted reference similar dark tones, suggesting opacity reduction or weight reduction for secondary text. If muted text uses 60% opacity of the primary, contrast would still exceed **9:1**, maintaining AAA compliance.

### Minimum Requirements

**Touch Targets:** Recommend all interactive elements (buttons, links, form inputs) meet or exceed 44×44px in the rendered interface. The measured spacing scale (8–16px padding) combined with 24px typography should naturally produce compliant targets for most button and link components. Verify during component implementation.

**Focus Indicators:** Implement 2px outline in the primary color (#27251e) with 2px offset from the element boundary. At high contrast and moderate width, this exceeds WCAG 2.4.7 visibility requirements. Ensure focus states remain visible against both background and surface colors; the primary color's high contrast supports this.

**Keyboard Navigation:** All functionality exposed via "Sign In" CTA and any interactive elements must be keyboard-accessible. Test tab order and focus management, particularly if the answer engine includes expandable sections, multi-step interactions, or modal dialogs.

**Typeface Readability:** The 24px base size and 1.33 line height are generous and support users with mild dyslexia or visual processing disorders. Ensure the pplxSans fallback chain does not degrade readability; test on devices where the custom font may not load.

</design-context>

Use the design system above for all UI you generate.