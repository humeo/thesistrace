import { createRoot } from "react-dom/client";
import { ResearchRunsPage } from "../../src/research-runs/ResearchRunsPage";
import "../../src/styles.css";

createRoot(document.getElementById("root")!).render(
  <ResearchRunsPage researcherId="test" runId="run_evidence" />,
);
