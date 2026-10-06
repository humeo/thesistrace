import { WorkspaceQueryProvider } from "../shell/WorkspaceQueryProvider";
import { HttpAgent } from "@ag-ui/client";
import { CopilotKitContext, CopilotKitCoreReact, EMPTY_SET } from "@copilotkit/react-core/v2/context";
import { useState, type ReactNode } from "react";
import { ChatUiProvider } from "./ChatUiProvider";
import type { ChatConversationController } from "./useChatConversation";

/** Local presentation harness: real library components, no runtime connection. */
export function ChatTestProvider({ children }: { children: ReactNode; controller?: ChatConversationController }) {
  const [copilotkit] = useState(() => new CopilotKitCoreReact({
    agents__unsafe_dev_only: { default: new HttpAgent({ url: "/test-agent-unused" }) },
    deferInitialConnection: true,
  }));
  return <WorkspaceQueryProvider researcherId="chat-fixture"><CopilotKitContext.Provider value={{ copilotkit, executingToolCallIds: EMPTY_SET }}>
    <ChatUiProvider><div className="quantgrove-chat h-full min-h-0">{children}</div></ChatUiProvider>
  </CopilotKitContext.Provider></WorkspaceQueryProvider>;
}
