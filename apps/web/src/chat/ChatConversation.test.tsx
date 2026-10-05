// @vitest-environment happy-dom
import { HttpAgent } from "@ag-ui/client";
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";

const runtime = vi.hoisted(() => ({
  agentReady: true,
  runtimeConnectionStatus: "connected",
  notify: () => {},
  subscribe: (listener: { onRuntimeConnectionStatusChanged: () => void }) => {
    runtime.notify = listener.onRuntimeConnectionStatusChanged;
    return { unsubscribe: () => {} };
  },
}));
const agent = new HttpAgent({ url: "/api/agent" });
vi.mock("@copilotkit/react-core/v2/context", () => ({ useCopilotKit: () => ({ copilotkit: runtime }) }));
vi.mock("@copilotkit/react-core/v2/headless", () => ({
  UseAgentUpdate: {}, useAgent: () => ({ agent, isReady: runtime.agentReady }),
}));
vi.mock("./useChatConversation", () => ({ useChatConversation: ({ existingSession }: { existingSession: boolean }) => {
  const [draft, setDraft] = useState("");
  return { turns: [], phase: existingSession ? "idle" : "new", draft, setDraft };
} }));
vi.mock("./ChatTimeline", () => ({ ChatTimeline: () => null }));
vi.mock("./ChatComposer", () => ({ ChatComposer: ({ controller }: { controller: { draft: string; setDraft: (value: string) => void } }) =>
  <textarea aria-label="Message" value={controller.draft} onChange={(event) => controller.setDraft(event.target.value)} />,
}));
import { AgentConversation } from "./ChatConversation";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
test.each([
  ["connecting", true],
  ["error", true],
  ["connected", false],
  ["connected", true],
] as const)("history sessions keep their canvas while runtime is %s and agent ready is %s", async (status, ready) => {
  runtime.runtimeConnectionStatus = status;
  runtime.agentReady = ready;
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(<AgentConversation existingSession initialSession={{
      id: "session", title: "Greeting", activity_at: "2026-09-30T00:00:00Z", created_at: "2026-09-30T00:00:00Z",
      message_title: null,
      current_turn: null, latest_turn: null, version: "2026-09-30T00:00:00Z",
    }} modelControls={null} onAccepted={() => {}} onSessionChanged={() => {}} onTitleMaySettle={() => {}}
      researcherId="owner" selection={null} titleMaySettle={false} threadId="session" />));
    expect(container.querySelector(".ant-welcome")).toBeNull();
    expect(container.querySelector("main > header")).toBeNull();
    expect(container.querySelector("main")?.getAttribute("aria-label")).toBe("Greeting");
    expect(container.querySelector("textarea")?.disabled).toBe(status !== "connected" || !ready);
  } finally {
    await act(async () => root.unmount());
    container.remove();
    runtime.runtimeConnectionStatus = "connected";
    runtime.agentReady = true;
  }
});

test("runtime discovery failure preserves an already mounted conversation and draft", async () => {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(<AgentConversation existingSession={false} modelControls={null}
      onAccepted={() => {}} onSessionChanged={() => {}} onTitleMaySettle={() => {}}
      researcherId="owner" selection={null} titleMaySettle={false} threadId="session" />));
    const textarea = container.querySelector("textarea")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea, "Retain this draft");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { runtime.runtimeConnectionStatus = "error"; runtime.notify(); });
    expect(container.querySelector("textarea")).toBe(textarea);
    expect(textarea.disabled).toBe(false);
    expect(textarea.value).toBe("Retain this draft");
  } finally {
    await act(async () => root.unmount());
    container.remove();
    runtime.runtimeConnectionStatus = "connected";
  }
});
