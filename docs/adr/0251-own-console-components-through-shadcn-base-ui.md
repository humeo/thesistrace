---
Status: accepted
---

# Own console components through shadcn/ui and Base UI

Quantgrove's console and authentication UI will use repository-owned shadcn/ui components backed by Base UI, with Tailwind and semantic CSS variable tokens. This replaces the interrupted plan's direct Radix integration and independently styled basic controls: owning one component layer makes the Classic visual rules and interaction behavior consistently reusable across pages, at the cost of maintaining those component sources and migrating their consumers.

Pages compose the UI foundation through layout and product components. Business modules continue to own drafts, requests, validation and state transitions; adopting a UI foundation does not transfer domain behavior to a form library. Preserve the existing public landing, specialized editor/chart capabilities and service contracts. The design rules remain in [DESIGN.md](../../DESIGN.md), and domain vocabulary remains in [CONTEXT.md](../../CONTEXT.md).

Shared date controls use shadcn composition while preserving ISO date values and existing validation. Lightweight feedback uses the official Base UI Toast; errors requiring action remain in the relevant page. Automated checks enforce basic-control and primitive-import ownership, with explicit boundaries for the preserved landing and specialized renderers. Product metrics use compact shared groups with optional summary cards, retaining domain-owned formatting and missing-value semantics.

This record captures the architectural direction and six choices explicitly selected by the user. The resulting implementation specification is ready for an agent; acceptance records the decision, not implementation or test completion. Publishing the specification does not itself perform the migration.
