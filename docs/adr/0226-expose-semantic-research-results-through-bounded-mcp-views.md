# Expose semantic Research results through bounded MCP views

Research Agents may read all product-visible ResearchRun and DailyTrack result
semantics, including authorable input, Factor horizons, Strategy summaries and
the bounded fixed CSI 300 Strategy Comparison metadata, Entry/Terminal facts and
metrics, cursor-paginated observations and positions, Terminal Strategy State,
and provenance. Comparison curves remain in the ordinary ResearchRun/DailyTrack
Detail read models instead of expanding the bounded MCP summary. Compact read
Tools and bounded result-page Tools are the public interface; physical Result
Bundle manifests, object keys, private Checkpoints, and recovery state remain
inaccessible, and optional MCP resources do not replace the Tool interface.
