import { createRoot } from "react-dom/client";
import { CopilotKitContext, CopilotKitCoreReact, EMPTY_SET } from "@copilotkit/react-core/v2/context";
import { ResearchA2UIActivity } from "../../src/chat/researchA2UI";
const copilotkit = new CopilotKitCoreReact({ deferInitialConnection: true, runtimeTransport: "rest", runtimeUrl: "/api/agent/copilotkit" });
createRoot(document.getElementById("root")!).render(<CopilotKitContext.Provider value={{ copilotkit, executingToolCallIds: EMPTY_SET }}><ResearchA2UIActivity message={{ id: "a2ui-surface-test", role: "activity", activityType: "a2ui-surface", content: { a2ui_operations: [
  { version: "v0.9", createSurface: { catalogId: "urn:thesistrace:a2ui:research:v0.9", surfaceId: "resources" } },
  { version: "v0.9", updateComponents: { surfaceId: "resources", components: [{ component: "ResearchComparison", id: "root", runIds: ["run_0123456789abcdef0123", "run_1123456789abcdef0123"] }] } },
] } }} /></CopilotKitContext.Provider>);
