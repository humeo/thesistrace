# 02 — Author and reuse Research Kinds without ambiguity

**What to build:** Give researchers one clear Research Type choice in the existing
Research workspace, default new work to Factor Evaluation, and preserve the chosen
type through admission, history, detail, and Use as Draft without leaking
inapplicable Strategy inputs.

**Blocked by:** 01 — Run two immutable Research Kinds end to end

**Status:** complete

## Plan

1. Characterize the existing Draft, admission, list, detail, and reuse behavior with focused public-contract tests so the remaining gaps are explicit.
2. Implement one accessible two-choice Research Type control at the top of the Research parameters, clear inapplicable Strategy values when Factor Evaluation is selected, and keep validation, payload, and pending-idempotency state exact for each kind.
3. Complete kind labels and conditional Result/action rendering across history, detail, and Use as Draft while preserving the established Strategy Backtest journey.
4. Add responsive styling and real-browser coverage for keyboard-accessible selection, conditional inputs, reuse, list/detail labels, and compact layouts.
5. Run the focused frontend gates, type checks, and relevant browser acceptance; then complete independent Standards and Spec reviews, fix and re-review any findings, mark the ticket complete, and commit it independently.

- [x] New Browser Drafts default to Factor Evaluation and present one explicit two-choice Research Type control at the top of the existing parameter area.
- [x] The control uses the user-facing labels `Factor Evaluation` and `Strategy Backtest`, follows the repository Design system, and is keyboard operable and screen-reader labelled.
- [x] Factor Evaluation shows Formula, Research Period, Universe, and Neutralization inputs without Holdings Count or Rebalance Sessions.
- [x] Strategy Backtest shows and requires Holdings Count and Rebalance Sessions in addition to the common Research inputs.
- [x] Switching to Factor Evaluation removes Strategy values from the submitted Draft contract rather than merely hiding populated controls.
- [x] Switching to Strategy Backtest prevents Run until both Strategy inputs are valid.
- [x] Pending admission and browser idempotency state include Research Kind, so a retry cannot silently change the intended Result type.
- [x] Research lists and details display the frozen Research Type for queued, running, terminal, and failed Runs.
- [x] Factor Evaluation detail displays the 1-, 5-, and 20-session Factor sections with Rank IC, Rank ICIR, IC, ICIR, and valid-session Coverage.
- [x] Factor Evaluation detail omits Strategy Summary, Strategy Daily Observations, Terminal Strategy State, and Start Tracking.
- [x] Strategy Backtest detail preserves its current Factor and Strategy sections and Start Tracking action.
- [x] Use as Draft copies Research Kind and every applicable authorable input without creating a backend resource.
- [x] Reusing a Factor Evaluation remains Factor Evaluation; reusing a Strategy Backtest preserves its Strategy inputs.
- [x] A researcher can deliberately convert a reused Draft by changing Research Type and performing the ordinary Run action; no direct derived-Run action is introduced.
- [x] Browser tests cover defaulting, switching, validation, payload shape, list and detail labels, conditional Result sections, Use as Draft, accessibility, and the responsive layout through public response contracts.
