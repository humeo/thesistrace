# Factor Evaluation Research Kind

**Status:** ready-for-agent

## Problem Statement

ThesisTrace currently treats every Research as a complete Factor Evaluation and
Strategy Backtest. A researcher who only wants to determine whether an Alpha has
predictive and ranking value must still provide Holdings Count and Rebalance
Sessions, wait for Strategy execution, and receive Strategy results that are not
part of the question being asked.

The current product therefore conflates two distinct research intentions. It also
makes Factor Evaluation appear to be an incidental section of a backtest rather
than a first-class Research outcome. The researcher needs a dedicated Factor
Evaluation choice without introducing another resource, Worker pool, execution
engine, recovery model, or source of scientific semantics.

## Solution

Add an immutable Research Kind to Browser Draft and ResearchRun with exactly two
values: `factor_evaluation` and `strategy_backtest`. The existing Research form
exposes the choice and defaults new Browser Drafts to Factor Evaluation.

Both kinds use the same Run Action, admission, selected Data Generation, FIFO
ResearchRun Queue, single-slot Research Worker, execution child, Alpha and Factor
calculation, ResearchRun Execution Chunks, private ResearchRun Execution
Checkpoints, retry, cancellation, recovery, Publication, and provenance. Factor
Evaluation ends after the shared Factor calculation. Strategy Backtest continues
through the existing Strategy calculation.

Factor Evaluation accepts no Strategy parameters and publishes a Result Bundle
containing exactly `factor_summary`. Its primary user-visible result is Rank IC,
Rank ICIR, IC, and ICIR for the fixed 1-, 5-, and 20-session Forward Return Label
horizons, accompanied by valid-session Coverage. Existing Five-Quantile Return
and Top-Bottom Return diagnostics remain calculated and retained in the Factor
Summary but are not shown as primary metrics. Insufficient samples produce null
metrics and zero Coverage without failing the ResearchRun.

Strategy Backtest preserves the complete current flow and publishes
`factor_summary`, `strategy_summary`, `strategy_daily_observations`, and
`terminal_strategy_state`. With identical frozen Factor inputs and the same Data
Generation, both Research Kinds must publish an exactly identical Factor Summary.
Only Strategy Backtest may seed a DailyTrack.

## User Stories

1. As a quantitative researcher, I want to choose Factor Evaluation when my question is about predictive power, so that I do not have to run an unrelated portfolio simulation.
2. As a quantitative researcher, I want new Browser Drafts to default to Factor Evaluation, so that the product encourages validating a factor before interpreting a backtest.
3. As a quantitative researcher, I want Strategy Backtest available from the same Research form, so that both research intentions remain easy to access.
4. As a quantitative researcher, I want the selected Research Kind frozen with the ResearchRun, so that the meaning of a historical Result cannot change after admission.
5. As a quantitative researcher, I want Factor Evaluation to require only Formula, Research Period, Universe, and neutralization inputs, so that Strategy configuration does not obstruct factor research.
6. As a quantitative researcher, I want Holdings Count hidden for Factor Evaluation, so that an irrelevant parameter cannot imply portfolio semantics.
7. As a quantitative researcher, I want Rebalance Sessions hidden for Factor Evaluation, so that an irrelevant schedule cannot affect the factor question.
8. As a quantitative researcher, I want Holdings Count required for Strategy Backtest, so that portfolio construction remains explicit.
9. As a quantitative researcher, I want Rebalance Sessions required for Strategy Backtest, so that Strategy timing remains explicit.
10. As a quantitative researcher, I want one Factor Evaluation Run to calculate Rank IC for 1-, 5-, and 20-session horizons, so that I can compare short- and medium-horizon ranking power.
11. As a quantitative researcher, I want one Factor Evaluation Run to calculate Rank ICIR for all three horizons, so that I can compare ranking stability.
12. As a quantitative researcher, I want one Factor Evaluation Run to calculate IC for all three horizons, so that I can inspect magnitude-sensitive predictive correlation.
13. As a quantitative researcher, I want one Factor Evaluation Run to calculate ICIR for all three horizons, so that I can inspect magnitude-sensitive stability.
14. As a quantitative researcher, I want each Horizon to show valid Rank IC session Coverage, so that I know how much evidence supports the reported Rank IC and Rank ICIR.
15. As a quantitative researcher, I want each Horizon to show valid IC session Coverage, so that I know how much evidence supports the reported IC and ICIR.
16. As a quantitative researcher, I want insufficient Factor samples shown as unavailable rather than zero, so that missing evidence is never presented as neutral predictive power.
17. As a quantitative researcher, I want a valid short Research Period to succeed even when one or more metrics are unavailable, so that data scarcity is not misreported as an execution failure.
18. As a quantitative researcher, I want only the four primary metrics and Coverage emphasized in the Factor Evaluation view, so that the result is focused and readable.
19. As a quantitative researcher, I want existing Five-Quantile Return and Top-Bottom Return diagnostics retained in the authoritative Factor Summary, so that current scientific evidence is not discarded during this product change.
20. As a quantitative researcher, I want Factor Evaluation to publish no empty Strategy fields, so that the Result truthfully represents the work performed.
21. As a quantitative researcher, I want Strategy Backtest to continue showing Factor metrics before Strategy metrics, so that I can distinguish predictive quality from portfolio construction outcomes.
22. As a quantitative researcher, I want identical frozen Factor inputs to produce an identical Factor Summary in both Research Kinds, so that choosing a Strategy cannot change Factor semantics.
23. As a quantitative researcher, I want Research lists to show the frozen Research Type, so that otherwise similar Runs remain distinguishable.
24. As a quantitative researcher, I want Research details to show the frozen Research Type, so that I can interpret the available Result sections correctly.
25. As a quantitative researcher, I want a Factor Evaluation detail to omit Strategy Summary, Strategy observations, and Terminal Strategy State, so that absent work is not represented by placeholders.
26. As a quantitative researcher, I want a Strategy Backtest detail to retain its existing Factor and Strategy sections, so that the complete current research report remains available.
27. As a quantitative researcher, I want Use as Draft to preserve Research Kind, so that reusing a historical Factor Evaluation does not silently become a Strategy Backtest.
28. As a quantitative researcher, I want Use as Draft to preserve applicable Strategy parameters for a Strategy Backtest, so that deliberate reuse remains complete.
29. As a quantitative researcher, I want to change Research Kind only in a Browser Draft before a new Run, so that a historical ResearchRun remains immutable.
30. As a quantitative researcher, I want conversion from Factor Evaluation to Strategy Backtest to use the existing Use as Draft flow, so that there is no hidden derived-Run lifecycle.
31. As a quantitative researcher, I want Start Tracking unavailable for Factor Evaluation, so that a Result without a Strategy account cannot create an invalid DailyTrack.
32. As a quantitative researcher, I want Start Tracking to remain available for a successful Strategy Backtest, so that the current continuous Strategy workflow is preserved.
33. As a quantitative researcher, I want Factor Evaluation to report committed Chunk progress, so that a long historical evaluation does not appear stalled.
34. As a quantitative researcher, I want to cancel queued or running Factor Evaluation through the same action as any ResearchRun, so that Research lifecycle behavior remains consistent.
35. As a quantitative researcher, I want an infrastructure retry to remain an Attempt of the same Factor Evaluation ResearchRun, so that recovery does not create duplicate research history.
36. As a quantitative researcher, I want a Factor Evaluation Result published only after the complete Run succeeds, so that partial summaries cannot be mistaken for authoritative evidence.
37. As a quantitative researcher, I want Formula, requested dates, Universe, neutralization, Research Kind, contracts, and Data Generation visible in provenance, so that the Factor result remains reproducible.
38. As an operator, I want Factor Evaluation and Strategy Backtest to share the strict FIFO ResearchRun Queue, so that scheduling remains predictable.
39. As an operator, I want both Research Kinds to use the existing fixed-role Research Worker pool, so that introducing Factor Evaluation does not create another capacity model.
40. As an operator, I want one Factor Evaluation Attempt to occupy one Worker execution slot, so that the declared 2-vCPU and 2-GiB envelope remains enforceable.
41. As an operator, I want Factor Evaluation to reuse the existing Generation Pin and fencing rules, so that cancellation and failure cannot race data collection or Publication.
42. As an operator, I want the 2010-to-latest Top 3000 reference workload for each Research Kind to pass the warm P95 five-minute gate, so that both product claims remain measurable.
43. As an operator, I want cold and warm performance measured separately for both Research Kinds, so that cache effects remain explicit.
44. As an operator, I want both Research Kinds to obey the same peak RSS, first Checkpoint, and cancellation gates, so that faster execution cannot weaken containment or operability.
45. As a Research platform maintainer, I want Alpha and Factor calculation implemented once, so that the two Research Kinds cannot drift scientifically.
46. As a Research platform maintainer, I want the execution branch to occur only after the shared Factor work, so that Factor Evaluation is not a second execution engine.
47. As a Research platform maintainer, I want Research Kind included in immutable input and idempotency identity, so that retries and duplicate requests cannot change the intended Result type.
48. As a Research platform maintainer, I want Result validation discriminated by Research Kind, so that missing required objects and unexpected Strategy objects fail closed.
49. As a Research platform maintainer, I want Factor-only Checkpoints to exclude Strategy continuation, so that private recovery state contains only work required by that Research Kind.
50. As a Research platform maintainer, I want Strategy Backtest Checkpoints to retain current Strategy continuation, so that existing recovery semantics remain complete.
51. As a Research platform maintainer, I want Factor Summary equivalence tested through complete public ResearchRuns, so that implementation refactoring cannot hide semantic drift behind a private seam.
52. As a product maintainer, I want the Result contract hard-cut in development without migrations or compatibility readers, so that the runtime has one current meaning.
53. As a product maintainer, I want development Product State reset while Canonical Data is preserved, so that the hard cut does not require downloading market and financial history again.
54. As a frontend maintainer, I want the Research Type control and conditional fields to follow the pinned Design system, so that the new choice fits the existing quiet utility interface.
55. As a frontend maintainer, I want keyboard and screen-reader users to operate the Research Type control and understand conditional parameters, so that the feature remains accessible.

## Implementation Decisions

### Domain and product model

- ResearchRun remains the only durable Research resource. Research Kind is an
  immutable value within its frozen input, not a separate Factor resource or a
  Worker role.
- Research Kind has exactly two values: `factor_evaluation` and
  `strategy_backtest`.
- New Browser Drafts default to `factor_evaluation`. Use as Draft copies the
  frozen Research Kind and applicable authorable inputs.
- The Research authoring surface presents one two-choice Research Type control.
  Factor Evaluation shows no Strategy parameters. Strategy Backtest requires
  Holdings Count and Rebalance Sessions.
- Research list and detail representations include the frozen Research Kind.
  The detail view renders only Result sections valid for that kind.
- There is no direct Factor-to-Strategy action. A researcher uses Use as Draft,
  selects Strategy Backtest, supplies Strategy parameters, and performs the
  ordinary Run Action.
- Only a successful Strategy Backtest may seed a DailyTrack. A Factor Evaluation
  Start Tracking request is rejected by the authoritative backend, and the
  frontend does not offer the action.

### Admission and immutable input

- The ResearchRun admission command becomes a discriminated Research Kind
  contract rather than flat optional Strategy fields.
- Factor Evaluation accepts Formula, Hypothesis, requested dates, Universe, and
  neutralization and rejects Holdings Count or Rebalance Sessions.
- Strategy Backtest requires the same common research fields plus Holdings Count
  and Rebalance Sessions.
- Research Kind participates in the immutable-input checksum, admission
  fingerprint, request idempotency, provenance, retry validation, Checkpoint
  binding, and calculation-contract validation.
- Admission freezes one selected Data Generation and one Research Execution Plan
  using the existing peak-memory and full-Universe rules.
- Product State uses a hard current-schema cut. There is no migration,
  compatibility reader, fallback, dual Result schema, or runtime version
  dispatcher. Development reset preserves Canonical Data and the Dataset Head.

### Shared execution

- Both Research Kinds claim through the existing strict FIFO ResearchRun Queue
  and execute in the same single-slot Research Worker pool and supervised child
  process.
- Both kinds use the existing columnar data reads, Alpha compilation and
  evaluation, Forward Return Label maturation, Factor aggregation, Chunk plan,
  supervisor acknowledgement, Checkpoint publication, fencing, retry,
  cancellation, and recovery implementation.
- The execution branch occurs after the shared Factor work. Factor Evaluation
  finalizes Factor state and returns. Strategy Backtest continues through the
  existing Strategy calculation and terminal account finalization.
- Factor-only continuation and Checkpoints contain the shared bounded Alpha,
  pending Label, Factor, checksum, and progress state but no Strategy
  continuation or Strategy observation descriptors.
- Strategy Backtest retains the current bounded Strategy continuation and staged
  Strategy observation behavior.
- No second Factor executor, queue, Worker role, numeric route, checkpoint
  engine, Publication implementation, or fallback path is introduced.

### Factor result

- Factor Evaluation publishes a Result Bundle containing exactly
  `factor_summary`. It never publishes empty Strategy values or a second Result
  type disguised as the current four-object bundle.
- Strategy Backtest publishes exactly `factor_summary`, `strategy_summary`,
  `strategy_daily_observations`, and `terminal_strategy_state`.
- Result manifests and readers validate the exact allowed object set for the
  frozen Research Kind and reject missing or unexpected objects.
- The Factor Summary retains fixed horizons 1, 5, and 20. Each Horizon retains
  the existing IC and Rank IC correlation summaries, Five-Quantile Return,
  Top-Bottom Return, Coverage, and checksums.
- The primary Factor Evaluation view displays mean Rank IC, Rank ICIR, mean IC,
  and ICIR for each Horizon plus valid-session Coverage. Existing quantile and
  Top-Bottom diagnostics remain retained but are not primary UI metrics.
- Daily Factor observations, Alpha Values, and stock-level Forward Return Labels
  remain transient and are not added to the Result Bundle.
- Insufficient samples produce null metrics and zero valid-session counts without
  failing an otherwise valid ResearchRun or fabricating numeric zero.
- For the same Formula, requested and resolved Research Period, Universe,
  neutralization, field bindings, calculation contracts, and Data Generation,
  both Research Kinds must publish byte-equivalent `factor_summary` content.

### User interface

- The Research Type control is placed at the top of the existing Research
  parameter area and follows the repository's pinned Design system, 8-pixel
  spacing rhythm, accessible focus treatment, and responsive breakpoint.
- Factor Evaluation is the default selected type. The type choice is explicit,
  keyboard operable, screen-reader labelled, and not inferred from whether
  Strategy inputs happen to be present.
- Switching to Factor Evaluation removes Strategy parameters from the submitted
  Draft contract rather than merely hiding populated values in the DOM.
- Switching to Strategy Backtest exposes required Holdings Count and Rebalance
  Sessions and prevents Run until they are valid.
- Research list and detail views render user-facing labels `Factor Evaluation`
  and `Strategy Backtest`, not raw persisted enum strings.
- Factor Evaluation detail displays the three Horizon sections, four primary
  metrics per Horizon, Coverage, and provenance. It omits every Strategy-only
  section and Start Tracking action.
- Strategy Backtest detail preserves the current Factor and Strategy sections,
  Strategy daily observations, terminal state, and Start Tracking action.
- Use as Draft round-trips Research Kind and applicable parameters without
  creating a backend resource.

### Performance and observability

- The reference 2010-to-2026 Top 3000 workload is run separately as Factor
  Evaluation and Strategy Backtest in the final Production Image with one 2-vCPU,
  2-GiB, single-slot Research Worker.
- For each Research Kind, warm P95 across five fresh Product State samples must
  not exceed five minutes and cold P95 must not exceed ten minutes.
- Both kinds retain the 1.5-GiB execution budget, first durable Checkpoint within
  45 seconds, and confirmed cooperative cancellation within five seconds while
  the owning supervisor remains healthy.
- Performance measurement includes admission, data reads, all calculations
  applicable to the Research Kind, Chunk Checkpoints, finalization, and atomic
  Result publication. Queue waiting is excluded.
- Structured execution evidence records Research Kind and phase timings. Factor
  Evaluation evidence must show no Strategy phase work or Strategy Result
  objects.

## Testing Decisions

- Tests assert observable Research behavior and scientific invariants rather
  than private function names, branch calls, or invocation counts.
- The primary test seam is the existing public ResearchRun interface. Tests admit
  both Research Kinds, run real Workers, read public detail and Result views,
  cancel work, exercise retry and restart, perform Use as Draft, and attempt
  Start Tracking without creating a second execution seam.
- Pure command and Result-shape rules are tested at the model interface: Factor
  Evaluation rejects Strategy fields, Strategy Backtest requires them, unknown
  Research Kinds fail, and each Result Bundle accepts exactly its declared
  object set.
- Real PostgreSQL, RustFS, Publication, Research Worker, and child subprocesses
  test admission, idempotency, claim, Generation Pin, Chunk Checkpoint,
  cancellation, infrastructure retry, Worker loss, restart, atomic publication,
  stale fencing, deletion, and exact Result object ownership for both kinds.
- One acceptance scenario admits Factor Evaluation and Strategy Backtest with
  identical frozen Factor inputs against the same Data Generation and asserts
  exact `factor_summary` equivalence, including the four primary metrics,
  retained diagnostics, Coverage, and checksums.
- One acceptance scenario proves Factor Evaluation publishes no Strategy object
  and cannot seed a DailyTrack; another proves Strategy Backtest retains the
  current four-object Result and can seed one DailyTrack.
- Factor calculation keeps its existing row-reference and Chunked-versus-
  uninterrupted equivalence coverage. Factor-only execution adds regression
  coverage for null metrics and zero Coverage under insufficient samples.
- Browser tests exercise the Research Type choice, Factor default, conditional
  Strategy fields, submission payload, list Type, conditional detail sections,
  Use as Draft round trip, absent Factor-only Start Tracking action, keyboard
  access, and responsive layout.
- Browser tests use the real public response shapes rather than duplicating an
  alternate client-only domain model.
- Production Image qualification executes five cold and five warm fresh Runs for
  each Research Kind and enforces duration, RSS, first Checkpoint, cancellation,
  manifest, child-exit, and cleanup evidence.
- Database-restart acceptance proves both discriminated Result Bundles and
  Research Kind provenance reopen under the current schema.
- Development lifecycle acceptance proves the required Product State reset
  removes obsolete Runs and Results while preserving Canonical Data and the
  exact Dataset Head.
- Prior art is the current direct ResearchRun admission acceptance, supervised
  child and Chunk continuation equivalence coverage, Publication object-set
  validation, cancellation and retry recovery acceptance, Use as Draft browser
  coverage, DailyTrack activation rules, and long Research Production Image
  qualification.

## Out of Scope

- A separate FactorEvaluation resource, endpoint family, queue, Worker pool,
  execution engine, checkpoint implementation, or Publication implementation.
- Configurable Factor horizons; V1 remains fixed at 1, 5, and 20 sessions.
- Publishing daily Factor observations, Alpha Values, stock-level Labels, Factor
  curves, or cumulative long-short charts.
- Removing Five-Quantile Return or Top-Bottom Return calculation and retained
  diagnostics.
- A FactorTrack or another incremental monitoring resource for Factor-only
  Research.
- Starting a DailyTrack from Factor Evaluation.
- A direct Backtest This Factor or derived-Run action. Use as Draft remains the
  only product reuse action.
- Reusing a successful Factor Evaluation's transient Alpha matrices or private
  Checkpoints as a cache for a new Strategy Backtest.
- Changing Strategy construction, transaction costs, Benchmark, holdings,
  rebalance, order, fill, cash, NAV, or terminal-state semantics.
- Parallel execution of Alpha, Factor, or Strategy stages inside one Worker.
- Compatibility readers, Product State migrations, fallback execution, V2
  resources, or dual schema operation.
- A new user-facing performance SLA or ETA promise; the performance limits are
  implementation acceptance and regression gates.

## Further Notes

- ADR-0214 records the decision to select Factor Evaluation or Strategy Backtest
  within one ResearchRun and reuse the complete execution lifecycle.
- ADR-0204 applies the complete Production Image performance gate to both
  Research Kind variants.
- Factor Evaluation remains scientifically independent of Strategy outcome even
  when Strategy Backtest includes the same Factor Summary.
- The four primary metrics are summaries of daily cross-sectional correlations,
  not pooled stock-day correlations, annualized Strategy ratios, or portfolio
  returns.
