import { createRoot } from "react-dom/client";
import { OperatorDatasetStatus } from "../../src/operator/OperatorDatasetStatus";

createRoot(document.getElementById("root")!).render(
  <main className="operator-page">
    <h1>Data operations</h1>
    <OperatorDatasetStatus
      reloadGeneration={0}
      onAccessNotFound={() => { throw new Error("Unexpected access rejection"); }}
    />
  </main>,
);
