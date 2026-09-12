import { createRoot } from "react-dom/client";
import { StrategyEvents } from "../../src/analysis/StrategyEvents";
createRoot(document.getElementById("root")!).render(<main style={{ padding: 24 }}><StrategyEvents endpoint="/api/research-runs/run_events/events/query" /></main>);
