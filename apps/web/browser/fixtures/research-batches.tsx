import { LanguageControls } from "./language-controls";
import { useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { ResearchBatchesPage } from "../../src/research-runs/ResearchBatchesPage";

function subscribe(listener: () => void) {
  window.addEventListener("popstate", listener);
  return () => window.removeEventListener("popstate", listener);
}
function Fixture() {
  const path = useSyncExternalStore(subscribe, () => window.location.pathname);
  const batchId = path.match(/^\/research-runs\/batches\/(batch_[a-z0-9]+)$/)?.[1];
  return <ResearchBatchesPage key={batchId ?? "list"} batchId={batchId} />;
}
createRoot(document.getElementById("root")!).render(<><LanguageControls /><Fixture /></>);
