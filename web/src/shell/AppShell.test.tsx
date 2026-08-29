import { expect, test } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { AuthProvider } from "../auth/AuthProvider";
import { AppShell } from "./AppShell";

function renderShell(currentPath: string, content = "Current resource"): string {
  return renderToStaticMarkup(
    <AuthProvider>
      <AppShell currentPath={currentPath}>
        <section>{content}</section>
      </AppShell>
    </AuthProvider>,
  );
}

test("renders Chat and the four Research resources with only the active content", () => {
  const markup = renderShell("/research-runs", "Selected resource");

  expect(markup.match(/<a /g)).toHaveLength(6);
  expect(markup).toContain('href="/chat"');
  expect(markup).toContain('href="/data"');
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

test("keeps the Research header focused on navigation and folder context", () => {
  const markup = renderShell("/research", "Research workspace");

  expect(markup).not.toContain("Canonical data");
  expect(markup).not.toContain("Through ");
  expect(markup).not.toContain("New research");
  expect(markup).toContain("Research workspace");
});

test.each(["/chat", "/data", "/research", "/research-runs", "/daily-tracks"])(
  "defaults the sidebar to expanded on %s",
  (currentPath) => {
    const markup = renderShell(currentPath);

    expect(markup).not.toContain("app-shell-collapsed");
    expect(markup).toContain('aria-expanded="true" aria-label="Collapse sidebar"');
  },
);
