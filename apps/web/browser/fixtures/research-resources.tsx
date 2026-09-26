import "../../src/styles.css";
import { createRoot } from "react-dom/client";
import { CopilotKitContext, CopilotKitCoreReact, EMPTY_SET } from "@copilotkit/react-core/v2/context";
import { ResearchA2UIActivity } from "../../src/chat/researchA2UI";
import { Toaster } from "../../src/components/ui/toast";
import { LanguageControls } from "./language-controls";
const copilotkit = new CopilotKitCoreReact({ deferInitialConnection: true, runtimeTransport: "rest", runtimeUrl: "/api/agent/copilotkit" });
const catalog = new URLSearchParams(location.search).has("catalog");
const components = catalog ? [
  { component: "Column", id: "root", children: ["formula", "table", "resources"] },
  { component: "Formula", id: "formula", expression: "rank(close) + ".repeat(50), label: "Research formula" },
  { component: "Table", id: "table", caption: "Research sample", summary: "Inspect sample", columns: Array.from({ length: 12 }, (_, i) => `Metric ${i + 1}`), rows: Array.from({ length: 100 }, (_, i) => Array.from({ length: 12 }, (_, j) => `Sample ${i + 1}:${j + 1}`)) },
  { component: "ResearchComparison", id: "resources", runIds: ["run_0123456789abcdef0123", "run_1123456789abcdef0123"] },
] : [{ component: "ResearchComparison", id: "root", runIds: ["run_0123456789abcdef0123", "run_1123456789abcdef0123"] }];
createRoot(document.getElementById("root")!).render(<CopilotKitContext.Provider value={{ copilotkit, executingToolCallIds: EMPTY_SET }}>
  <LanguageControls />
  <main style={{ maxWidth: 800, margin: "auto", padding: 16, minWidth: 0 }}>
    <ResearchA2UIActivity message={{ id: "a2ui-surface-test", role: "activity", activityType: "a2ui-surface", content: { a2ui_operations: [
      { version: "v0.9", createSurface: { catalogId: "urn:thesistrace:a2ui:research:v0.9", surfaceId: "resources" } },
      { version: "v0.9", updateComponents: { surfaceId: "resources", components } },
    ] } }} />
  </main><Toaster />
</CopilotKitContext.Provider>);
