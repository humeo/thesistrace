import React from "react";
import { createRoot } from "react-dom/client";
import { ResearchRunsPage } from "../../src/research-runs/ResearchRunsPage";
createRoot(document.getElementById("root")!).render(<ResearchRunsPage researcherId="test" />);
