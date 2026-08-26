# Make Research Batch a durable orchestration resource

A Research Batch atomically admits ordered ordinary ResearchRuns that share a research scope and Data Generation, owns aggregate lifecycle and cancellation, but owns no Result; every item retains its own immutable ResearchRun and Result. Factor Batches share preparation across independent Alphas, while Strategy Sweeps share one Alpha and Factor across enumerated Strategy inputs, and both must exactly match equivalent ordinary Runs without implicit cross-products or partial admission.
