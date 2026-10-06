import { WorkspaceQueryProvider } from "../../src/shell/WorkspaceQueryProvider";
import { LanguageControls } from "./language-controls";
import "../../src/styles.css";
import { createRoot } from "react-dom/client";
import { ResearchRunsPage } from "../../src/research-runs/ResearchRunsPage";

createRoot(document.getElementById("root")!).render(
  <WorkspaceQueryProvider researcherId="test"><LanguageControls /><ResearchRunsPage researcherId="test" runId="run_cancel" /></WorkspaceQueryProvider>,
);
