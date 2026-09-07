import { expect, test, vi } from "vitest";
import type { SessionHistoryController } from "../chat/useSessionHistory";
import { renderToStaticMarkup } from "react-dom/server";

import { AuthProvider } from "../auth/AuthProvider";
import { AppShell } from "./AppShell";

const sessionHistory: SessionHistoryController = {
  deleteSession: vi.fn(), error: null, loadMore: vi.fn(), loadingMore: false,
  nextCursor: null, refresh: vi.fn(), refreshVersion: 0, renameSession: vi.fn(),
  sessions: [], status: "ready", watchGeneratedTitle: vi.fn(),
};

function renderShell(
  currentPath: string,
  content = "Current resource",
  isOperator = false,
): string {
  return renderToStaticMarkup(
    <AuthProvider>
      <AppShell currentPath={currentPath} currentSessionId={null} isNewChat={currentPath === "/chat"}
        isOperator={isOperator} navigate={vi.fn()} sessionHistory={sessionHistory}>
        <section>{content}</section>
      </AppShell>
    </AuthProvider>,
  );
}

test("keeps the conversation sidebar available on Data without a separate Chat destination", () => {
  const markup = renderShell("/data");

  expect(markup).toContain('aria-label="Chats"');
  expect(markup).toContain("New Chat");
  expect(markup).not.toContain(">Chat<");
  expect(markup).not.toContain(">Chats<");
});

test("renders New Chat, Research resources and MCP with only the active content", () => {
  const markup = renderShell("/research-runs", "Selected resource");

  expect(markup.match(/<a /g)).toHaveLength(7);
  expect(markup).toContain('href="/chat"');
  expect(markup).toContain('href="/data"');
  expect(markup).toContain('href="/connections/mcp"');
  expect(markup).toContain('href="/research"');
  expect(markup).not.toContain("Definitions");
  expect(markup).toContain('aria-current="page" href="/research-runs"');
  expect(markup).toContain('href="/daily-tracks"');
  expect(markup).not.toContain("Canonical data");
  expect(markup).not.toContain("Through ");
  expect(markup).not.toContain("Core workspace");
  expect(markup).not.toContain("New research");
  expect(markup).toContain("Selected resource");
});

test("places the Operator destination at the bottom only for the Operator", () => {
  const operatorMarkup = renderShell(
    "/operator/researchers",
    "Operator researchers",
    true,
  );
  const ordinaryMarkup = renderShell("/data");

  expect(operatorMarkup).toContain(
    'aria-current="page" href="/operator/researchers"',
  );
  expect(operatorMarkup.indexOf('href="/operator/researchers"')).toBeGreaterThan(
    operatorMarkup.indexOf('href="/daily-tracks"'),
  );
  expect(operatorMarkup).toContain("Operator researchers");
  expect(ordinaryMarkup).not.toContain('href="/operator/researchers"');
  expect(ordinaryMarkup).not.toContain(">Operator<");

  const dataMarkup = renderShell("/operator/data", "Operator data", true);
  expect(dataMarkup).toContain(
    'aria-current="page" href="/operator/researchers"',
  );
  expect(dataMarkup).toContain("Operator data");
});

test("keeps Research context in the workspace content", () => {
  const markup = renderShell("/research", "Research workspace");

  expect(markup).not.toContain("Canonical data");
  expect(markup).not.toContain("Through ");
  expect(markup).not.toContain("New research");
  expect(markup).toContain("Research workspace");
});

test.each([
  "/chat", "/data", "/research", "/research-runs", "/research-runs/run-example",
  "/daily-tracks", "/daily-tracks/track-example", "/operator/researchers", "/operator/data",
])(
  "shows an expanded sidebar without a shared context bar on %s",
  (currentPath) => {
    const markup = renderShell(currentPath, "Page content", currentPath.startsWith("/operator"));

    expect(markup).not.toContain("app-shell-collapsed");
    expect(markup).toContain('aria-expanded="true" aria-label="Collapse sidebar"');
    expect(markup).not.toContain("context-bar");
    expect(markup).not.toContain("context-breadcrumb");
    expect(markup).toContain("Page content");
  },
);
