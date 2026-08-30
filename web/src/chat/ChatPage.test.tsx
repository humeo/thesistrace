import type { Message } from "@ag-ui/core";
import { expect, test, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { AuthProvider } from "../auth/AuthProvider";
import {
  AssistantMarkdown,
  ChatShell,
  ToolActivityRow,
  chatMessageBytes,
  chatSessionHref,
  chatTimelineItems,
  readBrowserChatThread,
} from "./ChatPage";

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

test("renders the standalone Chat hierarchy and safe model controls", () => {
  const markup = renderToStaticMarkup(
    <AuthProvider>
      <ChatShell
        catalogState={catalogState}
        preferenceState={{ status: "not-required" }}
        reloadCatalog={vi.fn()}
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

test("keeps New Chat ephemeral until a valid opaque session is present", () => {
  const generated = "00000000-0000-4000-8000-000000000111";
  expect(readBrowserChatThread("", () => generated)).toEqual({
    id: generated,
    persisted: false,
  });
  expect(readBrowserChatThread("?session=prototype", () => generated)).toEqual({
    id: generated,
    persisted: false,
  });
  expect(readBrowserChatThread(
    "?session=AA000000-0000-4000-8000-000000000222",
    () => generated,
  )).toEqual({
    id: "aa000000-0000-4000-8000-000000000222",
    persisted: true,
  });
  expect(chatSessionHref(generated)).toBe(
    "/chat?session=00000000-0000-4000-8000-000000000111",
  );
});

test("counts the UTF-8 payload rather than JavaScript code units", () => {
  expect(chatMessageBytes("alpha")).toBe(5);
  expect(chatMessageBytes("低波动")).toBe(9);
  expect(chatMessageBytes("α")).toBe(2);
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
  expect(live.map((item) => item.kind === "message" ? item.content : item.activity.name))
    .toEqual(replay.map((item) => (
      item.kind === "message" ? item.content : item.activity.name
    )));
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
