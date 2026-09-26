import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "../../src/styles.css";
import { ResearchRunsPage } from "../../src/research-runs/ResearchRunsPage";
import { LanguageControls } from "./language-controls";
function Fixture() {
  const [path, setPath] = useState(location.pathname);
  useEffect(() => { const update = () => setPath(location.pathname); window.addEventListener("popstate", update); return () => window.removeEventListener("popstate", update); }, []);
  const runId = path.startsWith("/research-runs/run_") ? path.split("/").at(-1) : undefined;
  return <><LanguageControls /><ResearchRunsPage researcherId="test" runId={runId} /></>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
