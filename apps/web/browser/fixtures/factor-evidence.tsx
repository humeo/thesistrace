import { LanguageControls } from "./language-controls";
import { createRoot } from "react-dom/client";
import { FactorEvidence } from "../../src/analysis/FactorEvidence";

createRoot(document.getElementById("root")!).render(
  <main style={{ padding: 24 }}><LanguageControls /><FactorEvidence runId="run-factor" /></main>,
);
