import { expect, test, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { AuthProvider } from "../auth/AuthProvider";
import { ChatShell } from "./ChatPage";

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
      <ChatShell catalogState={catalogState} reloadCatalog={vi.fn()} />
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
