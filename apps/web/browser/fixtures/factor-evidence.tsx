import { createRoot } from "react-dom/client";
import { FactorEvidence } from "../../src/analysis/FactorEvidence";

createRoot(document.getElementById("root")!).render(
  <main style={{ padding: 24 }}><FactorEvidence runId="run-factor" /></main>,
);
