import { LanguageControls } from "./language-controls";
import { createRoot } from "react-dom/client";
import { ResearchRunsPage } from "../../src/research-runs/ResearchRunsPage";

createRoot(document.getElementById("root")!).render(
  <><LanguageControls /><ResearchRunsPage researcherId="test" runId="run_cancel" /></>,
);
