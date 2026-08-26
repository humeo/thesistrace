# Expose semantic Research results through bounded MCP views

Research Agents may read all product-visible ResearchRun and DailyTrack result
semantics, including authorable input, Factor horizons, Strategy summaries and
Benchmark, cursor-paginated observations and positions, Terminal Strategy State,
and provenance. Compact read Tools and bounded result-page Tools are the public
interface; physical Result Bundle manifests, object keys, private Checkpoints,
and recovery state remain inaccessible, and optional MCP resources do not replace
the Tool interface.
