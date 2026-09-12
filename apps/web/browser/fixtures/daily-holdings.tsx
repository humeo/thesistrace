import { createRoot } from "react-dom/client";
import { DailyHoldings } from "../../src/analysis/DailyHoldings";
createRoot(document.getElementById("root")!).render(<main style={{ padding: 24 }}><DailyHoldings endpoint="/api/research-runs/run_holdings/holdings/query" /></main>);
