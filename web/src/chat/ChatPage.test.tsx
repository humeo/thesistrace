import { expect, test, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { AuthProvider } from "../auth/AuthProvider";
import {
  ChatShell,
  chatMessageBytes,
  chatSessionHref,
  readBrowserChatThread,
} from "./ChatPage";

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
