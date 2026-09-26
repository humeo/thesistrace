import "../../src/styles.css";
import { Toaster } from "../../src/components/ui/toast";
import { LanguageControls } from "./language-controls";
import { createRoot } from "react-dom/client";
import { StrategyEvents } from "../../src/analysis/StrategyEvents";
createRoot(document.getElementById("root")!).render(<main style={{ padding: 24 }}><LanguageControls /><StrategyEvents endpoint="/api/research-runs/run_events/events/query" /><Toaster /></main>);
