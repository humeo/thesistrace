import {
  CopilotKitContext,
  CopilotKitCoreReact,
  EMPTY_SET,
} from "@copilotkit/react-core/v2/context";
import { useEffect, useMemo, useState, type ReactNode } from "react";

const RESEARCH_CHAT_RUNTIME_URL = "/api/agent/copilotkit";

export function ResearchChatCopilotProvider({ children }: { children: ReactNode }) {
  const [copilotkit] = useState(() => new CopilotKitCoreReact({
    credentials: "include",
    deferInitialConnection: true,
    runtimeTransport: "rest",
    runtimeUrl: RESEARCH_CHAT_RUNTIME_URL,
  }));
  const context = useMemo(
    () => ({ copilotkit, executingToolCallIds: EMPTY_SET }),
    [copilotkit],
  );

  useEffect(() => {
    copilotkit.connect();
  }, [copilotkit]);

  return (
    <CopilotKitContext.Provider value={context}>
      {children}
    </CopilotKitContext.Provider>
  );
}
