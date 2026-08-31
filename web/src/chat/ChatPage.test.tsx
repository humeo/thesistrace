// @vitest-environment happy-dom

import type { AgentSubscriber } from "@ag-ui/client";
import type { Message } from "@ag-ui/core";
import { CopilotKitCoreReact } from "@copilotkit/react-core/v2/context";
import { expect, test, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { AuthProvider } from "../auth/AuthProvider";
import {
  AssistantMarkdown,
  ChatShell,
  ChatFailureNotice,
  ToolActivityRow,
  chatMessageBytes,
  chatTimelineItems,
  readBrowserChatThread,
  startExistingSessionConnection,
  type ConversationStatus,
} from "./ChatPage";
import { chatSessionHref } from "./chatNavigation";
import { createAgentFetch } from "./agentTransport";
import { AGENT_FAILURE_CODES, agentFailure } from "../../../contracts/agent-failure.mjs";
import {
  SessionHistoryList,
  sessionDialogErrorMessage,
} from "./SessionHistoryList";
import {
  AgentSessionInvalidError,
  AgentSessionTitleInvalidError,
} from "./sessionHistory";

const safeRunMarker = JSON.stringify({
  outcome: "completed",
  resource: {
    id: "run_0123456789abcdef0123",
    kind: "research_run",
    status: "queued",
  },
  type: "thesistrace.tool-result",
  version: 1,
});

const catalogState = {
  status: "ready" as const,
  catalog: {
    default_model_key: "research-primary",
    models: [
      {
        default_reasoning_effort: "medium" as const,
        display_name: "Research Primary",
        key: "research-primary",
        reasoning_efforts: ["low", "medium", "high"] as const,
      },
      {
        default_reasoning_effort: "high" as const,
        display_name: "Research Deep",
        key: "research-deep",
        reasoning_efforts: ["high", "xhigh"] as const,
      },
    ],
  },
};
const sessionHistory = {
  deleteSession: vi.fn(async () => undefined),
  error: null,
  loadMore: vi.fn(async () => undefined),
  loadingMore: false,
  nextCursor: null,
  refresh: vi.fn(),
  refreshVersion: 0,
  renameSession: vi.fn(async (session, title: string) => ({
    id: session.id,
    title,
    version: session.version,
  })),
  sessions: [],
  status: "ready" as const,
  watchGeneratedTitle: vi.fn(),
};

test("renders the standalone Chat hierarchy and safe model controls", () => {
  const markup = renderToStaticMarkup(
    <AuthProvider>
      <ChatShell
        catalogState={catalogState}
        navigateChat={vi.fn()}
        preferenceState={{ status: "not-required" }}
        reloadCatalog={vi.fn()}
        selectedSessionState={{ status: "not-required" }}
        sessionHistory={sessionHistory}
      />
    </AuthProvider>,
  );

  const brand = markup.indexOf("ThesisTrace");
  const newChat = markup.indexOf("New Chat");
  const data = markup.indexOf(">Data<");
  const research = markup.indexOf(">Research<");
  const researchRuns = markup.indexOf("Research Runs");
  const dailyTracks = markup.indexOf("Daily Tracks");
  const chats = markup.indexOf(">Chats<");
  expect(brand).toBeGreaterThan(-1);
  expect(brand).toBeLessThan(newChat);
  expect(newChat).toBeLessThan(data);
  expect(data).toBeLessThan(research);
  expect(research).toBeLessThan(researchRuns);
  expect(researchRuns).toBeLessThan(dailyTracks);
  expect(dailyTracks).toBeLessThan(chats);
  expect(markup).toContain('href="/chat"');
  expect(markup).toContain('aria-label="Workspace"');
  expect(markup).toContain('aria-label="Agent model settings"');
  expect(markup).toContain('<label for="chat-model">Model</label><select id="chat-model"');
  expect(markup).toContain('<label for="chat-reasoning">Reasoning</label><select id="chat-reasoning"');
  expect(markup).toContain('value="research-primary" selected=""');
  expect(markup).toContain('value="medium" selected=""');
  expect(markup).toContain('aria-expanded="true" aria-label="Collapse sidebar"');
  expect(markup).toContain('aria-expanded="false" aria-label="Open navigation"');
  expect(markup).not.toMatch(/temperature|top-p|token budget|endpoint|byok/i);
});

test("uses explicit loading and Not Found titles instead of an Untitled fallback", () => {
  const thread = {
    id: "00000000-0000-4000-8000-000000000111",
    kind: "session" as const,
  };
  const loading = renderToStaticMarkup(
    <AuthProvider>
      <ChatShell
        catalogState={catalogState}
        navigateChat={vi.fn()}
        preferenceState={{ status: "loading" }}
        reloadCatalog={vi.fn()}
        selectedSessionState={{ status: "loading" }}
        sessionHistory={sessionHistory}
        thread={thread}
      />
    </AuthProvider>,
  );
  expect(loading).toContain("Loading Chat");
  expect(loading).not.toContain("<strong>Untitled</strong>");

  const missing = renderToStaticMarkup(
    <AuthProvider>
      <ChatShell
        catalogState={catalogState}
        navigateChat={vi.fn()}
        preferenceState={{ status: "not-found" }}
        reloadCatalog={vi.fn()}
        selectedSessionState={{ status: "not-found" }}
        sessionHistory={sessionHistory}
        thread={thread}
      />
    </AuthProvider>,
  );
  expect(missing).toContain("<strong>Chat not found</strong>");
  expect(missing).not.toContain("<strong>Untitled</strong>");
});

test("keeps New Chat ephemeral until a valid opaque session is present", () => {
  const generated = "00000000-0000-4000-8000-000000000111";
  expect(readBrowserChatThread("", () => generated)).toEqual({
    id: generated,
    kind: "new",
  });
  expect(readBrowserChatThread("?session=prototype", () => generated)).toEqual({
    id: null,
    kind: "invalid",
  });
  expect(readBrowserChatThread(
    "?session=AA000000-0000-4000-8000-000000000222",
    () => generated,
  )).toEqual({
    id: "aa000000-0000-4000-8000-000000000222",
    kind: "session",
  });
  expect(readBrowserChatThread(
    "?session=00000000-0000-4000-8000-000000000111&session=00000000-0000-4000-8000-000000000222",
    () => generated,
  )).toEqual({ id: null, kind: "invalid" });
  expect(readBrowserChatThread(
    "?session=00000000-0000-0000-0000-000000000000",
    () => generated,
  )).toEqual({ id: null, kind: "invalid" });
  expect(readBrowserChatThread(
    "?session=ffffffff-ffff-ffff-ffff-ffffffffffff",
    () => generated,
  )).toEqual({ id: null, kind: "invalid" });
  expect(chatSessionHref(generated)).toBe(
    "/chat?session=00000000-0000-4000-8000-000000000111",
  );
});

test("renders explicit full and compact text for an active Agent run", () => {
  const markup = renderToStaticMarkup(
    <SessionHistoryList
      controller={{
        ...sessionHistory,
        sessions: [{
          active_run: true,
          activity_at: "2020-01-02T00:00:00.000000Z",
          created_at: "2020-01-01T00:00:00.000000Z",
          id: "00000000-0000-4000-8000-000000000111",
          title: "Quality Alpha",
          version: "2020-01-02T00:00:00.000000Z",
        }],
      }}
      currentSessionId={null}
      navigate={vi.fn()}
      navigationInteractive={true}
      restoreFocus={vi.fn()}
    />,
  );

  expect(markup).toContain('class="chat-session-run-full">Running</span>');
  expect(markup).toContain('class="chat-session-run-compact">Run</span>');
  expect(markup).toContain('aria-label="Quality Alpha, Running"');
});

test("counts the UTF-8 payload rather than JavaScript code units", () => {
  expect(chatMessageBytes("alpha")).toBe(5);
  expect(chatMessageBytes("低波动")).toBe(9);
  expect(chatMessageBytes("α")).toBe(2);
});

test.each(AGENT_FAILURE_CODES)("renders only safe copy and legal controls for %s", (code) => {
  const markup = renderToStaticMarkup(<ChatFailureNotice code={code} onReconnect={vi.fn()} onRetry={vi.fn()} onRevise={vi.fn()} onSelectModel={vi.fn()} retryDisabled={false} />);
  expect(markup).toContain(`data-failure-code="${code}"`);
  expect(markup).toContain(agentFailure(code).label);
  expect(markup).toContain('role="alert"');
  expect(markup).not.toMatch(/confirm|approval|automatic retry|stack trace/i);
  if (agentFailure(code).action === "reconnect") expect(markup).not.toContain("Retry with selected model");
});

test("replayed error remains one failed terminal state even if the client later reports an exception", async () => {
  const setError = vi.fn();
  const setStatus = vi.fn();
  const onRunIdentity = vi.fn();
  const attached = startExistingSessionConnection({
    connect: async (subscriber) => {
      await subscriber.onRunStartedEvent?.({ event: { runId: "stored-run", selection: { modelKey: "removed-model", providerModelId: "historical-id", reasoningEffort: "high" } } } as never);
      await subscriber.onRunErrorEvent?.({ event: { code: "PROVIDER_RATE_LIMIT", message: "private-response-canary" } } as never);
      await subscriber.onRunFailed?.({ error: new Error("private-sdk-canary") } as never);
      await subscriber.onRunFinishedEvent?.({} as never);
    },
    failRunningTools: vi.fn(), finishTool: vi.fn(), onSessionChanged: vi.fn(), onRunIdentity,
    onTitleMaySettle: vi.fn(), setError, setStatus, shouldWatchTitle: () => false, startTool: vi.fn(), threadId: "thread",
  });
  await attached.settled;
  expect(setStatus.mock.calls.map(([value]) => value)).toEqual(["loading-history", "running", "failed"]);
  expect(setError.mock.calls.map(([value]) => value)).toEqual([null, "PROVIDER_RATE_LIMIT"]);
  expect(onRunIdentity).toHaveBeenCalledWith("stored-run", { modelKey: "removed-model", providerModelId: "historical-id", reasoningEffort: "high" });
  attached.dispose();
});

test.each(["failed", "complete"] as const)("a real AG-UI reconnect preserves its received %s terminal after a later protocol failure", async (terminal) => {
  const runtime = new CopilotKitCoreReact({ runtimeUrl: "http://runtime.test/api/agent/copilotkit", runtimeTransport: "rest", deferInitialConnection: true });
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ version: "1.69.3", agents: { research: {} }, mode: "sse" })));
  const logging = vi.spyOn(console, "error").mockImplementation(() => undefined);
  try {
    runtime.connect();
    await vi.waitFor(() => expect(runtime.runtimeConnectionStatus).toBe("connected"));
    const { agent, unregister } = runtime.registerProxiedAgent({ agentId: "reconnect-fixture", runtimeAgentId: "research" });
    try {
      const threadId = "00000000-0000-4000-8000-000000000111";
      agent.threadId = threadId;
      let stream!: ReadableStreamDefaultController<Uint8Array>;
      agent.fetch = createAgentFetch(async () => new Response(new ReadableStream<Uint8Array>({ start(controller) {
        stream = controller;
        for (const event of [
          { type: "RUN_STARTED", threadId, runId: "00000000-0000-4000-8000-000000000112" },
          terminal === "failed"
            ? { type: "RUN_ERROR", code: "PROVIDER_RATE_LIMIT", message: "Safe provider failure" }
            : { type: "RUN_FINISHED", threadId, runId: "00000000-0000-4000-8000-000000000112" },
        ]) controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
      } }), { headers: { "content-type": "text/event-stream" } }));
      const errors: Array<string | null> = [];
      const statuses: ConversationStatus[] = [];
      const attached = startExistingSessionConnection({
        connect: async (subscriber) => { await agent.connectAgent(undefined, subscriber); },
        failRunningTools: vi.fn(), finishTool: vi.fn(), onSessionChanged: vi.fn(), onRunIdentity: vi.fn(),
        onTitleMaySettle: vi.fn(), shouldWatchTitle: () => false, startTool: vi.fn(), threadId,
        setStatus: (status) => {
          statuses.push(status);
          if (status === terminal) {
            // A trailing frame after the terminal makes the real AG-UI verifier
            // reject connectAgent after it has already delivered the terminal.
            stream.enqueue(new TextEncoder().encode(`data: ${JSON.stringify({ type: "TEXT_MESSAGE_CONTENT", messageId: "invalid-after-terminal", delta: "late" })}\n\n`));
            stream.close();
          }
        },
        setError: (code) => { errors.push(code); },
      });
      await attached.settled;
      expect(errors).toEqual(terminal === "failed" ? [null, "PROVIDER_RATE_LIMIT"] : [null]);
      expect(statuses).toEqual(["loading-history", "running", terminal]);
      attached.dispose();
    } finally { unregister(); }
  } finally { logging.mockRestore(); vi.unstubAllGlobals(); }
});

test("keeps an active reconnect subscribed when its title settles before the terminal event", async () => {
  const connectionState: {
    resolve?: () => void;
    subscriber?: AgentSubscriber;
  } = {};
  let titleMaySettle = true;
  const statuses: ConversationStatus[] = [];
  const onTitleMaySettle = vi.fn();
  const connection = new Promise<void>((resolve) => {
    connectionState.resolve = resolve;
  });
  const attached = startExistingSessionConnection({
    connect: async (candidate) => {
      connectionState.subscriber = candidate;
      await connection;
    },
    failRunningTools: vi.fn(),
    finishTool: vi.fn(),
    onSessionChanged: vi.fn(),
    onRunIdentity: vi.fn(),
    onTitleMaySettle,
    setError: vi.fn(),
    setStatus: (status) => statuses.push(status),
    shouldWatchTitle: () => titleMaySettle,
    startTool: vi.fn(),
    threadId: "00000000-0000-4000-8000-000000000111",
  });
  const subscriber = connectionState.subscriber;
  if (subscriber === undefined) throw new Error("Reconnect did not install its subscriber");

  await subscriber.onRunStartedEvent?.({ event: { runId: "00000000-0000-4000-8000-000000000112" } } as never);
  expect(statuses.at(-1)).toBe("running");

  titleMaySettle = false;
  await subscriber.onRunFinishedEvent?.({} as never);
  expect(statuses.at(-1)).toBe("complete");
  expect(onTitleMaySettle).not.toHaveBeenCalled();

  connectionState.resolve?.();
  await attached.settled;
  expect(statuses.at(-1)).toBe("complete");
  attached.dispose();
});

test("shows distinct rename guidance for local input and malformed server responses", () => {
  expect(sessionDialogErrorMessage("rename", new AgentSessionTitleInvalidError())).toBe(
    "Choose a title between 1 and 80 characters other than Untitled.",
  );
  expect(sessionDialogErrorMessage("rename", new AgentSessionInvalidError())).toBe(
    "The Chat title response was invalid.",
  );
});

test("renders Tool lifecycle metadata without arguments or results", () => {
  const messages: Message[] = [{
    content: "Check the current data.",
    id: "00000000-0000-4000-8000-000000000001",
    role: "user",
  }, {
    content: "",
    id: "00000000-0000-4000-8000-000000000002",
    role: "assistant",
    toolCalls: [{
      function: {
        arguments: '{"formula":"browser-must-not-render-this"}',
        name: "get_research_context",
      },
      id: "provider-tool-call-1",
      type: "function",
    }],
  }, {
    content: safeRunMarker,
    id: "00000000-0000-4000-8000-000000000003",
    role: "tool",
    toolCallId: "provider-tool-call-1",
  }];
  const timeline = chatTimelineItems(messages, [{
    durationMs: 42.6,
    id: "provider-tool-call-1",
    name: "get_research_context",
    status: "completed",
  }]);
  expect(timeline).toMatchObject([
    { kind: "message", role: "user" },
    {
      activity: {
        durationMs: 42.6,
        name: "get_research_context",
        resource: {
          id: "run_0123456789abcdef0123",
          kind: "research_run",
          status: "queued",
        },
        status: "completed",
      },
      kind: "tool",
    },
  ]);
  expect(JSON.stringify(timeline)).not.toMatch(/browser-must-not-render/);

  const markup = renderToStaticMarkup(<ToolActivityRow activity={{
    durationMs: 42.6,
    id: "provider-tool-call-1",
    name: "get_research_context",
    resource: {
      id: "run_0123456789abcdef0123",
      kind: "research_run",
      status: "queued",
    },
    status: "completed",
  }} />);
  expect(markup).toContain("MCP Tool");
  expect(markup).toContain("get_research_context");
  expect(markup).toContain("Completed");
  expect(markup).toContain("43 ms");
  expect(markup).toContain('href="/research-runs/run_0123456789abcdef0123"');
  expect(markup).toContain("queued");
  expect(markup).not.toMatch(/argument|result/i);
});

test("keeps Tool and final Assistant text in the same order before and after reload", () => {
  const assistantId = "00000000-0000-4000-8000-000000000002";
  const toolCall = {
    function: { arguments: "{}", name: "get_research_run_result" },
    id: "provider-tool-call-order",
    type: "function" as const,
  };
  const toolResult: Message = {
    content: safeRunMarker,
    id: "00000000-0000-4000-8000-000000000003",
    role: "tool",
    toolCallId: toolCall.id,
  };
  const live = chatTimelineItems([{
    content: "",
    id: assistantId,
    role: "assistant",
    toolCalls: [toolCall],
  }, toolResult, {
    content: "Authoritative result artifact",
    id: `${assistantId}-agui-text`,
    role: "assistant",
  }]);
  const replay = chatTimelineItems([{
    content: "Authoritative result artifact",
    id: assistantId,
    role: "assistant",
    toolCalls: [toolCall],
  }, toolResult]);

  expect(live.map((item) => item.kind)).toEqual(["tool", "message"]);
  expect(replay.map((item) => item.kind)).toEqual(["tool", "message"]);
  expect(live.map((item) => item.kind === "message"
    ? item.content
    : item.kind === "tool" ? item.activity.name : item.message.id))
    .toEqual(replay.map((item) => (
      item.kind === "message"
        ? item.content
        : item.kind === "tool" ? item.activity.name : item.message.id
    )));
});

test("places a durable A2UI Activity in the timeline without an empty Assistant placeholder", () => {
  const timeline = chatTimelineItems([{
    content: "",
    id: "00000000-0000-4000-8000-000000000120",
    role: "assistant",
  }, {
    activityType: "a2ui-surface",
    content: {
      a2ui_operations: [],
    },
    id: "a2ui-surface-generate-call",
    role: "activity",
  }]);

  expect(timeline).toMatchObject([{
    id: "a2ui:a2ui-surface-generate-call",
    kind: "a2ui",
  }]);
  expect(JSON.stringify(timeline)).not.toContain("Responding");
});

test("renders research Markdown while disabling raw HTML, images, and non-Run links", () => {
  const markup = renderToStaticMarkup(
    <AssistantMarkdown
      content={`### Research completed

**Formula:** \`rank(-abs(pct_change(close, 1)))\`

[Open ResearchRun](/research-runs/run_0123456789abcdef0123)
[External](https://example.com/private)
![remote](https://example.com/pixel.png)
<img src="https://example.com/raw.png" onerror="alert(1)">
<script>alert("unsafe")</script>`}
      streaming={false}
    />,
  );

  expect(markup).toContain("Research completed");
  expect(markup).toContain("rank(-abs(pct_change(close, 1)))");
  expect(markup).toContain('href="/research-runs/run_0123456789abcdef0123"');
  expect(markup).toContain("External");
  expect(markup).not.toContain("https://example.com/private");
  expect(markup).not.toMatch(/<img|<script|onerror|pixel\.png|raw\.png/);
});
