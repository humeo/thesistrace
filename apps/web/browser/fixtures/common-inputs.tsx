import { createRoot } from "react-dom/client";
import { CommonInputObservations } from "../../src/analysis/CommonInputObservations";

createRoot(document.getElementById("root")!).render(
  <main style={{ padding: 32 }}><CommonInputObservations endpoint="/inputs" /></main>,
);
