import { LanguageControls } from "./language-controls";
import { createRoot } from "react-dom/client";
import { CommonInputObservations } from "../../src/analysis/CommonInputObservations";

createRoot(document.getElementById("root")!).render(
  <main style={{ padding: 32 }}><LanguageControls /><CommonInputObservations endpoint="/inputs" /></main>,
);
