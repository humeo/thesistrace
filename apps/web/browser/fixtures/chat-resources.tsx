import { createRoot } from "react-dom/client";
import { ResearchA2UIActivity } from "../../src/chat/researchA2UI";
import { ChatUiProvider } from "../../src/chat/ChatUiProvider";
import { ResearchResourceProvider } from "../../src/chat/ResearchResourceProvider";
import { WorkspaceQueryProvider } from "../../src/shell/WorkspaceQueryProvider";
import "../../src/styles.css";

createRoot(document.getElementById("root")!).render(
  <main className="quantgrove-chat" style={{ width: 808, padding: 20, margin: "auto" }}>
    <WorkspaceQueryProvider researcherId="research-fixture"><ChatUiProvider><ResearchResourceProvider><ResearchA2UIActivity message={{
      id: "research-results", role: "activity", activityType: "a2ui-surface", content: {
        a2ui_operations: [
          { version: "v0.9", createSurface: { catalogId: "urn:thesistrace:a2ui:research:v0.9", surfaceId: "results" } },
          { version: "v0.9", updateComponents: { surfaceId: "results", components: [
            { id: "root", component: "Column", gap: "wide", align: "center", children: ["intro", "heading", "run"] },
            { id: "intro", component: "Text", text: "The authoritative research results are ready." },
            { id: "heading", component: "Text", variant: "title", text: "Factor comparison" },
            { id: "run", component: "ResearchComparison", runIds: ["run_0123456789abcdef0123", "run_1123456789abcdef0123", "run_2123456789abcdef0123"] },
          ] } },
        ],
      },
    }} /></ResearchResourceProvider></ChatUiProvider></WorkspaceQueryProvider>
  </main>,
);
